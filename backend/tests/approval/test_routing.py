"""审批流转（T-AP-1，工程约定第 5 节先写测试）：AP-04、AP-05、AP-07、AP-09、AP-12、AP-16 中不访问数据库的判断，以及结果指纹。

用例取自业务例子 E14、E15，以及 E37 中"管理员通过后进入第 2 级会签、采购和生产都通过才到终点；单价只改到 80 时管理员通过即结束"。
下一级会进入哪些节点要执行入口条件（SQL），由调用方算好后经 `next_nodes` 交给流转函数；这里用固定的回答代替。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from cost_platform.approval.routing import Action, Member, Node, Progress, decide, fingerprint, start

T0 = datetime(2026, 10, 29, 9, 0, 0)

# 角色成员：ADMIN 为系统管理员 1，008 为采购 2001，007 为生产 3001
ROLE_MEMBERS = {"ADMIN": {"1"}, "008": {"2001"}, "007": {"3001"}}


def is_member(member: Member, user_id: str) -> bool:
    if member.kind == "user":
        return member.id == user_id
    return user_id in ROLE_MEMBERS.get(member.id, set())


def user(uid: str, name: str) -> Member:
    return Member(kind="user", id=uid, name=name)


def role(code: str, name: str) -> Member:
    return Member(kind="role", id=code, name=name)


def node(flow: str, level: int, name: str, mode: str, *members: Member, index: int = 0) -> Node:
    return Node(flow=flow, level=level, index=index, name=name, mode=mode, members=list(members))  # type: ignore[arg-type]


def answers(table: dict[tuple[str, int], list[Node]]) -> Callable[[str, int], list[Node]]:
    """下一级会进入的节点：按（审批流、级别）给出，没有列出的为空。"""
    return lambda flow, level: [n for n in table.get((flow, level), [])]


def act(kind: str, uid: str, name: str = "", comment: str | None = None) -> Action:
    return Action(kind=kind, user_id=uid, user_name=name or uid, at=T0, comment=comment)  # type: ignore[arg-type]


# ---------------------------------------------------------------- E37：成本明细改价审批

def e37_start() -> Progress:
    return start(["COST_TO_GOODS"], {"COST_TO_GOODS": [node("COST_TO_GOODS", 1, "管理员审批", "or", role("ADMIN", "系统管理员"))]})


SIGN = {("COST_TO_GOODS", 2): [node("COST_TO_GOODS", 2, "采购、生产会签", "and", role("008", "采购"), role("007", "生产"))]}


def test_e37_admin_pass_enters_countersign_and_both_must_pass() -> None:
    progress = e37_start()
    first = decide(progress, act("pass", "1", "系统管理员"), applicant_id="112", is_member=is_member, next_nodes=answers(SIGN))
    assert first.allowed and first.destination == "next"
    assert first.progress.level == 2 and first.progress.status == "pending"
    assert [n.name for n in first.progress.nodes if n.level == 2] == ["采购、生产会签"]

    buyer = decide(first.progress, act("pass", "2001", "采购"), applicant_id="112", is_member=is_member, next_nodes=answers(SIGN))
    assert buyer.allowed and buyer.destination == "stay"
    assert buyer.progress.status == "pending" and buyer.progress.level == 2

    maker = decide(buyer.progress, act("pass", "3001", "生产"), applicant_id="112", is_member=is_member, next_nodes=answers(SIGN))
    assert maker.allowed and maker.destination == "end"
    assert maker.progress.status == "approved"
    assert maker.progress.ended == {"COST_TO_GOODS": 2}


def test_e37_price_80_admin_pass_ends() -> None:
    """单价只改到 80：第 2 级入口条件不成立（80 不大于 82.5），系统管理员通过即结束。"""
    done = decide(e37_start(), act("pass", "1"), applicant_id="112", is_member=is_member, next_nodes=answers({}))
    assert done.allowed and done.destination == "end"
    assert done.progress.status == "approved" and done.progress.ended == {"COST_TO_GOODS": 1}


def test_input_progress_is_not_changed() -> None:
    progress = e37_start()
    decide(progress, act("pass", "1"), applicant_id="112", is_member=is_member, next_nodes=answers(SIGN))
    assert progress.level == 1 and progress.nodes[0].status == "pending"


def test_countersign_member_cannot_pass_twice() -> None:
    first = decide(e37_start(), act("pass", "1"), applicant_id="112", is_member=is_member, next_nodes=answers(SIGN))
    buyer = decide(first.progress, act("pass", "2001"), applicant_id="112", is_member=is_member, next_nodes=answers(SIGN))
    again = decide(buyer.progress, act("pass", "2001"), applicant_id="112", is_member=is_member, next_nodes=answers(SIGN))
    assert not again.allowed


def test_not_an_approver_cannot_pass_or_reject() -> None:
    """AP-05：不是本级尚未处理的审批人提交处理，不允许（由调用方返回 403）。"""
    progress = e37_start()
    for kind in ("pass", "reject"):
        decision = decide(progress, act(kind, "2001", comment="价格偏高"), applicant_id="112", is_member=is_member,
                          next_nodes=answers(SIGN))
        assert not decision.allowed and decision.destination == "stay"


def test_role_member_processed_by_records_account() -> None:
    """按角色配置的成员，该角色任一账号处理即算处理，记下实际处理的账号。"""
    done = decide(e37_start(), act("pass", "1", "系统管理员", "价格已核对"), applicant_id="112", is_member=is_member,
                  next_nodes=answers({}))
    member = done.progress.nodes[0].members[0]
    assert (member.status, member.processed_by, member.processed_by_name, member.processed_at, member.comment) == (
        "passed", "1", "系统管理员", T0, "价格已核对")


# ---------------------------------------------------------------- E14：撤回

TWO_LEVELS = {("F", 2): [node("F", 2, "二级", "or", user("20", "王五"))]}


def two_level_start() -> Progress:
    return start(["F"], {"F": [node("F", 1, "一级会签", "and", user("10", "李四"), user("11", "张三"))]})


def test_e14_withdraw_after_someone_passed_is_denied() -> None:
    progress = decide(two_level_start(), act("pass", "10"), applicant_id="112", is_member=is_member,
                      next_nodes=answers(TWO_LEVELS)).progress
    assert progress.level == 1  # 会签还差张三
    withdraw = decide(progress, act("withdraw", "112"), applicant_id="112", is_member=is_member, next_nodes=answers(TWO_LEVELS))
    assert not withdraw.allowed and withdraw.progress.status == "pending"


def test_e14_withdraw_before_anyone_processed() -> None:
    withdraw = decide(two_level_start(), act("withdraw", "112", comment="录入有误"), applicant_id="112", is_member=is_member,
                      next_nodes=answers(TWO_LEVELS))
    assert withdraw.allowed and withdraw.destination == "closed"
    assert withdraw.progress.status == "withdrawn"


def test_only_applicant_can_withdraw() -> None:
    """AP-12：只有发起人能撤回。"""
    decision = decide(two_level_start(), act("withdraw", "10"), applicant_id="112", is_member=is_member,
                      next_nodes=answers(TWO_LEVELS))
    assert not decision.allowed


# ---------------------------------------------------------------- E15：两个审批流合成一个审批

F1_F2 = {
    ("F1", 2): [node("F1", 2, "王五审批", "or", user("20", "王五"))],
    ("F2", 2): [node("F2", 2, "赵六审批", "or", user("30", "赵六"))],
    ("F2", 3): [node("F2", 3, "钱七审批", "or", user("40", "钱七"))],
}


def e15_start() -> Progress:
    return start(["F1", "F2"], {"F1": [node("F1", 1, "李四审批", "or", user("10", "李四"))],
                                "F2": [node("F2", 1, "李四审批", "or", user("10", "李四"))]})


def test_e15_one_pass_counts_for_both_entries_then_flows_end_separately() -> None:
    nxt = answers(F1_F2)
    li = decide(e15_start(), act("pass", "10", "李四"), applicant_id="112", is_member=is_member, next_nodes=nxt)
    assert li.allowed and li.destination == "next"
    assert [(n.flow, n.status) for n in li.progress.nodes if n.level == 1] == [("F1", "passed"), ("F2", "passed")]
    assert li.progress.level == 2

    wang = decide(li.progress, act("pass", "20"), applicant_id="112", is_member=is_member, next_nodes=nxt)
    assert wang.destination == "stay"
    zhao = decide(wang.progress, act("pass", "30"), applicant_id="112", is_member=is_member, next_nodes=nxt)
    assert zhao.destination == "next" and zhao.progress.level == 3
    assert zhao.progress.ended == {"F1": 2}  # F1 到达终点，F2 还有第 3 级
    assert [n.name for n in zhao.progress.nodes if n.level == 3] == ["钱七审批"]

    qian = decide(zhao.progress, act("pass", "40"), applicant_id="112", is_member=is_member, next_nodes=nxt)
    assert qian.destination == "end" and qian.progress.status == "approved"
    assert qian.progress.ended == {"F1": 2, "F2": 3}


def test_e15_same_person_on_two_levels_passes_twice() -> None:
    """李四也是 F2 第 2 级的审批人：第 1 级的通过不计入第 2 级。"""
    nxt = answers({("F1", 2): [node("F1", 2, "王五审批", "or", user("20", "王五"))],
                   ("F2", 2): [node("F2", 2, "李四复核", "or", user("10", "李四"))]})
    first = decide(e15_start(), act("pass", "10"), applicant_id="112", is_member=is_member, next_nodes=nxt)
    level2 = [n for n in first.progress.nodes if n.level == 2]
    assert [n.status for n in level2] == ["pending", "pending"]
    second = decide(first.progress, act("pass", "10"), applicant_id="112", is_member=is_member, next_nodes=nxt)
    assert second.allowed
    assert [(n.flow, n.status) for n in second.progress.nodes if n.level == 2] == [("F1", "pending"), ("F2", "passed")]


def test_e15_reject_at_any_level_closes_whole_approval() -> None:
    nxt = answers(F1_F2)
    li = decide(e15_start(), act("pass", "10"), applicant_id="112", is_member=is_member, next_nodes=nxt)
    rejected = decide(li.progress, act("reject", "30", comment="价格偏高"), applicant_id="112", is_member=is_member, next_nodes=nxt)
    assert rejected.allowed and rejected.destination == "closed"
    assert rejected.progress.status == "rejected"
    zhao = next(n for n in rejected.progress.nodes if n.name == "赵六审批")
    assert zhao.status == "rejected" and zhao.members[0].comment == "价格偏高"


def test_finished_approval_accepts_no_more_actions() -> None:
    done = decide(e37_start(), act("pass", "1"), applicant_id="112", is_member=is_member, next_nodes=answers({}))
    for kind in ("pass", "reject", "withdraw"):
        assert not decide(done.progress, act(kind, "1", comment="x"), applicant_id="1", is_member=is_member,
                          next_nodes=answers({})).allowed


# ---------------------------------------------------------------- 指纹（AP-08）

def test_fingerprint_is_stable_and_changes_with_content() -> None:
    view = {"master": {"rows": [{"cells": [{"before": "75", "after": "90"}]}]}, "affected": []}
    same = {"affected": [], "master": {"rows": [{"cells": [{"before": "75", "after": "90"}]}]}}
    changed = {"master": {"rows": [{"cells": [{"before": "75", "after": "80"}]}]}, "affected": []}
    assert fingerprint(view) == fingerprint(same)
    assert fingerprint(view) != fingerprint(changed)
    assert fingerprint(view).startswith("sha256:") and len(fingerprint(view)) == len("sha256:") + 64
