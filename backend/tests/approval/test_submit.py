"""触发审批（T-AP-2）：AP-01、AP-02、AP-14、AP-17、AP-21、AP-22，业务例子 E20、E22、E23、E24、E37（提交部分）、E38、E40、E41。"""

from __future__ import annotations

import pytest

from cost_platform.contracts import types as t

from .support import ADMIN, TECH, YANGNA, Harness, _dtl, cost, goods, modify
from .test_freeze import e37_save

ADD = "tmp-00000000-0000-4000-8000-0000000000a1"


def test_e37_only_k30_triggers_and_nothing_is_written() -> None:
    """成本单 2550 原辅料一次改三行：只有聚维酮K30 一行触发本审批；三行在数据库中都不变；结果为已提交审批。"""
    h = Harness(["COST_TO_GOODS"])
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206323, PRICE="90"),
                                              modify("COST_MATERIAL", 206326, GOODSID="13165", PRICE="40"),
                                              modify("COST_MATERIAL", 206325, MEMO="改备注"))])
    assert run.state.outcome == "approvalSubmitted"
    [approval] = run.state.approvals
    assert (approval.status, approval.level, approval.flows) == ("pending", 1, ["COST_TO_GOODS"])
    assert run.state.pending_documents == {t.DocumentRef("COST_PINGGU", "2550")}
    assert h.world.row("T_COST_PINGGU_DTL", 206323)["PRICE"] == 75  # type: ignore[index]
    assert h.world.row("T_COST_PINGGU_DTL", 206326)["GOODSID"] == 310  # type: ignore[index]
    assert h.world.row("T_COST_PINGGU_DTL", 206325)["MEMO"] is None  # type: ignore[index]
    record = h.record(approval.approval_id)
    triggers = {r.row_key: r.flows for r in record.triggers if r.entity == "COST_MATERIAL"}
    assert triggers == {"206323": ["COST_TO_GOODS"], "206326": [], "206325": []}
    assert [n.name for n in record.progress.nodes] == ["管理员审批"]
    assert (record.page_title, record.operation_label, record.source_label) == ("成本核算", "保存", "250mg乙酰唑胺片")


def test_e37_goods_block_only_k30_cannot_be_unchecked() -> None:
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h)
    with h.uow.begin() as uow:
        rows = h.store.affected(uow, approval.approval_id)
    assert [(r.block, r.target_table, r.key, r.checked, r.missing) for r in rows] == [("goods", "T_COST_GOODS", "25", True, False)]


def test_e37_notifies_level_one_approvers() -> None:
    """AP-17、E23：通知第 1 级审批人（角色 ADMIN 的启用账号），标题固定格式。"""
    h = Harness(["COST_TO_GOODS"])
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206323, PRICE="90"))])
    [notice] = run.state.notifications
    assert notice.event == "approvalSubmitted" and notice.recipients == (ADMIN.user_id,)
    assert notice.title == "您有来自于成本核算页面，业务单据为2550的审批"
    assert notice.body == "" and notice.link == f"/approval/{run.state.approvals[0].approval_id}"


def test_e38_list_price_unchanged_saves_normally() -> None:
    """只把玉米淀粉换成微晶纤维素（13165），带出单价 40，和物料清单单价 40 相同：不进审批，直接写入。"""
    h = Harness(["COST_TO_GOODS"])
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206326, GOODSID="13165", PRICE="40"))])
    assert run.state.outcome == "saved" and run.state.approvals == []
    assert h.world.row("T_COST_PINGGU_DTL", 206326)["GOODSID"] == 13165  # type: ignore[index]
    assert h.frozen() == set()


def test_memo_only_does_not_trigger() -> None:
    """只改备注：不触发，也不写物料清单。"""
    h = Harness(["COST_TO_GOODS"])
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206325, MEMO="只改备注"))])
    assert run.state.outcome == "saved"
    assert h.world.row("T_COST_PINGGU_DTL", 206325)["MEMO"] == "只改备注"  # type: ignore[index]
    assert h.world.row("T_COST_GOODS", 115)["ZX_PRICE"] is None  # type: ignore[index]


def test_e40_two_k30_rows_written_with_different_prices() -> None:
    """两行聚维酮K30 一行改成 80、另一行改成 82：都要写物料清单 25 的执行价，保存返回 422，什么都不写入；两行都改成 80 正常提交。"""
    h = Harness(["COST_TO_GOODS"])
    h.world.put("T_COST_PINGGU_DTL", _dtl(206399, 2550, 25, "75", "1"))
    with pytest.raises(t.PlatformError) as caught:
        h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206323, PRICE="80"),
                                            modify("COST_MATERIAL", 206399, PRICE="82"))])
    assert caught.value.code is t.ErrorCode.VALIDATION_FAILED
    assert [d.message for d in caught.value.details] == ["物料清单 聚维酮K30（GOODSID 25）的 ZX_PRICE 会被写成 80 和 82"]
    assert h.frozen() == set() and h.world.row("T_COST_PINGGU_DTL", 206323)["PRICE"] == 75  # type: ignore[index]
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206323, PRICE="80"),
                                              modify("COST_MATERIAL", 206399, PRICE="80"))])
    [approval] = run.state.approvals
    with h.uow.begin() as uow:
        [row] = h.store.affected(uow, approval.approval_id)
    triggers = {r.id: r.row_key for r in h.record(approval.approval_id).triggers}
    assert row.key == "25" and [triggers[i] for i in row.triggers] == ["206323", "206399"]


def test_e20_only_the_triggering_document_waits() -> None:
    """一次保存修改了成本单 2550 中聚维酮K30 的单价（命中）和成本单 2556 的备注（不命中）：只为 2550 生成审批，2556 的备注已写入。"""
    h = Harness(["COST_TO_GOODS"])
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206323, PRICE="90")),
                                         cost(2556, master={"MEMO": "已写入"})])
    assert run.state.outcome == "approvalSubmitted"
    assert [a.document.record_key for a in run.state.approvals] == ["2550"]
    assert h.world.row("T_COST_PINGGU", 2556)["MEMO"] == "已写入"  # type: ignore[index]
    assert h.world.row("T_COST_PINGGU_DTL", 206323)["PRICE"] == 75  # type: ignore[index]


def _modify_only_flow(h: Harness) -> None:
    """E22：审批流的审核操作只勾选修改（7.8 的样例本来勾选新增和修改）。"""
    name, flow = h.config.flows["COST_TO_GOODS"]
    h.config.flows["COST_TO_GOODS"] = (name, flow.model_copy(update={"operations": {"COST_MATERIAL": ["modify"]}}))
    from cost_platform.approval import ItemsApprovalCatalog
    entities = {k: v for k, v in h.config.entities.items() if k != "COST_GOODS_PRICE"}
    h.config.catalog = ItemsApprovalCatalog(h.config.flows, entities)


def test_e22_add_or_delete_only_does_not_trigger() -> None:
    h = Harness(["COST_TO_GOODS"])
    _modify_only_flow(h)
    add = {"entity": "COST_MATERIAL", "op": "add", "clientRowId": ADD, "values": {"GOODSID": "115", "PRICE": "70"}}
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, add)])
    assert run.state.outcome == "saved" and run.state.approvals == []
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, {"entity": "COST_MATERIAL", "op": "delete", "rowKey": "206325"})])
    assert run.state.outcome == "saved" and h.world.row("T_COST_PINGGU_DTL", 206325) is None


def test_e22_e24_whole_document_waits_with_reserved_keys() -> None:
    """同一次保存还修改了已有明细的单价：整张提交审批，新增、删除都不写入；新增明细在提交时取得主键；通过后一起生效。"""
    h = Harness(["COST_TO_GOODS"])
    _modify_only_flow(h)
    add = {"entity": "COST_MATERIAL", "op": "add", "clientRowId": ADD, "values": {"GOODSID": "116", "PRICE": "12"}}
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206323, PRICE="80"), add,
                                              {"entity": "COST_MATERIAL", "op": "delete", "rowKey": "206325"})])
    [approval] = run.state.approvals
    record = h.record(approval.approval_id)
    reserved = record.key_map[ADD]
    assert reserved == "300001"
    assert h.world.row("T_COST_PINGGU_DTL", reserved) is None and h.world.row("T_COST_PINGGU_DTL", 206325) is not None
    h.pass_(ADMIN, approval.approval_id)
    assert h.world.row("T_COST_PINGGU_DTL", reserved)["GOODSID"] == 116  # type: ignore[index]
    assert h.world.row("T_COST_PINGGU_DTL", reserved)["DOCID"] == 2550  # type: ignore[index]
    assert h.world.row("T_COST_PINGGU_DTL", 206325) is None
    assert h.world.row("T_COST_PINGGU_DTL", 206323)["PRICE"] == 80  # type: ignore[index]


# ---------------------------------------------------------------- E41：技术中心客指物料变更审批（C06 7.9）

def _tech_world(h: Harness) -> None:
    """假设成本单 2550 的状态为"评估中"，硬脂酸镁那一行勾了客户指定（说明用的假设，d_cg 中 2550 为"商业化"）。"""
    h.world.tables["T_COST_PINGGU"]["2550"]["USESTATUS"] = "评估中"
    h.world.tables["T_COST_PINGGU_DTL"]["206325"]["CUSTOMER_SPECIFIED"] = 1


def test_e41_tech_center_changing_customer_material_enters_approval() -> None:
    h = Harness(["TECH_CUSTOMER_MATERIAL"])
    _tech_world(h)
    run = h.save(TECH, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206325, GOODSID="117", PRICE="13"))])
    [approval] = run.state.approvals
    assert approval.flows == ["TECH_CUSTOMER_MATERIAL"]
    assert h.frozen() == {("T_COST_PINGGU", "2550")}  # 只冻结这张成本单，没有受影响单据
    h.pass_(ADMIN, approval.approval_id)
    assert h.world.row("T_COST_PINGGU_DTL", 206325)["GOODSID"] == 117  # type: ignore[index]


def test_e41_deleting_customer_material_enters_approval() -> None:
    h = Harness(["TECH_CUSTOMER_MATERIAL"])
    _tech_world(h)
    run = h.save(TECH, "COST_PINGGU", [cost(2550, {"entity": "COST_MATERIAL", "op": "delete", "rowKey": "206325"})])
    assert run.state.outcome == "approvalSubmitted"
    assert h.world.row("T_COST_PINGGU_DTL", 206325) is not None


def test_e41_not_customer_specified_or_not_tech_center_saves_normally() -> None:
    h = Harness(["TECH_CUSTOMER_MATERIAL"])
    _tech_world(h)
    run = h.save(TECH, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206326, GOODSID="13165", PRICE="40"))])
    assert run.state.outcome == "saved"  # 玉米淀粉不是客户指定
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206325, GOODSID="117", PRICE="13"))])
    assert run.state.outcome == "saved"  # 杨娜不属于技术中心（部门 1069）
    assert h.world.row("T_COST_PINGGU_DTL", 206325)["GOODSID"] == 117  # type: ignore[index]


def test_two_flows_hit_one_document_make_one_approval() -> None:
    """一张单据命中两个审批流时合成一个审批（AP-09）：7.8 和 7.9 同时命中硬脂酸镁那一行。"""
    h = Harness(["COST_TO_GOODS", "TECH_CUSTOMER_MATERIAL"])
    _tech_world(h)
    run = h.save(TECH, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206325, GOODSID="117", PRICE="20"))])
    [approval] = run.state.approvals
    assert approval.flows == ["COST_TO_GOODS", "TECH_CUSTOMER_MATERIAL"]
    record = h.record(approval.approval_id)
    assert [(n.flow, n.name) for n in record.progress.nodes] == [("COST_TO_GOODS", "管理员审批"),
                                                                  ("TECH_CUSTOMER_MATERIAL", "管理员审批")]
    assert len(run.state.notifications) == 1 and run.state.notifications[0].recipients == ("1",)
    assert h.frozen() == {("T_COST_PINGGU", "2550"), ("T_COST_GOODS", "117")}


def test_e39_cost_documents_listed_and_checked() -> None:
    """7.10：含 25 的成本单明细都列给审批人，默认全选。"""
    h = Harness(["GOODS_TO_COST"])
    [approval] = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")]).state.approvals
    with h.uow.begin() as uow:
        rows = h.store.affected(uow, approval.approval_id)
    assert [(r.block, r.key, r.checked) for r in rows] == [("costMaterial", "206323", True), ("costMaterial", "103681", True)]
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] is None  # type: ignore[index]
    assert approval.document == t.RecordRef(entity="COST_GOODS_PRICE", record_key="25")
