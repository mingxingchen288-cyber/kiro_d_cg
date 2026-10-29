"""审批中的新增数据（AP-02、AP-10，C06 7.6、7.8）：主表是新增的；主表已有、明细是新增的。

7.8 的审批流审核原辅料的新增和修改，新增一行聚维酮K30（物料 25）、单价 80，和物料清单的 75 不同，所以保存时进入审批。
新增的行在送审时预留主键，库里不写；审批详情中标为"新增"，只有新值，物料名称按物料 Lookup 用物料ID查出；最终批准时插入，
并按审批流把物料清单 25 的执行价写成 80。
"""

from __future__ import annotations

from typing import Any

from cost_platform.contracts import types as t

from .support import ADMIN, YANGNA, Harness, cost

MASTER_TMP = "tmp-00000000-0000-4000-8000-0000000000b1"
DETAIL_TMP = "tmp-00000000-0000-4000-8000-0000000000b2"


def k30_row() -> dict[str, Any]:
    return {"entity": "COST_MATERIAL", "op": "add", "clientRowId": DETAIL_TMP,
            "values": {"GOODSID": "25", "PRICE": "80", "BATCH_QTY": "10"}}


def cells(row: t.ViewRow) -> list[tuple[object, object]]:
    return [(c.before, c.after) for c in row.cells]


def check_goods_block(detail: t.ApprovalDetail) -> None:
    [goods] = detail.view.affected
    [target] = goods.rows
    assert (target.op, target.checked, cells(target)) == ("modify", True, [("25", "25"), ("聚维酮K30", "聚维酮K30"), ("75", "80")])


def test_new_cost_document_shown_as_added_and_inserted_when_approved() -> None:
    """杨娜新建一张成本单，只有聚维酮K30 一行：主表、明细都预留主键，详情中都是"新增"；批准后整张插入，结果没有"已跳过"。"""
    h = Harness(["COST_TO_GOODS"], goods_lookup=True)
    master = {"op": "add", "clientRowId": MASTER_TMP, "values": {"GOODSNAME": "250mg乙酰唑胺片", "MEMO": "新建"}}
    run = h.save(YANGNA, "COST_PINGGU", [{"entity": "COST_PINGGU", "master": master, "details": [k30_row()]}])
    assert run.state.outcome == "approvalSubmitted"
    [approval] = run.state.approvals
    record = h.record(approval.approval_id)
    bill, dtl = record.key_map[MASTER_TMP], record.key_map[DETAIL_TMP]
    assert approval.document.record_key == bill
    assert h.world.row("T_COST_PINGGU", bill) is None and h.world.row("T_COST_PINGGU_DTL", dtl) is None

    detail = h.detail(ADMIN, approval.approval_id)
    [head] = detail.view.master.rows
    assert detail.view.master.columns == ["单据号", "产品", "每盒成本", "千片加工费"]
    assert (head.op, cells(head)[:3]) == ("add", [(None, bill), (None, "250mg乙酰唑胺片"), (None, "8")])
    [material] = [d for d in detail.view.details if d.key == "material"]
    [row] = material.rows
    assert (row.op, row.flows) == ("add", ["COST_TO_GOODS"])
    assert cells(row) == [(None, "25"), (None, "聚维酮K30"), (None, "80"), (None, "800")]
    check_goods_block(detail)

    result = h.pass_(ADMIN, approval.approval_id)
    assert result.outcome == "approvalProcessed" and result.skipped == []
    inserted = h.world.row("T_COST_PINGGU_DTL", dtl)
    assert inserted is not None and (inserted["DOCID"], inserted["GOODSID"], inserted["PRICE"]) == (int(bill), 25, 80)
    assert h.world.row("T_COST_PINGGU", bill)["MEMO"] == "新建"  # type: ignore[index]
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] == 80  # type: ignore[index]
    assert h.frozen() == set()


def test_new_detail_row_of_existing_document() -> None:
    """成本单 2550 已有，只新增一行聚维酮K30：只给这一行预留主键，2550 整张冻结；详情中主表为"修改"（每盒成本变化），
    这一行为"新增"；批准后用预留的主键插入 2550 的明细。"""
    h = Harness(["COST_TO_GOODS"], goods_lookup=True)
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, k30_row())])
    [approval] = run.state.approvals
    record = h.record(approval.approval_id)
    dtl = record.key_map[DETAIL_TMP]
    assert list(record.key_map) == [DETAIL_TMP]
    assert ("T_COST_PINGGU", "2550") in h.frozen() and h.world.row("T_COST_PINGGU_DTL", dtl) is None

    detail = h.detail(ADMIN, approval.approval_id)
    [head] = detail.view.master.rows
    assert (head.op, cells(head)[0], cells(head)[2]) == ("modify", ("2550", "2550"), ("18.425", "26.425"))
    [material] = [d for d in detail.view.details if d.key == "material"]
    [row] = material.rows
    assert (row.op, cells(row)) == ("add", [(None, "25"), (None, "聚维酮K30"), (None, "80"), (None, "800")])
    check_goods_block(detail)

    result = h.pass_(ADMIN, approval.approval_id)
    assert result.outcome == "approvalProcessed" and result.skipped == []
    inserted = h.world.row("T_COST_PINGGU_DTL", dtl)
    assert inserted is not None and (inserted["DOCID"], inserted["GOODSID"], inserted["PRICE"]) == (2550, 25, 80)
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] == 80  # type: ignore[index]
    assert h.frozen() == set()
