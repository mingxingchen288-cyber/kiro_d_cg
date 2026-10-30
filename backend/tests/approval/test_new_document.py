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
    assert (target.op, target.checked, cells(target)) == ("modify", True, [("25", "25"), ("聚维酮K30", "聚维酮K30"), ("75.00", "80.00")])


def test_new_cost_document_shown_as_added_and_inserted_when_approved() -> None:
    """杨娜新建一张成本单，只有聚维酮K30 一行：主表、明细都预留主键，详情中都是"新增"；批准后整张插入，结果没有"已跳过"。"""
    h = Harness(["COST_TO_GOODS"])
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
    assert (head.op, cells(head)[:3]) == ("add", [(None, bill), (None, "250mg乙酰唑胺片"), (None, "8.0000")])
    [material] = [d for d in detail.view.details if d.key == "material"]
    [row] = material.rows
    assert (row.op, row.flows) == ("add", ["COST_TO_GOODS"])
    assert cells(row) == [(None, "25"), (None, "聚维酮K30"), (None, "80.00"), (None, "800.00")]
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
    h = Harness(["COST_TO_GOODS"])
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, k30_row())])
    [approval] = run.state.approvals
    record = h.record(approval.approval_id)
    dtl = record.key_map[DETAIL_TMP]
    assert list(record.key_map) == [DETAIL_TMP]
    assert ("T_COST_PINGGU", "2550") in h.frozen() and h.world.row("T_COST_PINGGU_DTL", dtl) is None

    detail = h.detail(ADMIN, approval.approval_id)
    [head] = detail.view.master.rows
    assert (head.op, cells(head)[0], cells(head)[2]) == ("modify", ("2550", "2550"), ("18.4250", "26.4250"))
    [material] = [d for d in detail.view.details if d.key == "material"]
    [row] = material.rows
    assert (row.op, cells(row)) == ("add", [(None, "25"), (None, "聚维酮K30"), (None, "80.00"), (None, "800.00")])
    check_goods_block(detail)

    result = h.pass_(ADMIN, approval.approval_id)
    assert result.outcome == "approvalProcessed" and result.skipped == []
    inserted = h.world.row("T_COST_PINGGU_DTL", dtl)
    assert inserted is not None and (inserted["DOCID"], inserted["GOODSID"], inserted["PRICE"]) == (2550, 25, 80)
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] == 80  # type: ignore[index]
    assert h.frozen() == set()


COPY_TMP = "tmp-00000000-0000-4000-8000-0000000000b3"
COPY_DTL_TMP = "tmp-00000000-0000-4000-8000-0000000000b4"


def test_copied_document_approved_with_values_resolved_at_submission() -> None:
    """复制成本单 2550 成新单据（主表 `copyOf` 2550，明细复制 206323 聚维酮K30、单价改成 80，和物料清单的 75 不同，进入
    COST_TO_GOODS）。项目号不可写（保存操作的可写字段里没有），取源行的值：前端复制时 2550 的项目号是"P-1"，保存前被别人改成
    "P-2"，写入管道（这里由 Pipeline 替身按 WP-21 代替）在保存这一刻取到"P-2"；审批期间 2550 又改成"P-3"。
    待审修改存的是保存这一刻解出的值：项目号"P-2"，不含前端带来的只在视图中的物料名称和计算字段每批数量；详情中新增的
    这一行物料名称按 Lookup 查出；通过后新单据的项目号是"P-2"（不在通过时再读源行），明细按存下的值插入。
    （2026-10-31 起币种 FMNAME 配了币种 Lookup、可写，这个用例改用仍不可写的项目号 PROJECTNO。）"""
    h = Harness(["COST_TO_GOODS"])
    source = h.world.tables["T_COST_PINGGU"]["2550"]
    source["PROJECTNO"] = "P-1"
    master = {"op": "add", "clientRowId": COPY_TMP, "copyOf": "2550",
              "values": {"GOODSNAME": "250mg乙酰唑胺片", "USESTATUS": "商业化", "MEMO": "复制", "PROJECTNO": "P-1"}}
    detail = {"entity": "COST_MATERIAL", "op": "add", "clientRowId": COPY_DTL_TMP, "copyOf": "206323",
              "values": {"GOODSID": "25", "GOODSNAME": "聚维酮K30", "PRICE": "80", "BATCH_QTY": "10"}}
    source["PROJECTNO"] = "P-2"  # 复制之后、保存之前，别人改了 2550 的项目号
    run = h.save(YANGNA, "COST_PINGGU", [{"entity": "COST_PINGGU", "master": master, "details": [detail]}])
    [approval] = run.state.approvals
    record = h.record(approval.approval_id)
    assert record.patch.master.copy_of == "2550"
    assert record.patch.master.values == {"GOODSNAME": "250mg乙酰唑胺片", "USESTATUS": "商业化", "MEMO": "复制", "PROJECTNO": "P-2"}
    [stored] = record.patch.details
    assert (stored.copy_of, stored.values) == ("206323", {"GOODSID": "25", "PRICE": "80"})

    source["PROJECTNO"] = "P-3"  # 审批期间 2550 又被改了
    [material] = [d for d in h.detail(ADMIN, approval.approval_id).view.details if d.key == "material"]
    [row] = material.rows
    assert (row.op, cells(row)[:3]) == ("add", [(None, "25"), (None, "聚维酮K30"), (None, "80.00")])

    result = h.pass_(ADMIN, approval.approval_id)
    assert result.outcome == "approvalProcessed"
    bill, dtl = record.key_map[COPY_TMP], record.key_map[COPY_DTL_TMP]
    written = h.world.row("T_COST_PINGGU", bill)
    assert written is not None and (written["PROJECTNO"], written["GOODSNAME"], written["MEMO"]) == ("P-2", "250mg乙酰唑胺片", "复制")
    inserted = h.world.row("T_COST_PINGGU_DTL", dtl)
    assert inserted is not None and (inserted["DOCID"], inserted["GOODSID"], inserted["PRICE"]) == (int(bill), 25, 80)
