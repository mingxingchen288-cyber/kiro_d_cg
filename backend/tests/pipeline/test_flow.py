"""按架构第 7 节的顺序调用本模块的能力，验证业务例子和模块说明第 7 节列出的场景（模拟验证）。

计算用 rules-core 的替代实现，按单据返回预设的结果；冻结检查、触发审批、动作展开用替代阶段。
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeStage

from .support import (
    GOODS,
    KEY_1,
    KEY_2,
    MASTER,
    MATERIAL,
    PAGE,
    TMP_1,
    TMP_2,
    Pipeline,
    Setup,
    command,
    command_rows,
    master_modify,
    master_none,
    scales_inspector,
)

D = Decimal


def row_result(entity: str, row_key: str | None = None, client_row_id: str | None = None, **computed: str) -> t.EvalRowResult:
    return t.EvalRowResult(entity=entity, row_key=row_key, client_row_id=client_row_id, computed=computed, fields={},
                           style=t.RowStyle(row=None, cells={}))


def respond(pipeline: Pipeline, *rows: t.EvalRowResult, effects: list[t.RuleEffect] | None = None) -> None:
    pipeline.setup.engine.respond(t.EvalComputed(ok=True, rows=list(rows), effects=effects or []))


def writes(pipeline: Pipeline) -> list[tuple[str, str, list[dict[str, object]]]]:
    return [(w.op, w.entity, w.rows) for w in pipeline.store.writes]


def price_change(price: str = "3.80", **more: str) -> t.Command:
    return command([master_none("1001", [
        {"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {"PRICE": price, **more}}])])


# ---------------------------------------------------------------- 改一格、计算、小数位

def test_e05_writes_price_and_calculated_columns_only() -> None:
    """E05：PRICE 3.50→3.80、USAGE 不变：只写这条明细的 PRICE 和计算带出的 COST_BATCH，以及主表汇总 TOTAL_COST。"""
    pipeline = Pipeline()
    respond(pipeline, row_result(MATERIAL, "5001", COST_BATCH="7.60"), row_result(MATERIAL, "5002", COST_BATCH="47.00"),
            row_result(MASTER, "1001", TOTAL_COST="54.60"))
    ctx = pipeline.setup.context()
    result = pipeline.execute(price_change(USAGE="2"), ctx)
    assert writes(pipeline) == [("update", MATERIAL, [{"rowKey": "5001", "PRICE": D("3.80"), "COST_BATCH": D("7.60")}]),
                                ("update", MASTER, [{"rowKey": "1001", "TOTAL_COST": D("54.60")}])]
    assert result.outcome == "saved"
    assert [(r.entity, r.row_key) for r in result.rows] == [(MATERIAL, "5001"), (MASTER, "1001")]
    material = result.rows[0]
    assert isinstance(material, t.ResultRow)
    assert material.values["PRICE"] == "3.80" and material.values["COST_BATCH"] == "7.60"
    assert material.values["GOODSNAME"] == "硬脂酸镁" and material.frozen is None  # WP-12：含实体的全部字段

    [request] = pipeline.setup.engine.requests
    assert request.phase == "commit" and request.operation == "COST_PINGGU.save" and request.page == PAGE
    assert request.context.user_id == "112" and request.context.today.isoformat() == "2026-10-29"
    edited = request.document.details[MATERIAL][0]
    assert edited.row_key == "5001" and edited.values["PRICE"] == "3.80" and edited.old == {"PRICE": "3.50"}
    assert request.changed == [t.ChangedRow(entity=MATERIAL, row_key="5001", op="modify", fields=["PRICE"])]


def test_e04_calculated_values_rounded_and_result_matches_database() -> None:
    """E04：计算值 1.234567885、-1.234567885 存为 1.23456789、-1.23456789，返回给前端的值与数据库相同。"""
    pipeline = Pipeline()
    respond(pipeline, row_result(MATERIAL, "5001", COST_BATCH="1.234567885"), row_result(MASTER, "1001", TOTAL_COST="-1.234567885"))
    result = pipeline.execute(price_change(), pipeline.setup.context())
    assert pipeline.store.rows[MATERIAL]["5001"]["COST_BATCH"] == D("1.23456789")
    assert pipeline.store.rows[MASTER]["1001"]["TOTAL_COST"] == D("-1.23456789")
    values = {r.entity: r.values for r in result.rows if isinstance(r, t.ResultRow)}
    assert values[MATERIAL]["COST_BATCH"] == "1.23456789" and values[MASTER]["TOTAL_COST"] == "-1.23456789"


def test_column_scale_applies_to_calculated_value() -> None:
    pipeline = Pipeline(inspector=scales_inspector({("T_COST_PINGGU", "TOTAL_COST"): 2}))
    respond(pipeline, row_result(MASTER, "1001", TOTAL_COST="54.605"))
    pipeline.execute(price_change(), pipeline.setup.context())
    assert pipeline.store.rows[MASTER]["1001"]["TOTAL_COST"] == D("54.61")


def test_same_values_write_nothing_and_leave_no_record() -> None:
    """提交的值与当前值相同：不写业务表，命令结果为 unchanged，事务回滚（WP-10 的第二种情况）。"""
    pipeline = Pipeline()
    result = pipeline.execute(price_change("3.5", USAGE="2"), pipeline.setup.context())
    assert result.outcome == "unchanged" and result.rows == []
    assert pipeline.store.writes == [] and command_rows(pipeline.factory) == []


# ---------------------------------------------------------------- 只在改到规则读取的字段时求值（WP-08，用户 2026-10-29 选乙）

# 仿成本核算：明细 COST_BATCH = USAGE * PRICE，主表 TOTAL_COST 汇总明细的 COST_BATCH，明细的用量按主表 APEX_PL 算
COST_RULE_FIELDS = {PAGE: {MASTER: frozenset({"APEX_PL"}), MATERIAL: frozenset({"USAGE", "PRICE", "COST_BATCH"})}}


def test_e01_master_field_not_used_by_rules_writes_only_it() -> None:
    """E01 的形状：成本单 1001 主表的 MEMO 改为"测试"。规则不读 MEMO：不读明细、不求值，只写 MEMO，其余列不变。"""
    pipeline = Pipeline(setup=Setup(rule_fields=COST_RULE_FIELDS))
    result = pipeline.execute(command([master_modify("1001", {"MEMO": "测试"})]), pipeline.setup.context())
    assert result.outcome == "saved"
    assert writes(pipeline) == [("update", MASTER, [{"rowKey": "1001", "MEMO": "测试"}])]
    assert pipeline.setup.engine.requests == [] and pipeline.store.detail_loads == []
    assert pipeline.store.rows[MASTER]["1001"]["TOTAL_COST"] == D("54.00")


def test_master_field_used_by_rules_recalculates_whole_document() -> None:
    """主表的 APEX_PL 改为 120000：规则读这个字段，读出两条明细、按整张单据求值，计算带出的 TOTAL_COST 一起写。"""
    pipeline = Pipeline(setup=Setup(rule_fields=COST_RULE_FIELDS))
    respond(pipeline, row_result(MASTER, "1001", TOTAL_COST="64.80"))
    result = pipeline.execute(command([master_modify("1001", {"APEX_PL": "120000"})]), pipeline.setup.context())
    assert result.outcome == "saved"
    assert writes(pipeline) == [("update", MASTER, [{"rowKey": "1001", "APEX_PL": D("120000"), "TOTAL_COST": D("64.80")}])]
    [request] = pipeline.setup.engine.requests
    assert [r.row_key for r in request.document.details[MATERIAL]] == ["5001", "5002"]
    assert pipeline.store.detail_loads == [["1001"]]


# ---------------------------------------------------------------- 规则拒绝、提示、必填

def test_rule_reject_writes_nothing() -> None:
    pipeline = Pipeline()
    effect = t.RejectEffect(kind="reject", rule="R_PRICE_RANGE", message="价格超出范围", entity=MATERIAL, row_key="5001",
                            field="PRICE")
    respond(pipeline, effects=[effect])
    with pytest.raises(t.PlatformError) as caught:
        pipeline.execute(price_change("380"), pipeline.setup.context())
    assert caught.value.code is t.ErrorCode.RULE_REJECTED
    assert [(d.message, d.entity, d.row_key, d.field) for d in caught.value.details] == [
        ("价格超出范围", MATERIAL, "5001", "PRICE")]
    assert pipeline.store.writes == [] and command_rows(pipeline.factory) == []


def test_rule_prompt_in_result() -> None:
    pipeline = Pipeline()
    effect = t.PromptEffect(kind="prompt", rule="R_MARGIN_LOW", message="毛利率低于 5%", entity=MASTER, row_key="1001",
                            field="TOTAL_COST")
    respond(pipeline, effects=[effect])
    result = pipeline.execute(price_change(), pipeline.setup.context())
    assert result.prompts == [t.Prompt(rule="R_MARGIN_LOW", message="毛利率低于 5%", entity=MASTER, row_key="1001",
                                       field="TOTAL_COST")]


def test_required_checked_on_added_and_modified_rows() -> None:
    """WP-07：新增的明细没有填必填的 MEMO：VALIDATION_FAILED，逐项给出字段。数值字段没有配置默认值时为 0（C06 第 2 节），
    所以必填的 USAGE 不为空。"""
    pipeline = Pipeline(setup=Setup(required={MATERIAL: ["MEMO", "USAGE"]}))
    cmd = command([master_none("1001", [{"entity": MATERIAL, "op": "add", "clientRowId": TMP_1, "values": {"PRICE": "1"}}])])
    with pytest.raises(t.PlatformError) as caught:
        pipeline.execute(cmd, pipeline.setup.context())
    assert caught.value.code is t.ErrorCode.VALIDATION_FAILED
    assert [(d.entity, d.client_row_id, d.field) for d in caught.value.details] == [(MATERIAL, TMP_1, "MEMO")]


def test_required_not_checked_on_rows_changed_only_by_calculation() -> None:
    """主表 MEMO 必填且为空：只因计算发生变化的主表行不检查，改了的明细行检查通过。"""
    pipeline = Pipeline(setup=Setup(required={MASTER: ["MEMO"], MATERIAL: ["GOODSID"]}))
    respond(pipeline, row_result(MASTER, "1001", TOTAL_COST="54.60"))
    assert pipeline.execute(price_change(), pipeline.setup.context()).outcome == "saved"


def test_required_uses_rule_result() -> None:
    """规则给出的必填（C07 结果的 fields）也检查。"""
    pipeline = Pipeline()
    respond(pipeline, t.EvalRowResult(entity=MATERIAL, row_key="5001", computed={}, fields={"MEMO": t.FieldState(required=True)},
                                      style=t.RowStyle(row=None, cells={})))
    with pytest.raises(t.PlatformError) as caught:
        pipeline.execute(price_change(), pipeline.setup.context())
    assert caught.value.code is t.ErrorCode.VALIDATION_FAILED
    assert [(d.row_key, d.field) for d in caught.value.details] == [("5001", "MEMO")]


# ---------------------------------------------------------------- 新增、删除、idMap、默认值

def test_new_detail_gets_key_and_id_map() -> None:
    pipeline = Pipeline()
    cmd = command([master_none("1001", [
        {"entity": MATERIAL, "op": "add", "clientRowId": TMP_1, "values": {"GOODSID": "115", "USAGE": "1", "PRICE": "1.20"}},
        {"entity": MATERIAL, "op": "delete", "rowKey": "5002"}])])
    respond(pipeline, row_result(MATERIAL, client_row_id=TMP_1, COST_BATCH="1.20"), row_result(MASTER, "1001", TOTAL_COST="8.20"))
    result = pipeline.execute(cmd, pipeline.setup.context())
    assert result.id_map == {TMP_1: "9001"}
    assert pipeline.store.rows[MATERIAL]["9001"]["DOCID"] == D(1001)
    assert pipeline.store.rows[MATERIAL]["9001"]["COST_BATCH"] == D("1.20")
    assert "5002" not in pipeline.store.rows[MATERIAL]
    added = next(r for r in result.rows if r.row_key == "9001")
    assert isinstance(added, t.ResultRow) and added.client_row_id == TMP_1 and added.values["DTLID"] == "9001"
    assert t.DeletedRow(entity=MATERIAL, row_key="5002", deleted=True) in result.rows
    [request] = pipeline.setup.engine.requests
    assert [c.op for c in request.changed] == ["add", "delete"]  # 删除的行仍在请求中，标为 delete（C07 第 2 节）
    assert [r.client_row_id or r.row_key for r in request.document.details[MATERIAL]] == ["5001", "5002", TMP_1]


def test_new_document_with_details_writes_master_first() -> None:
    pipeline = Pipeline()
    cmd = command([{"entity": MASTER, "master": {"op": "add", "clientRowId": TMP_1, "values": {"MEMO": "新单"}},
                    "details": [{"entity": MATERIAL, "op": "add", "clientRowId": TMP_2, "values": {"GOODSID": "115", "USAGE": "1"}}]}])
    result = pipeline.execute(cmd, pipeline.setup.context())
    assert [w.op + ":" + w.entity for w in pipeline.store.writes] == [f"insert:{MASTER}", f"insert:{MATERIAL}"]
    assert result.id_map == {TMP_1: "9001", TMP_2: "9002"}
    assert pipeline.store.rows[MATERIAL]["9002"]["DOCID"] == D(9001)


def test_e28_builtin_default_ignores_client_value() -> None:
    """E28：张三新增一行，前端把 CREATE_BY 改成李四直接调接口提交：数据库中仍为张三。"""
    pipeline = Pipeline()
    cmd = command([{"entity": MASTER, "master": {"op": "add", "clientRowId": TMP_1, "values": {"CREATE_BY": "李四"}}, "details": []}])
    pipeline.execute(cmd, pipeline.setup.context())
    row = pipeline.store.rows[MASTER]["9001"]
    assert row["CREATE_BY"] == "张三" and row["USESTATUS"] == "草稿"


def test_delete_master_deletes_details_first() -> None:
    """WP-06：删除主表行时，同一事务中先物理删除它的全部明细，再删除主表行。"""
    pipeline = Pipeline()
    result = pipeline.execute(command([{"entity": MASTER, "master": {"op": "delete", "rowKey": "1001"}, "details": []}]),
                              pipeline.setup.context())
    assert [(w.op, w.entity) for w in pipeline.store.writes] == [("deleteChildren", MATERIAL), ("delete", MASTER)]
    assert "1001" not in pipeline.store.rows[MASTER]
    assert sorted(pipeline.store.rows[MATERIAL]) == ["5101"]
    assert [r.row_key for r in result.rows] == ["1001", "5001", "5002"]
    assert pipeline.setup.engine.requests == []  # 删除的单据不再计算


# ---------------------------------------------------------------- 审计（WP-11）

def test_audit_recorded_when_page_audits() -> None:
    pipeline = Pipeline()
    cmd = command([{"entity": MASTER, "master": {"op": "delete", "rowKey": "1001"}, "details": []},
                   master_modify("1002", {"MEMO": "新备注"})])
    pipeline.execute(cmd, pipeline.setup.context())
    [row] = command_rows(pipeline.factory)
    audit = json.loads(row["audit_diff"])
    assert [(a["entity"], a["rowKey"], a["op"]) for a in audit] == [
        (MASTER, "1001", "delete"), (MATERIAL, "5001", "delete"), (MATERIAL, "5002", "delete"), (MASTER, "1002", "modify")]
    assert audit[1]["fields"]["PRICE"] == {"old": "3.50", "new": None}
    assert audit[3]["fields"] == {"MEMO": {"old": "旧备注", "new": "新备注"}}


def test_no_audit_when_page_does_not_audit() -> None:
    pipeline = Pipeline(setup=Setup(audit=False))
    pipeline.execute(command([master_modify("1002", {"MEMO": "新备注"})]), pipeline.setup.context())
    [row] = command_rows(pipeline.factory)
    assert row["audit_diff"] is None


# ---------------------------------------------------------------- 判重（E06）

def test_e06_resubmission_executes_once() -> None:
    pipeline = Pipeline()
    ctx = pipeline.setup.context()
    first = pipeline.execute(command([master_modify("1002", {"MEMO": "测试"})]), ctx)
    again = pipeline.execute(command([master_modify("1002", {"MEMO": "测试"})]), ctx)
    assert again == first and pipeline.executions == 1
    with pytest.raises(t.PlatformError) as caught:
        pipeline.execute(command([master_modify("1002", {"MEMO": "别的"})]), ctx)
    assert caught.value.code is t.ErrorCode.IDEMPOTENCY_KEY_REUSED


# ---------------------------------------------------------------- 行权限（WP-03）

def test_row_outside_permission_refuses_whole_command() -> None:
    pipeline = Pipeline()
    pipeline.setup.permission.set_rows(PAGE, MASTER, t.SqlCondition(sql="CREATE_BY = :rp_username", binds={"rp_username": "user112"}))
    pipeline.store.denied.add((MASTER, "1002"))
    with pytest.raises(t.PlatformError) as caught:
        pipeline.execute(command([master_modify("1001", {"MEMO": "a"}), master_modify("1002", {"MEMO": "b"})]),
                         pipeline.setup.context())
    assert caught.value.code is t.ErrorCode.PERMISSION_DENIED
    assert pipeline.store.writes == []


def test_documents_locked_in_key_order_with_one_statement_per_entity() -> None:
    pipeline = Pipeline()
    pipeline.execute(command([master_modify("1002", {"MEMO": "b"}), master_modify("1001", {"MEMO": "a"})]), pipeline.setup.context())
    assert pipeline.store.locked == [(MASTER, ["1001", "1002"])]


# ---------------------------------------------------------------- 提交审批的单据不写（第 5 节）

def test_documents_submitted_for_approval_are_not_written() -> None:
    """E20 的形状：同一次保存改了 1001 的明细 PRICE（提交审批）和 1002 的 MEMO：只写 1002；1001 给出正式值并标冻结。"""
    approval = t.ApprovalRef(approval_id="203", document=t.RecordRef(entity=MASTER, record_key="1001"), status="pending",
                             level=1, flows=["COST_TO_GOODS"])

    def submit(uow, state: t.CommandState, ctx: t.ExecutionContext) -> None:  # type: ignore[no-untyped-def]
        state.pending_documents.add(t.DocumentRef(MASTER, "1001"))
        state.approvals.append(approval)
        state.outcome = "approvalSubmitted"

    pipeline = Pipeline(trigger=FakeStage("触发审批", effect=submit))
    cmd = command([master_none("1001", [{"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {"PRICE": "3.80"}}]),
                   master_modify("1002", {"MEMO": "已写"})])
    result = pipeline.execute(cmd, pipeline.setup.context())
    assert writes(pipeline) == [("update", MASTER, [{"rowKey": "1002", "MEMO": "已写"}])]
    assert result.outcome == "approvalSubmitted" and result.approvals == [approval]
    pending = next(r for r in result.rows if r.row_key == "5001")
    assert isinstance(pending, t.ResultRow) and pending.values["PRICE"] == "3.50"
    assert pending.frozen == t.FrozenMark(approval_id="203")


# ---------------------------------------------------------------- 动作执行中范围外的单据（WP-18）

def sync_to_1002(state: t.CommandState, ctx: t.ExecutionContext) -> None:
    """按钮 updateRecords 的替代展开：找到范围外的成本单 1002，把 5101 的 PRICE 写成 3.80。"""
    state.intents.append(t.RowIntent(document=t.DocumentRef(MASTER, "1002"), entity=MATERIAL, op="modify", row_key="5101",
                                     client_row_id=None, values={"PRICE": D("3.80")}))


def test_intent_document_locked_and_freeze_checked_before_merge() -> None:
    checked: list[list[t.DocumentRef]] = []

    def freeze(uow, state: t.CommandState, ctx: t.ExecutionContext) -> None:  # type: ignore[no-untyped-def]
        checked.append(list(state.involved))

    pipeline = Pipeline(freeze=FakeStage("冻结检查", effect=freeze), actions=[sync_to_1002])
    result = pipeline.execute(price_change(), pipeline.setup.context())
    assert checked == [[t.DocumentRef(MASTER, "1001")], [t.DocumentRef(MASTER, "1002")]]  # 第二次只查新找到的单据
    assert pipeline.store.locked == [(MASTER, ["1001"]), (MASTER, ["1002"])]
    assert pipeline.store.rows[MATERIAL]["5101"]["PRICE"] == D("3.80")
    assert {r.row_key for r in result.rows} == {"5001", "5101"}


def test_intent_document_frozen_by_other_approval_refuses_everything() -> None:
    """WP-18：updateRecords 找到范围外的成本单 1002，它被别的审批冻结：整个命令返回 FROZEN_BY_APPROVAL，什么都不写。"""
    def freeze(uow, state: t.CommandState, ctx: t.ExecutionContext) -> None:  # type: ignore[no-untyped-def]
        if t.DocumentRef(MASTER, "1002") in state.involved:
            raise t.PlatformError(t.ErrorCode.FROZEN_BY_APPROVAL, "单据已被审批冻结",
                                  [t.ErrorDetail(entity=MASTER, row_key="1002", approval_id="300")])

    pipeline = Pipeline(freeze=FakeStage("冻结检查", effect=freeze), actions=[sync_to_1002])
    with pytest.raises(t.PlatformError) as caught:
        pipeline.execute(price_change(), pipeline.setup.context())
    assert caught.value.code is t.ErrorCode.FROZEN_BY_APPROVAL
    assert pipeline.store.writes == [] and command_rows(pipeline.factory) == []


def test_intent_cannot_write_erp_column_of_erp_row() -> None:
    def to_goods(state: t.CommandState, ctx: t.ExecutionContext) -> None:
        state.intents.append(t.RowIntent(document=t.DocumentRef(GOODS, "115"), entity=GOODS, op="modify", row_key="115",
                                         client_row_id=None, values={"PRICE": D("3.80")}))

    pipeline = Pipeline(actions=[to_goods])
    with pytest.raises(t.PlatformError) as caught:
        pipeline.execute(price_change(), pipeline.setup.context(origin=t.Origin(kind="approval", approval_id="203")))
    assert caught.value.code is t.ErrorCode.FIELD_NOT_WRITABLE


def test_second_request_key_independent() -> None:
    pipeline = Pipeline()
    ctx = pipeline.setup.context()
    pipeline.execute(command([master_modify("1002", {"MEMO": "一"})], request_key=KEY_1), ctx)
    pipeline.execute(command([master_modify("1002", {"MEMO": "二"})], request_key=KEY_2), ctx)
    assert pipeline.store.rows[MASTER]["1002"]["MEMO"] == "二" and pipeline.executions == 2
