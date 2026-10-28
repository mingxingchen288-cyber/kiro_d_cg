"""命令记录与判重（WP-01、WP-11），表 PF_COMMAND。"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Text, bindparam, text
from sqlalchemy.exc import IntegrityError

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
    """审计差异（WP-11）：修改的行逐字段记旧值和新值。"""
    return [
        {"entity": c.entity, "rowKey": c.row_key, "op": c.op,
         "fields": {name: {"old": _text(c.old.get(name)), "new": _text(value)} for name, value in c.values.items()}}
        for c in changes
    ]


class OracleCommandRecorder:
    def begin(self, uow: UnitOfWork, user_id: str, command: Command, now: datetime) -> CommandResult | None:
        key = {"b_user": user_id, "b_key": command.request_key}
        digest = command.content_digest()
        try:
            uow.connection.execute(_INSERT, {**key, "b_operation": command.operation, "b_page": command.page,
                                             "b_digest": digest, "b_time": now})
            return None
        except IntegrityError:
            found = uow.connection.execute(_EXISTING, key).one()
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
