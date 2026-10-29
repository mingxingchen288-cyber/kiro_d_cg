"""命令记录与判重（WP-01、WP-02、WP-11、WP-13），表 PF_COMMAND（迁移 wp_0001）。

- 事务的第一条语句插入命令记录，唯一键为（用户、请求键）。同一请求键的命令仍在处理时，Oracle 让这条 INSERT 等待对方
  提交或回滚；等待最多 `wait_seconds` 秒（`.env` 的 `PLATFORM_REQUEST_WAIT_SECONDS`），用连接的调用超时实现，超时返回
  409 REQUEST_IN_PROGRESS。对方提交后这条 INSERT 违反唯一键，读出原记录判重；对方回滚后这条 INSERT 成功，照常执行。
- 命令失败时整个事务回滚，命令记录一起撤销（WP-02），同一请求键可以重新提交；写入管道不自动重试（WP-13）。
- 完成时用一条 UPDATE 写入状态、命令结果和审计差异（WP-11）。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Text, bindparam, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from cost_platform.contracts.decimal_text import format_decimal
from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    Command,
    CommandResult,
    ErrorCode,
    PlatformError,
    RowChange,
    Value,
    dump_wire,
    parse_wire,
)

# 绑定变量名不能用 Oracle 保留字（例如 audit），统一加 b_ 前缀
_INSERT = text(
    "INSERT INTO pf_command (user_id, request_key, operation, page, digest, status, created_at) "
    "VALUES (:b_user, :b_key, :b_operation, :b_page, :b_digest, 'running', :b_time)")
_EXISTING = text("SELECT digest, status, result FROM pf_command WHERE user_id = :b_user AND request_key = :b_key")
_FINISH = text(
    "UPDATE pf_command SET status = 'done', result = :b_result, audit_diff = :b_audit, finished_at = :b_time "
    "WHERE user_id = :b_user AND request_key = :b_key").bindparams(
    bindparam("b_result", type_=Text), bindparam("b_audit", type_=Text))

_CALL_TIMEOUT = ("DPY-4024", "DPI-1067")
"""python-oracledb 的调用超时（Thin、Thick 模式），连接仍可用。"""


def _text(value: Value | int) -> object:
    """审计差异中的值按 C01 写成文本：数值为十进制文本，日期时间到秒。"""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (Decimal, int)):
        return format_decimal(Decimal(value))
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def audit_rows(changes: list[RowChange]) -> list[dict[str, object]]:
    """审计差异（WP-11）：修改的行逐字段记旧值和新值，新增行记写入的值，删除的行记删除前的值。"""
    rows: list[dict[str, object]] = []
    for c in changes:
        if c.op == "delete":
            fields = {name: {"old": _text(value), "new": None} for name, value in c.old.items()}
        else:
            fields = {name: {"old": _text(c.old.get(name)), "new": _text(value)} for name, value in c.values.items()}
        row: dict[str, object] = {"entity": c.entity, "rowKey": c.row_key}
        if c.op == "add" and c.client_row_id:
            row["clientRowId"] = c.client_row_id
        row.update({"op": c.op, "fields": fields})
        rows.append(row)
    return rows


@contextmanager
def _call_timeout(uow: UnitOfWork, seconds: int) -> Iterator[None]:
    """这一次调用最多等 `seconds` 秒（python-oracledb 的 `call_timeout`），结束后恢复连接原来的设置。"""
    driver = uow.connection.connection.driver_connection
    previous = getattr(driver, "call_timeout", None)
    if previous is None:  # 不是 Oracle 连接（模拟验证用的 SQLite）
        yield
        return
    driver.call_timeout = seconds * 1000
    try:
        yield
    finally:
        driver.call_timeout = previous


class OracleCommandRecorder:
    def __init__(self, wait_seconds: int = 5) -> None:
        self._wait = int(wait_seconds)

    def begin(self, uow: UnitOfWork, user_id: str, command: Command, now: datetime) -> CommandResult | None:
        key = {"b_user": user_id, "b_key": command.request_key}
        digest = command.content_digest()
        try:
            with _call_timeout(uow, self._wait):
                uow.connection.execute(_INSERT, {**key, "b_operation": command.operation, "b_page": command.page,
                                                 "b_digest": digest, "b_time": now})
            return None
        except IntegrityError:
            found = uow.connection.execute(_EXISTING, key).one()
        except DBAPIError as exc:
            if any(code in str(exc.orig) for code in _CALL_TIMEOUT):
                raise PlatformError(ErrorCode.REQUEST_IN_PROGRESS, "同一请求仍在处理，请稍后查看结果") from None
            raise
        if found.digest != digest:
            raise PlatformError(ErrorCode.IDEMPOTENCY_KEY_REUSED, "同一请求键已用于内容不同的命令")
        return parse_wire(CommandResult, json.loads(found.result))

    def finish(self, uow: UnitOfWork, user_id: str, command: Command, result: CommandResult,
               audit: list[RowChange] | None, now: datetime) -> None:
        uow.connection.execute(_FINISH, {
            "b_user": user_id, "b_key": command.request_key, "b_time": now,
            "b_result": json.dumps(dump_wire(CommandResult, result), ensure_ascii=False),
            "b_audit": None if audit is None else json.dumps(audit_rows(audit), ensure_ascii=False),
        })
