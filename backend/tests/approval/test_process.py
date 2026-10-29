"""审批处理（T-AP-3、T-AP-4 的 AP-11）：通过、驳回、撤回经命令执行；业务例子 E13、E14、E15、E17、E37、E39。

命令执行用 support.Pipeline 代替 orchestration 和 write-pipeline；审批的阶段、存储、详情计算都是本模块的真实代码。
"""

from __future__ import annotations

import pytest

from cost_platform.contracts import types as t

from .support import ADMIN, BUYER, MAKER, YANGNA, D, Harness, Person, cost, goods, modify
from .test_freeze import e37_save


def _dtl(h: Harness, key: int) -> dict:
    return h.world.row("T_COST_PINGGU_DTL", key)  # type: ignore[return-value]


# ---------------------------------------------------------------- E37：两级审批，第 2 级会签

def test_e37_admin_then_countersign_then_everything_written() -> None:
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "90")
    first = h.pass_(ADMIN, approval.approval_id)
    assert first.outcome == "approvalProcessed"
    assert (first.approvals[0].status, first.approvals[0].level) == ("pending", 2)
    record = h.record(approval.approval_id)
    assert [(n.level, n.name, n.mode, [m.id for m in n.members]) for n in record.progress.nodes if n.level == 2] == [
        (2, "采购、生产会签", "and", ["008", "007"])]
    assert _dtl(h, 206323)["PRICE"] == 75 and h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] is None  # type: ignore[index]

    stay = h.pass_(BUYER, approval.approval_id)
    assert (stay.approvals[0].status, stay.approvals[0].level) == ("pending", 2)
    assert _dtl(h, 206323)["PRICE"] == 75  # 审批中途通过不写业务表（AP-20）

    done = h.pass_(MAKER, approval.approval_id)
    assert done.approvals[0].status == "approved"
    assert (_dtl(h, 206323)["PRICE"], _dtl(h, 206323)["COST_BATCH"]) == (90, 900)
    assert (_dtl(h, 206326)["GOODSID"], _dtl(h, 206326)["PRICE"]) == (13165, 40)
    assert _dtl(h, 206325)["MEMO"] == "改备注"
    assert h.world.row("T_COST_PINGGU", 2550)["TOTAL_COST"] == D(900) + D(40) * D("42.5") + D(63) * D("2.5")  # type: ignore[index]
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] == 90  # type: ignore[index]
    assert h.world.row("T_COST_GOODS", 13165)["ZX_PRICE"] is None and h.world.row("T_COST_GOODS", 115)["ZX_PRICE"] is None  # type: ignore[index]
    assert h.frozen() == set()
    assert h.world.table_writes == [("update", "T_COST_GOODS", "25", {"ZX_PRICE": D(90)})]  # 没注册的表经 TableWriter 写
    assert h.record(approval.approval_id).pending_status == "applied"
    assert [r.action for r in h.records(approval.approval_id)] == ["pass", "pass", "pass"]


def test_e37_registered_goods_written_through_intents() -> None:
    """物料清单在平台注册过时（实体 COST_GOODS_PRICE），执行价经写入意图交给 write-pipeline，不经 TableWriter。"""
    h = Harness(["COST_TO_GOODS"], register_goods=True)
    approval = e37_save(h, "80")
    h.pass_(ADMIN, approval.approval_id)
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] == 80  # type: ignore[index]
    assert h.world.table_writes == []
    intents = h.pipeline.runs[-1].state
    assert intents.outcome == "approvalProcessed"


def test_e37_price_80_admin_pass_ends() -> None:
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "80")
    done = h.pass_(ADMIN, approval.approval_id)
    assert done.approvals[0].status == "approved" and done.approvals[0].level == 1
    assert _dtl(h, 206323)["PRICE"] == 80 and h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] == 80  # type: ignore[index]


def test_passed_notifies_applicant() -> None:
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "80")
    h.pass_(ADMIN, approval.approval_id)
    [notice] = h.pipeline.runs[-1].state.notifications
    assert notice.event == "approvalPassed" and notice.recipients == (YANGNA.user_id,)
    assert notice.title == "您有来自于成本核算页面，业务单据为2550的审批已通过"


def test_not_an_approver_gets_403() -> None:
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h)
    with pytest.raises(t.PlatformError) as caught:
        h.pass_(BUYER, approval.approval_id, checked=[], fingerprint="sha256:x")
    assert caught.value.code is t.ErrorCode.PERMISSION_DENIED


def test_stale_fingerprint_needs_reconfirm() -> None:
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h)
    with pytest.raises(t.PlatformError) as caught:
        h.pass_(ADMIN, approval.approval_id, checked=[], fingerprint="sha256:" + "0" * 64)
    assert caught.value.code is t.ErrorCode.RECONFIRM_REQUIRED
    assert h.record(approval.approval_id).progress.level == 1


def test_e17_same_pass_request_runs_once() -> None:
    """审批人重复提交同一个通过请求：同步和后续动作只执行一次。"""
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "80")
    first = h.pass_(ADMIN, approval.approval_id, request_key="00000000-0000-4000-8000-00000000e017")
    again = h.pass_(ADMIN, approval.approval_id, request_key="00000000-0000-4000-8000-00000000e017")
    assert again == first
    assert [c.operation for c in h.pipeline.executed].count("approval.pass") == 1
    assert h.world.table_writes == [("update", "T_COST_GOODS", "25", {"ZX_PRICE": D(80)})]


# ---------------------------------------------------------------- E39：物料清单改价，取消 2556

def test_e39_unchecked_row_is_not_written() -> None:
    h = Harness(["GOODS_TO_COST"])
    [approval] = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")]).state.approvals
    h.pass_(ADMIN, approval.approval_id, checked=[("GOODS_TO_COST", "costMaterial", "206323")])
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] == 80  # type: ignore[index]
    assert (_dtl(h, 206323)["PRICE"], _dtl(h, 206323)["COST_BATCH"]) == (80, 800)
    assert (_dtl(h, 103681)["PRICE"], _dtl(h, 103681)["COST_BATCH"]) == (75, D("23.25"))
    assert h.frozen() == set()
    with h.uow.begin() as uow:
        rows = {r.key: r.checked for r in h.store.affected(uow, approval.approval_id)}
    assert rows == {"206323": True, "103681": False}


def test_all_unchecked_only_source_applies() -> None:
    """E12：全部取消，只有来源修改生效。"""
    h = Harness(["GOODS_TO_COST"])
    [approval] = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")]).state.approvals
    h.pass_(ADMIN, approval.approval_id, checked=[])
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] == 80  # type: ignore[index]
    assert _dtl(h, 206323)["PRICE"] == 75 and _dtl(h, 103681)["PRICE"] == 75


# ---------------------------------------------------------------- E13：驳回

def test_e13_reject_keeps_everything_and_releases_freeze() -> None:
    h = Harness(["GOODS_TO_COST"])
    [approval] = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")]).state.approvals
    with pytest.raises(t.PlatformError) as caught:
        h.reject(ADMIN, approval.approval_id, None)
    assert caught.value.code is t.ErrorCode.VALIDATION_FAILED
    result = h.reject(ADMIN, approval.approval_id, "价格偏高")
    assert result.approvals[0].status == "rejected"
    [item] = h.records(approval.approval_id)
    assert (item.action, item.user_id, item.comment, item.at) == ("reject", ADMIN.user_id, "价格偏高", h.ctx(ADMIN).now)
    [notice] = h.pipeline.runs[-1].state.notifications
    assert notice.recipients == (YANGNA.user_id,) and notice.title.endswith("的审批已驳回")
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] is None  # type: ignore[index]
    assert _dtl(h, 206323)["PRICE"] == 75
    assert h.frozen() == set()
    assert h.record(approval.approval_id).pending_status == "void"


# ---------------------------------------------------------------- E14：撤回

def test_e14_withdraw_denied_after_a_pass() -> None:
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "90")
    h.pass_(ADMIN, approval.approval_id)
    with pytest.raises(t.PlatformError) as caught:
        h.withdraw(YANGNA, approval.approval_id)
    assert caught.value.code is t.ErrorCode.PERMISSION_DENIED


def test_e14_withdraw_before_anyone_processed() -> None:
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "90")
    with pytest.raises(t.PlatformError) as caught:
        h.withdraw(ADMIN, approval.approval_id)
    assert caught.value.code is t.ErrorCode.PERMISSION_DENIED  # 只有发起人能撤回
    result = h.withdraw(YANGNA, approval.approval_id, "录入有误")
    assert result.approvals[0].status == "withdrawn"
    assert _dtl(h, 206323)["PRICE"] == 75 and h.frozen() == set()
    assert [(r.action, r.comment) for r in h.records(approval.approval_id)] == [("withdraw", "录入有误")]


# ---------------------------------------------------------------- E15：两个审批流合成一个审批

LI, WANG, ZHAO, QIAN = (Person("10", "李四", "COST", "10"), Person("20", "王五", "COST", "10"),
                        Person("30", "赵六", "COST", "10"), Person("40", "钱七", "COST", "10"))


def _flow(key: str, order: int, *levels: list[str]) -> t.ConfigDraft:
    return t.ConfigDraft(type="approvalFlow", key=key, name=key, content={
        "page": "COST_PINGGU", "order": order, "operations": {"COST_MATERIAL": ["modify"]},
        "levels": [{"level": i, "nodes": [{"name": f"{key} 第{i}级", "conditionType": "always", "mode": "or",
                                           "approvers": [{"type": "user", "userId": u} for u in users]}]}
                   for i, users in enumerate(levels, start=1)],
        "notify": [{"event": "submitted", "to": "levelApprovers"}, {"event": "levelEntered", "to": "levelApprovers"}],
    })


def test_e15_one_approval_for_two_flows() -> None:
    h = Harness([], extra_flows=[_flow("F1", 1, ["10"], ["20"]), _flow("F2", 2, ["10"], ["30"], ["40"])])
    for p in (LI, WANG, ZHAO, QIAN):
        h.directory.add_account(t.AccountRef(p.user_id, f"u{p.user_id}", p.name, p.department, True), [p.role])
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206325, MEMO="随审批"))])
    [approval] = run.state.approvals
    assert approval.flows == ["F1", "F2"]
    assert [n.recipients for n in run.state.notifications] == [("10",)]
    todo = h.service.list(h.ctx(LI), "todo", 0, 50)
    assert [r.approval_id for r in todo.rows] == [approval.approval_id] and todo.total == 1
    assert h.service.list(h.ctx(WANG), "todo", 0, 50).total == 0  # 王五在第 2 级，还没到
    assert h.service.list(h.ctx(YANGNA), "mine", 0, 50).rows[0].source.record_key == "2550"

    h.pass_(LI, approval.approval_id)
    record = h.record(approval.approval_id)
    assert record.progress.level == 2 and [n.status for n in record.progress.nodes if n.level == 1] == ["passed", "passed"]
    assert [n.recipients for n in h.pipeline.runs[-1].state.notifications] == [("20", "30")]
    h.pass_(WANG, approval.approval_id)
    h.pass_(ZHAO, approval.approval_id)
    record = h.record(approval.approval_id)
    assert record.progress.level == 3 and record.progress.ended == {"F1": 2}
    assert _dtl(h, 206325)["MEMO"] is None
    h.pass_(QIAN, approval.approval_id)
    assert h.record(approval.approval_id).progress.status == "approved"
    assert _dtl(h, 206325)["MEMO"] == "随审批"


def test_e15_reject_on_any_level_drops_changes() -> None:
    h = Harness([], extra_flows=[_flow("F1", 1, ["10"], ["20"]), _flow("F2", 2, ["10"], ["30"], ["40"])])
    for p in (LI, WANG, ZHAO, QIAN):
        h.directory.add_account(t.AccountRef(p.user_id, f"u{p.user_id}", p.name, p.department, True), [p.role])
    [approval] = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206325, MEMO="随审批"))]).state.approvals
    h.pass_(LI, approval.approval_id)
    h.reject(ZHAO, approval.approval_id, "不同意")
    assert h.record(approval.approval_id).progress.status == "rejected"
    assert _dtl(h, 206325)["MEMO"] is None and h.frozen() == set()
