"""增量补丁：合并、变更计划、小数位、ERP 行、默认值（WP-04、WP-05、WP-06、WP-14、WP-15、WP-16）。

工程约定第 5 节：先写失败的测试。业务例子 E04、E05、E08、E28。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeUnitOfWorkFactory
from cost_platform.pipeline.loader import DocumentLoader, PageSaveInvolved
from cost_platform.pipeline.merge import DocumentMerger, PatchMerger
from cost_platform.pipeline.values import ColumnScales

from .support import (
    GOODS,
    GOODS_ENTITY,
    GOODS_PAGE,
    GOODS_SAVE,
    MASTER,
    MATERIAL,
    MATERIAL_ENTITY,
    NOW,
    TMP_1,
    TMP_2,
    MemoryStore,
    Setup,
    command,
    master_modify,
    master_none,
    scales_inspector,
)

D = Decimal


def merge(cmd: t.Command, setup: Setup | None = None, store: MemoryStore | None = None,
          scales: dict[tuple[str, str], int | None] | None = None,
          ctx: t.ExecutionContext | None = None) -> tuple[t.CommandState, set[tuple[str, str]]]:
    setup = setup or Setup()
    store = store or MemoryStore()
    ctx = ctx or setup.context()
    state = t.CommandState(command=cmd)
    with FakeUnitOfWorkFactory().begin() as uow:
        PageSaveInvolved().run(uow, state, ctx)
        DocumentLoader(store, setup.permission).lock(uow, state, ctx)
        patched = DocumentMerger(setup.permission, ColumnScales(scales_inspector(scales))).merge_patches(state, ctx)
    return state, patched


def changes(state: t.CommandState) -> list[tuple[str, str, str | None, dict[str, Any]]]:
    return [(c.entity, c.op, c.row_key or c.client_row_id, c.values) for c in state.changes.rows]


def refused(cmd: t.Command, **kwargs: Any) -> t.PlatformError:
    with pytest.raises(t.PlatformError) as caught:
        merge(cmd, **kwargs)
    return caught.value


# ---------------------------------------------------------------- 修改

def test_e05_only_changed_field_enters_plan() -> None:
    """E05：只把 5001 的 PRICE 从 3.50 改为 3.80，同时提交一个值没变的 USAGE：变更计划只有 PRICE。"""
    state, patched = merge(command([master_none("1001", [
        {"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {"PRICE": "3.80", "USAGE": "2"}}])]))
    [change] = state.changes.rows
    assert (change.entity, change.op, change.row_key) == (MATERIAL, "modify", "5001")
    assert change.values == {"PRICE": D("3.80")} and change.old == {"PRICE": D("3.50")}
    assert change.document == t.DocumentRef(MASTER, "1001")
    ref = t.DocumentRef(MASTER, "1001")
    candidate_row = next(r for r in state.candidate[ref].details[MATERIAL] if r.row_key == "5001")
    assert candidate_row.values["PRICE"] == D("3.80")
    current_row = next(r for r in state.current[ref].details[MATERIAL] if r.row_key == "5001")
    assert current_row.values["PRICE"] == D("3.50")  # 当前值保持命令开始时读到的值
    assert patched == {(MATERIAL, "5001")}


def test_same_value_is_not_a_change() -> None:
    """数值按数值相等比较：3.5 与 3.50 相同；文本相同也不算变化。"""
    state, _ = merge(command([master_modify("1002", {"MEMO": "旧备注"}, details=[
        {"entity": MATERIAL, "op": "modify", "rowKey": "5101", "changes": {"PRICE": "3.0", "USAGE": "4.000"}}])]))
    assert state.changes.rows == []


def test_master_field_change() -> None:
    """E01 的形状：主表 MEMO 改为"测试"。"""
    state, _ = merge(command([master_modify("1001", {"MEMO": "测试"})]))
    assert changes(state) == [(MASTER, "modify", "1001", {"MEMO": "测试"})]
    assert state.changes.rows[0].old == {"MEMO": None}


def test_value_rounded_before_compare_and_write() -> None:
    """WP-15：PRICE 列为 NUMBER(p,2) 时 3.805 按 3.81 写入；1.234567885 最多保留 8 位。"""
    state, _ = merge(command([master_none("1001", [
        {"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {"PRICE": "3.805", "USAGE": "1.234567885"}}])]),
        scales={("T_COST_PINGGU_DTL", "PRICE"): 2})
    assert state.changes.rows[0].values == {"PRICE": D("3.81"), "USAGE": D("1.23456789")}


@pytest.mark.parametrize(("field", "reason"), [("TOTAL_COST", "计算字段"), ("DOCID", "主键"), ("GOODSNAME", "")])
def test_master_field_not_writable(field: str, reason: str) -> None:
    error = refused(command([master_modify("1001", {field: "1"})]))
    assert error.code is t.ErrorCode.FIELD_NOT_WRITABLE
    assert [(d.entity, d.row_key, d.field) for d in error.details] == [(MASTER, "1001", field)]
    assert reason in (error.details[0].message or "")


def test_detail_parent_key_and_view_only_field_not_writable() -> None:
    """明细的主从关联字段 DOCID、只在视图中的 GOODSNAME 不能改。"""
    for field in ("DOCID", "GOODSNAME", "COST_BATCH", "DTLID"):
        error = refused(command([master_none("1001", [
            {"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {field: "1"}}])]))
        assert error.code is t.ErrorCode.FIELD_NOT_WRITABLE
        assert error.details[0].field == field


# ---------------------------------------------------------------- ERP 行（WP-14，E08）

def goods_command(documents: list[dict[str, Any]]) -> t.Command:
    return command(documents, page=GOODS_PAGE, operation=GOODS_SAVE)


def test_e08_erp_row_price_refused() -> None:
    """物料表 ISERP=1 的行改 PRICE：FIELD_NOT_WRITABLE。"""
    error = refused(goods_command([master_modify("115", {"PRICE": "3.80"}, entity=GOODS)]))
    assert error.code is t.ErrorCode.FIELD_NOT_WRITABLE
    assert [(d.entity, d.row_key, d.field) for d in error.details] == [(GOODS, "115", "PRICE")]
    assert "ERP" in (error.details[0].message or "")


def test_e08_local_row_price_saved() -> None:
    """ISERP=0 的行改 PRICE：进入变更计划。"""
    state, _ = merge(goods_command([master_modify("116", {"PRICE": "48.00"}, entity=GOODS)]))
    assert changes(state) == [(GOODS, "modify", "116", {"PRICE": D("48.00")})]


def test_e08_new_row_is_local_and_erp_column_editable() -> None:
    """新增行（含复制出的行）ISERP 由写入管道设为 0，ERP 列 PRICE 可以填写。"""
    state, _ = merge(goods_command([{"entity": GOODS, "master": {"op": "add", "clientRowId": TMP_1,
                                                                   "values": {"NAME": "硬脂酸镁", "PRICE": "3.50"}},
                                     "details": []}]))
    [change] = state.changes.rows
    assert change.op == "add" and change.client_row_id == TMP_1 and change.row_key is None
    assert change.values["ISERP"] == D(0) and change.values["PRICE"] == D("3.50")
    assert "GOODSID" not in change.values  # 主键在写入时取序列


def test_erp_row_column_in_patch_refused() -> None:
    error = refused(goods_command([master_modify("116", {"ISERP": "1"}, entity=GOODS)]))
    assert error.code is t.ErrorCode.FIELD_NOT_WRITABLE and error.details[0].field == "ISERP"


def test_entity_without_erp_row_erp_column_always_read_only() -> None:
    """没有 erpRow 的实体，ERP 列在所有行上只读。"""
    entity = GOODS_ENTITY.model_copy(update={"erp_row": None})
    current = {"116": t.Row(entity=GOODS, row_key="116", client_row_id=None,
                            values={"GOODSID": D(116), "NAME": "聚维酮K30", "ISERP": D(0), "PRICE": D("47"), "ZX_PRICE": D("47")})}
    patch = t.parse_wire(t.DocumentPatch, master_modify("116", {"PRICE": "48"}, entity=GOODS))
    with pytest.raises(t.PlatformError) as caught:
        PatchMerger().merge(entity, current, patch, frozenset({"PRICE"}))
    assert caught.value.code is t.ErrorCode.FIELD_NOT_WRITABLE


# ---------------------------------------------------------------- 新增与默认值（WP-16，E28）

def test_e28_new_master_row_defaults() -> None:
    """CREATE_BY 默认为当前用户、不可编辑：前端改成李四也写张三；USESTATUS 默认为下拉第一个"草稿"；
    数值字段没有配置默认值时为 0；CREATE_TIME 取当前时间。"""
    state, patched = merge(command([{"entity": MASTER, "master": {"op": "add", "clientRowId": TMP_1,
                                                                   "values": {"MEMO": "新单", "CREATE_BY": "李四"}},
                                     "details": []}]))
    [change] = state.changes.rows
    assert change.op == "add" and change.document == t.DocumentRef(MASTER, TMP_1)
    values = change.values
    assert values["CREATE_BY"] == "张三"
    assert values["USESTATUS"] == "草稿"
    assert values["APEX_PL"] == D(0) and values["TOTAL_COST"] == D(0)
    assert values["CREATE_TIME"] == NOW
    assert values["MEMO"] == "新单"
    assert "DOCID" not in values and "GOODSNAME" not in values  # 主键取序列；其他字段没有默认值时为空，不写
    assert patched == {(MASTER, TMP_1)}
    assert state.candidate[t.DocumentRef(MASTER, TMP_1)].master.values["CREATE_BY"] == "张三"


def test_provided_value_wins_over_default() -> None:
    state, _ = merge(command([{"entity": MASTER, "master": {"op": "add", "clientRowId": TMP_1,
                                                             "values": {"USESTATUS": "已提交", "APEX_PL": "200"}},
                               "details": []}]))
    assert state.changes.rows[0].values["USESTATUS"] == "已提交"
    assert state.changes.rows[0].values["APEX_PL"] == D(200)


def test_new_detail_row_in_existing_document() -> None:
    """C02 第 1 节的样例：在成本单 1001 新增一条原辅料明细，关联字段取主单主键。"""
    state, _ = merge(command([master_none("1001", [
        {"entity": MATERIAL, "op": "add", "clientRowId": TMP_1, "values": {"GOODSID": "115", "USAGE": "1", "PRICE": "1.20"}}])]))
    [change] = state.changes.rows
    assert change.entity == MATERIAL and change.op == "add" and change.client_row_id == TMP_1
    assert change.document == t.DocumentRef(MASTER, "1001")
    assert change.values == {"DOCID": D(1001), "GOODSID": D(115), "USAGE": D(1), "PRICE": D("1.20"), "COST_BATCH": D(0)}
    rows = state.candidate[t.DocumentRef(MASTER, "1001")].details[MATERIAL]
    assert [r.client_row_id for r in rows] == [None, None, TMP_1]


def test_new_document_with_details() -> None:
    """新单据：明细的关联字段在主表取得主键后由写入填上。"""
    state, _ = merge(command([{"entity": MASTER, "master": {"op": "add", "clientRowId": TMP_1, "values": {"MEMO": "新单"}},
                               "details": [{"entity": MATERIAL, "op": "add", "clientRowId": TMP_2,
                                            "values": {"GOODSID": "115", "USAGE": "1"}}]}]))
    master, detail = state.changes.rows
    assert (master.entity, detail.entity) == (MASTER, MATERIAL)
    assert detail.document == t.DocumentRef(MASTER, TMP_1)
    assert detail.values["DOCID"] is None


# ---------------------------------------------------------------- 删除（WP-06）与行已不存在（WP-05）

def test_delete_detail_row_keeps_old_values() -> None:
    state, _ = merge(command([master_none("1001", [{"entity": MATERIAL, "op": "delete", "rowKey": "5002"}])]))
    [change] = state.changes.rows
    assert (change.entity, change.op, change.row_key, change.values) == (MATERIAL, "delete", "5002", {})
    assert change.old["PRICE"] == D("47.00") and change.old["GOODSNAME"] == "聚维酮K30"


def test_delete_master_cascades_to_every_detail() -> None:
    state, _ = merge(command([{"entity": MASTER, "master": {"op": "delete", "rowKey": "1001"}, "details": []}]))
    assert [(c.entity, c.op, c.row_key) for c in state.changes.rows] == [
        (MASTER, "delete", "1001"), (MATERIAL, "delete", "5001"), (MATERIAL, "delete", "5002")]
    assert state.changes.rows[0].old["GOODSNAME"] == "250mg乙酰唑胺片"


def test_missing_detail_row_skipped_by_default() -> None:
    state, _ = merge(command([master_none("1001", [
        {"entity": MATERIAL, "op": "modify", "rowKey": "5003", "changes": {"PRICE": "1"}},
        {"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {"MEMO": "保留"}}])]))
    assert state.skipped == [t.SkippedRow(entity=MATERIAL, row_key="5003", reason="ROW_NOT_FOUND")]
    assert changes(state) == [(MATERIAL, "modify", "5001", {"MEMO": "保留"})]


def test_missing_master_skipped_by_default() -> None:
    store = MemoryStore()
    del store.rows[MASTER]["1002"]
    state, _ = merge(command([master_modify("1002", {"MEMO": "x"}), master_modify("1001", {"MEMO": "y"})]), store=store)
    assert state.skipped == [t.SkippedRow(entity=MASTER, row_key="1002", reason="ROW_NOT_FOUND")]
    assert changes(state) == [(MASTER, "modify", "1001", {"MEMO": "y"})]


def test_missing_row_rejected_when_configured() -> None:
    error = refused(command([master_none("1001", [{"entity": MATERIAL, "op": "delete", "rowKey": "5003"}])]),
                    setup=Setup(row_not_found="reject"))
    assert error.code is t.ErrorCode.ROW_NOT_FOUND
    assert [(d.entity, d.row_key) for d in error.details] == [(MATERIAL, "5003")]


# ---------------------------------------------------------------- 端口 ChangeMerger 的兼容用法（orchestration 的 SaveFlow）

def test_patch_merger_port_modifies_current_rows() -> None:
    current = {"5001": t.Row(entity=MATERIAL, row_key="5001", client_row_id=None,
                             values={"DTLID": D(5001), "PRICE": D("3.50"), "USAGE": D(2), "MEMO": None})}
    patch = t.parse_wire(t.DocumentPatch, master_none("1001", [
        {"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {"PRICE": "3.80", "USAGE": "2"}}]))
    [change] = PatchMerger().merge(MATERIAL_ENTITY, current, patch, frozenset({"PRICE", "USAGE"}))
    assert change.values == {"PRICE": D("3.80")} and current["5001"].values["PRICE"] == D("3.80")


# ---------------------------------------------------------------- 基于属性：变更计划只含值有变化的列

_PRICES = st.decimals(min_value=D("0"), max_value=D("999"), places=2, allow_nan=False, allow_infinity=False)


@settings(max_examples=60, deadline=None)
@given(price=_PRICES, usage=_PRICES, memo=st.one_of(st.none(), st.sampled_from(["", "备注", "测试"])),
       include=st.sets(st.sampled_from(["PRICE", "USAGE", "MEMO"]), min_size=1))
def test_plan_contains_only_changed_columns(price: Decimal, usage: Decimal, memo: str | None, include: set[str]) -> None:
    wire = {"PRICE": str(price), "USAGE": str(usage), "MEMO": memo}
    patch = {name: wire[name] for name in include}
    state, _ = merge(command([master_none("1001", [{"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": patch}])]))
    before = MemoryStore().rows[MATERIAL]["5001"]
    expected = {name: value for name, value in {"PRICE": price, "USAGE": usage, "MEMO": memo or None}.items()
                if name in include and value != before[name]}
    if not expected:
        assert state.changes.rows == []
        return
    [change] = state.changes.rows
    assert change.values == expected
    assert change.old == {name: before[name] for name in expected}
