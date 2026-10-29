"""判重与命令记录（WP-01、WP-02、WP-11），工程约定第 5 节：先写失败的测试。业务例子 E06。

用 contracts 的事务替代实现（内存 SQLite，表结构与迁移 wp_0001 相同）验证判重的判断；同一请求键并发提交、
处理中等待在 `test_oracle_command_log.py` 中于 d_cg 上验证。
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from cost_platform.contracts import types as t
from cost_platform.pipeline.command_log import OracleCommandRecorder, audit_rows

from .support import KEY_1, KEY_2, MASTER, MATERIAL, NOW, TMP_1, Setup, command, command_factory, command_rows, master_modify


def saved(cmd: t.Command) -> t.CommandResult:
    return t.CommandResult(request_key=cmd.request_key, outcome="saved", rows=[], id_map={}, prompts=[], skipped=[],
                           approvals=[])


def run(recorder: OracleCommandRecorder, factory, user: str, cmd: t.Command, fail: bool = False) -> t.CommandResult:  # type: ignore[no-untyped-def]
    """一个命令事务：插入命令记录 → （失败时抛出）→ 写完成记录并提交。"""
    with factory.begin() as uow:
        replay = recorder.begin(uow, user, cmd, NOW)
        if replay is not None:
            return replay
        if fail:
            raise t.PlatformError(t.ErrorCode.RULE_REJECTED, "规则拒绝")
        result = saved(cmd)
        recorder.finish(uow, user, cmd, result, None, NOW)
        uow.commit()
        return result


def test_e06_same_key_same_content_returns_original_result() -> None:
    factory, recorder = command_factory(), OracleCommandRecorder()
    cmd = command([master_modify("1001", {"MEMO": "测试"})])
    first = run(recorder, factory, "112", cmd)
    with factory.begin() as uow:
        assert recorder.begin(uow, "112", cmd, NOW) == first  # 第二次不执行业务流程，直接返回第一次的结果
    [row] = command_rows(factory)
    assert (row["user_id"], row["request_key"], row["status"]) == ("112", KEY_1, "done")
    assert row["operation"] == "COST_PINGGU.save" and row["page"] == "COST_PINGGU"
    assert row["digest"] == cmd.content_digest()


def test_e06_same_key_different_content_refused() -> None:
    factory, recorder = command_factory(), OracleCommandRecorder()
    run(recorder, factory, "112", command([master_modify("1001", {"MEMO": "测试"})]))
    with factory.begin() as uow, pytest.raises(t.PlatformError) as caught:
        recorder.begin(uow, "112", command([master_modify("1001", {"MEMO": "别的"})]), NOW)
    assert caught.value.code is t.ErrorCode.IDEMPOTENCY_KEY_REUSED


def test_request_key_is_per_user() -> None:
    factory, recorder = command_factory(), OracleCommandRecorder()
    run(recorder, factory, "112", command([master_modify("1001", {"MEMO": "甲"})]))
    with factory.begin() as uow:
        assert recorder.begin(uow, "113", command([master_modify("1001", {"MEMO": "乙"})]), NOW) is None


def test_failed_command_leaves_no_record_and_key_can_be_reused() -> None:
    """WP-02：任一步失败，命令记录一起撤销，同一请求键可以重新提交。"""
    factory, recorder = command_factory(), OracleCommandRecorder()
    cmd = command([master_modify("1001", {"MEMO": "测试"})], request_key=KEY_2)
    with pytest.raises(t.PlatformError):
        run(recorder, factory, "112", cmd, fail=True)
    assert command_rows(factory) == []
    assert run(recorder, factory, "112", cmd).outcome == "saved"
    assert len(command_rows(factory)) == 1


def test_finish_writes_result_and_audit_in_one_statement() -> None:
    factory, recorder = command_factory(), OracleCommandRecorder()
    cmd = command([master_modify("1001", {"MEMO": "测试"})])
    change = t.RowChange(document=t.DocumentRef(MASTER, "1001"), entity=MASTER, op="modify", row_key="1001",
                         client_row_id=None, values={"MEMO": "测试"}, old={"MEMO": None})
    with factory.begin() as uow:
        recorder.begin(uow, "112", cmd, NOW)
        recorder.finish(uow, "112", cmd, saved(cmd), [change], datetime(2026, 10, 29, 10, 0, 1))
        uow.commit()
    [row] = command_rows(factory)
    assert json.loads(row["result"])["outcome"] == "saved"
    assert json.loads(row["audit_diff"]) == [
        {"entity": MASTER, "rowKey": "1001", "op": "modify", "fields": {"MEMO": {"old": None, "new": "测试"}}}]


class _TableChanges:
    """`TableWriter.changes` 的替代：本事务中写没注册的表的改动。"""

    def __init__(self, changes: list[t.RowChange]) -> None:
        self._changes = changes

    def changes(self, uow: object) -> list[t.RowChange]:
        return list(self._changes)


def test_complete_records_approval_processed_with_table_writer_audit() -> None:
    """C06 7.5 物料清单改价审批的最终批准：业务表没有写入，只把 ZX_PRICE 写到没注册的表 T_COST_GOODS（WP-19）。
    `complete` 给出 approvalProcessed，命令记录的审计差异记下这次改动（不看页面的 audit）。"""
    goods = t.RowChange(document=t.DocumentRef("T_COST_GOODS", "25"), entity="T_COST_GOODS", op="modify", row_key="25",
                        client_row_id=None, values={"ZX_PRICE": Decimal("90.1235")}, old={"ZX_PRICE": Decimal("75")})
    factory = command_factory()
    recorder = OracleCommandRecorder(tables=_TableChanges([goods]))
    cmd = command([], page=None, operation="approval.pass", params={"approvalId": "203"})
    approval = t.ApprovalRef(approval_id="203", document=t.RecordRef(entity="GOODS_PRICE", record_key="25"), status="approved",
                             level=1, flows=["GOODS_PRICE_CHANGE"])
    state = t.CommandState(command=cmd)
    state.approvals.append(approval)
    with factory.begin() as uow:
        recorder.begin(uow, "112", cmd, NOW)
        result = recorder.complete(uow, state, Setup().context())
        uow.commit()
    assert result.outcome == "approvalProcessed" and result.approvals == [approval]
    [row] = command_rows(factory)
    assert row["status"] == "done" and json.loads(row["result"])["outcome"] == "approvalProcessed"
    assert json.loads(row["audit_diff"]) == [{"entity": "T_COST_GOODS", "rowKey": "25", "op": "modify",
                                              "fields": {"ZX_PRICE": {"old": "75", "new": "90.1235"}}}]


def test_complete_unchanged_writes_no_record() -> None:
    """WP-10：提交的值与当前值相同，结果为 unchanged，命令记录不写完成状态（调用方不提交）。"""
    factory, recorder = command_factory(), OracleCommandRecorder()
    cmd = command([master_modify("1002", {"MEMO": "旧备注"})])
    with factory.begin() as uow:
        recorder.begin(uow, "112", cmd, NOW)
        result = recorder.complete(uow, t.CommandState(command=cmd), Setup().context())
        assert result.outcome == "unchanged"
        assert [r["status"] for r in uow.connection.execute(text("SELECT status FROM pf_command")).mappings()] == ["running"]


def test_audit_rows_for_add_and_delete() -> None:
    """WP-11：新增行记写入的值，删除的行记删除前的值；数值按十进制文本，日期时间到秒。"""
    ref = t.DocumentRef(MASTER, "1001")
    add = t.RowChange(document=ref, entity=MATERIAL, op="add", row_key="9001", client_row_id=TMP_1,
                      values={"GOODSID": Decimal(115), "PRICE": Decimal("1.20")}, old={})
    delete = t.RowChange(document=ref, entity=MATERIAL, op="delete", row_key="5002", client_row_id=None, values={},
                         old={"DTLID": Decimal(5002), "PRICE": Decimal("47.00"), "MEMO": None,
                              "CREATED": datetime(2026, 1, 5, 9, 0, 0)})
    assert audit_rows([add, delete]) == [
        {"entity": MATERIAL, "rowKey": "9001", "clientRowId": TMP_1, "op": "add",
         "fields": {"GOODSID": {"old": None, "new": "115"}, "PRICE": {"old": None, "new": "1.20"}}},
        {"entity": MATERIAL, "rowKey": "5002", "op": "delete",
         "fields": {"DTLID": {"old": "5002", "new": None}, "PRICE": {"old": "47.00", "new": None}, "MEMO": {"old": None, "new": None},
                    "CREATED": {"old": "2026-01-05T09:00:00", "new": None}}},
    ]
