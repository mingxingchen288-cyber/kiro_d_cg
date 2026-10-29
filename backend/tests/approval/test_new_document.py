"""新建的成本单整张进入审批（AP-02、AP-10，C06 7.6、7.8）。

杨娜新建一张成本单：原辅料一行聚维酮K30（物料 25），单价 80、批量 10；物料清单中 25 的单价为 75。7.8 的审批流审核原辅料的
新增和修改，所以保存时进入审批：主表和明细在送审时预留主键，库里不写；审批详情中主表和明细都是"新增"，只有新值；最终批准
时整张插入，并按审批流把物料清单 25 的执行价写成 80。
"""

from __future__ import annotations

from .support import ADMIN, YANGNA, Harness

MASTER_TMP = "tmp-00000000-0000-4000-8000-0000000000b1"
DETAIL_TMP = "tmp-00000000-0000-4000-8000-0000000000b2"


def new_cost_document() -> dict[str, object]:
    return {"entity": "COST_PINGGU", "master": {"op": "add", "clientRowId": MASTER_TMP, "values": {"MEMO": "新建"}},
            "details": [{"entity": "COST_MATERIAL", "op": "add", "clientRowId": DETAIL_TMP,
                         "values": {"GOODSID": "25", "PRICE": "80", "BATCH_QTY": "10"}}]}


def cells(row: object) -> list[tuple[object, object]]:
    return [(c.before, c.after) for c in row.cells]  # type: ignore[attr-defined]


def test_new_cost_document_shown_as_added_and_inserted_when_approved() -> None:
    h = Harness(["COST_TO_GOODS"])
    run = h.save(YANGNA, "COST_PINGGU", [new_cost_document()])
    assert run.state.outcome == "approvalSubmitted"
    [approval] = run.state.approvals
    record = h.record(approval.approval_id)
    bill, dtl = record.key_map[MASTER_TMP], record.key_map[DETAIL_TMP]
    assert approval.document.record_key == bill
    assert h.world.row("T_COST_PINGGU", bill) is None and h.world.row("T_COST_PINGGU_DTL", dtl) is None

    detail = h.detail(ADMIN, approval.approval_id)
    [master] = detail.view.master.rows
    assert master.op == "add"
    assert detail.view.master.columns == ["单据号", "产品", "每盒成本", "千片加工费"]
    assert cells(master)[0] == (None, bill) and cells(master)[2] == (None, "8")
    [material] = [d for d in detail.view.details if d.key == "material"]
    [row] = material.rows
    assert (row.op, row.flows) == ("add", ["COST_TO_GOODS"])
    assert [cells(row)[i] for i in (0, 2, 3)] == [(None, "25"), (None, "80"), (None, "800")]
    [goods] = detail.view.affected
    [target] = goods.rows
    assert (target.op, target.checked, cells(target)[2]) == ("modify", True, ("75", "80"))

    result = h.pass_(ADMIN, approval.approval_id)
    assert result.outcome == "approvalProcessed" and result.skipped == []
    inserted = h.world.row("T_COST_PINGGU_DTL", dtl)
    assert inserted is not None and (inserted["DOCID"], inserted["GOODSID"], inserted["PRICE"]) == (int(bill), 25, 80)
    assert h.world.row("T_COST_PINGGU", bill)["MEMO"] == "新建"  # type: ignore[index]
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] == 80  # type: ignore[index]
    assert h.frozen() == set()
