"""审批详情和预览（T-AP-3，AP-08、AP-21，C06 7.6，C09 第 6 节）：业务例子 E37、E39，以及记录已不存在的行。"""

from __future__ import annotations

from cost_platform.contracts import types as t

from .support import ADMIN, BUYER, YANGNA, Harness, cost, goods, modify
from .test_freeze import e37_save


def cells(row: t.ViewRow) -> list[tuple[object, object]]:
    return [(c.before, c.after) for c in row.cells]


def test_e37_detail_trigger_column_and_goods_block() -> None:
    """原辅料三行的"触发审批"依次为"成本明细改价审批""随审批等待""随审批等待"；物料清单一块只有 25，单价 75→90，不能取消。"""
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "90")
    detail = h.detail(ADMIN, approval.approval_id)
    assert (detail.status, detail.current_level, detail.page_title, detail.operation_label) == ("pending", 1, "成本核算", "保存")
    assert (detail.source.record_key, detail.source.label, detail.applicant.display_name) == ("2550", "250mg乙酰唑胺片", "杨娜")
    [material] = [d for d in detail.view.details if d.key == "material"]
    assert material.columns == ["物料", "物料名称", "单价", "金额"]
    assert [(r.op, r.flows) for r in material.rows] == [("modify", ["COST_TO_GOODS"]), ("modify", []), ("modify", [])]
    assert cells(material.rows[0]) == [("25", "25"), ("聚维酮K30", "聚维酮K30"), ("75", "90"), ("750", "900")]
    assert cells(material.rows[1])[:3] == [("310", "13165"), ("玉米淀粉", "玉米淀粉"), ("22", "40")]
    [goods_block] = detail.view.affected
    assert (goods_block.key, goods_block.title, goods_block.selection, goods_block.editable) == ("goods", "物料清单", "all", False)
    [row] = goods_block.rows
    assert cells(row) == [("25", "25"), ("聚维酮K30", "聚维酮K30"), ("75", "90")]
    assert (row.op, row.ref, row.checked) == ("modify", t.RowRef(key="25"), True)
    assert detail.view.master.key == "cost" and detail.view.master.columns == ["单据号", "产品", "每盒成本", "千片加工费"]


def test_e37_steps_show_upcoming_countersign_and_actions() -> None:
    """进度列已进入的节点和按当前数据推算后面会进入的节点（90 > 82.5，第 2 级会签）。"""
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "90")
    detail = h.detail(ADMIN, approval.approval_id)
    assert [(s.level, s.node, s.status, [m.id for m in s.members]) for s in detail.steps] == [
        (1, "管理员审批", "pending", ["ADMIN"]), (2, "采购、生产会签", "upcoming", ["008", "007"])]
    assert detail.actions == t.ApprovalActions(can_pass=True, can_reject=True, can_withdraw=False)
    mine = h.detail(YANGNA, approval.approval_id)  # 任何已登录的用户都能查看（AP-15）
    assert mine.actions == t.ApprovalActions(can_pass=False, can_reject=False, can_withdraw=True)
    assert mine.fingerprint == detail.fingerprint


def test_e37_price_80_has_no_second_level() -> None:
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "80")
    assert [s.level for s in h.detail(ADMIN, approval.approval_id).steps] == [1]


def test_after_first_level_steps_record_who_passed() -> None:
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "90")
    h.pass_(ADMIN, approval.approval_id)
    detail = h.detail(BUYER, approval.approval_id)
    first = detail.steps[0]
    assert (first.status, first.members[0].status, first.members[0].processed_by) == (
        "passed", "passed", t.UserBrief(user_id="1", display_name="系统管理员"))
    assert [(s.level, s.status) for s in detail.steps] == [(1, "passed"), (2, "pending")]
    assert detail.actions.can_pass


# ---------------------------------------------------------------- E39：取消勾选后详情重算

def test_e39_preview_unchecked_row_restores_values() -> None:
    """取消 2556 那一行：这一行恢复为单价 75、金额 23.25，2556 的每盒成本恢复为改前的值；其他行仍显示 75→80。"""
    h = Harness(["GOODS_TO_COST"])
    [approval] = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")]).state.approvals
    detail = h.detail(ADMIN, approval.approval_id)
    assert detail.view.master.key == "goods"
    assert cells(detail.view.master.rows[0]) == [("25", "25"), ("聚维酮K30", "聚维酮K30"), ("75", "75"), ("75", "80")]
    [block] = [b for b in detail.view.affected if b.key == "costMaterial"]
    assert block.editable and block.selection == "checked"
    assert block.columns == ["单据号", "产品", "物料", "单价", "金额", "每盒成本", "千片加工费"]
    by_key = {r.ref.key: r for r in block.rows if r.ref}
    assert cells(by_key["206323"])[:6] == [("2550", "2550"), ("250mg乙酰唑胺片", "250mg乙酰唑胺片"), ("聚维酮K30", "聚维酮K30"),
                                          ("75", "80"), ("750", "800"), ("18.425", "18.925")]
    assert cells(by_key["103681"])[3:5] == [("75", "80"), ("23.25", "24.8")]

    preview = h.preview(ADMIN, approval.approval_id, [("GOODS_TO_COST", "costMaterial", "206323")])
    [block] = [b for b in preview.view.affected if b.key == "costMaterial"]
    by_key = {r.ref.key: r for r in block.rows if r.ref}
    assert (by_key["103681"].op, by_key["103681"].checked) == ("none", False)
    assert cells(by_key["103681"])[3:6] == [("75", "75"), ("23.25", "23.25"), ("0.2325", "0.2325")]
    assert cells(by_key["206323"])[3] == ("75", "80")
    assert preview.fingerprint != detail.fingerprint
    # 预览不保存勾选：再打开详情仍是全选
    again = h.detail(ADMIN, approval.approval_id)
    assert again.fingerprint == detail.fingerprint


def test_e39_next_level_cannot_check_back() -> None:
    """多级审批时，下一级只能在上一级保留的行里再取消，不能把上一级取消的行勾回来（AP-07）。样例 7.10 只有一级，这里在它后面
    加一级采购复核（说明用的假设配置）。"""
    h = Harness(["GOODS_TO_COST"])
    name, flow = h.config.flows["GOODS_TO_COST"]
    second = t.FlowLevel(level=2, nodes=[t.FlowNode(name="采购复核", condition_type="always", approvers=[t.RoleApprover(type="role", role="008")],
                                                    mode="or")])
    h.config.flows["GOODS_TO_COST"] = (name, flow.model_copy(update={"levels": [*flow.levels, second]}))
    from cost_platform.approval import ItemsApprovalCatalog
    h.config.catalog = ItemsApprovalCatalog(h.config.flows, h.config.entities)
    [approval] = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")]).state.approvals
    h.pass_(ADMIN, approval.approval_id, checked=[("GOODS_TO_COST", "costMaterial", "206323")])
    detail = h.detail(BUYER, approval.approval_id)
    [block] = [b for b in detail.view.affected if b.key == "costMaterial"]
    assert {r.ref.key: r.checked for r in block.rows if r.ref} == {"206323": True, "103681": False}
    h.pass_(BUYER, approval.approval_id, checked=[("GOODS_TO_COST", "costMaterial", "206323"),
                                                  ("GOODS_TO_COST", "costMaterial", "103681")])
    assert h.world.row("T_COST_PINGGU_DTL", 103681)["PRICE"] == 75  # type: ignore[index]
    assert h.world.row("T_COST_PINGGU_DTL", 206323)["PRICE"] == 80  # type: ignore[index]


# ---------------------------------------------------------------- AP-21：记录已不存在

def test_missing_record_listed_last_and_skipped() -> None:
    """展示视图查出的一行 keyColumn 为空：照常记为这一块的一行，详情中排在最后、不能勾选；最终批准时跳过并记入执行结果。"""
    h = Harness(["GOODS_TO_COST"])
    original = h.world.relation

    def with_lost_row(name: str) -> list[dict]:
        rows = original(name)
        if name == "V_COST_PINGGU_MATERIAL":
            rows.append({"DTLID": None, "DOCID": 2601, "GOODSID": 25, "GOODSNAME": "聚维酮K30", "PRICE": 75, "COST_BATCH": 150})
        return rows

    h.world.relation = with_lost_row  # type: ignore[method-assign]
    [approval] = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")]).state.approvals
    detail = h.detail(ADMIN, approval.approval_id)
    [block] = [b for b in detail.view.affected if b.key == "costMaterial"]
    last = block.rows[-1]
    assert (last.missing, last.op, last.ref, last.checked) == (True, "none", None, None)
    assert cells(last)[2:5] == [("聚维酮K30", "聚维酮K30"), ("75", "75"), ("150", "150")]
    h.pass_(ADMIN, approval.approval_id)
    result = h.record(approval.approval_id).result
    assert {"flow": "GOODS_TO_COST", "block": "costMaterial", "key": None, "status": "skipped", "reason": "记录已不存在"} in result


def test_e31_e33_two_flows_share_source_tables() -> None:
    """几个审批流合成的审批：来源单据只显示一份，列取各审批流 master、detail 块的并集；明细每行列出触发的审批流。"""
    from .test_submit import _tech_world
    h = Harness(["COST_TO_GOODS", "TECH_CUSTOMER_MATERIAL"])
    _tech_world(h)
    from .support import TECH
    [approval] = h.save(TECH, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206325, GOODSID="117", PRICE="20"),
                                                   modify("COST_MATERIAL", 206323, PRICE="90"))]).state.approvals
    detail = h.detail(ADMIN, approval.approval_id)
    [material] = [d for d in detail.view.details if d.key == "material"]
    assert material.columns == ["物料", "物料名称", "单价", "金额", "客户指定"]
    assert [r.flows for r in material.rows] == [["COST_TO_GOODS", "TECH_CUSTOMER_MATERIAL"], ["COST_TO_GOODS"]]
    assert [b.title for b in detail.view.affected] == ["物料清单（成本明细改价审批）"]
    assert [(s.level, s.flow, s.node) for s in detail.steps] == [(1, "COST_TO_GOODS", "管理员审批"),
                                                                 (1, "TECH_CUSTOMER_MATERIAL", "管理员审批"),
                                                                 (2, "COST_TO_GOODS", "采购、生产会签")]
