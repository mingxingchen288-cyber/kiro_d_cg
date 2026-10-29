"""审批流转（T-AP-1）：AP-04、AP-05、AP-07、AP-09、AP-12、AP-16 中不访问数据库的判断，以及结果指纹（AP-08）。

输入当前进度和一次处理（通过、驳回、撤回），输出处理是否允许、新的进度和去向：
- `stay`：留在本级（会签还有人没处理，或同级还有节点没通过）；
- `next`：本级全部节点通过，进入下一级；
- `end`：全部审批流到达终点，审批通过；
- `closed`：驳回或撤回，审批结束。

下一级会进入哪些节点要执行入口条件（C06 7.2 的 SQL），由调用方经 `next_nodes(审批流, 级别)` 给出：返回空表示这个审批流
以本级为终点（AP-04）。几个审批流合成一个审批时，同一级的节点合在一起审批，各自决定终点（AP-09）。

对照旧系统：`ConfiguredApprovalRuntime.route`（每次只算下一级，整级没有节点命中就结束）、`approveComposite`
（本级本人的全部待办一次处理，不替同一个人处理新打开的上一级）、`progressPermissions`（撤回：发起人，且没人处理过）。
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

MemberStatus = Literal["pending", "passed", "rejected"]
ApprovalStatus = Literal["pending", "approved", "rejected", "withdrawn"]
Destination = Literal["stay", "next", "end", "closed"]


@dataclass
class Member:
    """节点的一个审批人：直接列出的账号（`user`），或一个角色（`role`，该角色任一账号处理即算处理）。"""

    kind: Literal["user", "role"]
    id: str
    name: str
    status: MemberStatus = "pending"
    processed_by: str | None = None
    processed_by_name: str | None = None
    processed_at: datetime | None = None
    comment: str | None = None


@dataclass
class Node:
    """某个审批流某一级里进入的一个节点。`index` 为节点在这一级配置中的位置。"""

    flow: str
    level: int
    index: int
    name: str
    mode: Literal["or", "and"]
    members: list[Member]
    status: MemberStatus = "pending"


@dataclass
class Progress:
    """一个审批的进度：当前级别、已进入的全部节点、已到达终点的审批流（编码 -> 终点级别）。"""

    status: ApprovalStatus
    level: int
    flows: list[str]
    nodes: list[Node]
    ended: dict[str, int] = field(default_factory=dict)

    def active_flows(self) -> list[str]:
        return [f for f in self.flows if f not in self.ended]

    def current_nodes(self) -> list[Node]:
        return [n for n in self.nodes if n.level == self.level]

    def anyone_passed(self) -> bool:
        return any(m.status == "passed" for n in self.nodes for m in n.members)


@dataclass(frozen=True)
class Action:
    kind: Literal["pass", "reject", "withdraw"]
    user_id: str
    user_name: str
    at: datetime
    comment: str | None = None


@dataclass(frozen=True)
class Decision:
    allowed: bool
    destination: Destination
    progress: Progress
    processed: tuple[Node, ...] = ()
    """这次处理计入的节点（AP-16）。"""
    reason: str | None = None


Membership = Callable[[Member, str], bool]
"""某个账号是不是这个审批人：直接列出的账号比较编号，角色看账号是否属于这个角色。"""

NextNodes = Callable[[str, int], list[Node]]


def start(flows: Sequence[str], entered: dict[str, list[Node]]) -> Progress:
    """提交时的进度：`entered` 为各审批流第 1 级进入的节点；没有节点进入的审批流不在这个审批中（AP-01）。"""
    codes = [f for f in flows if entered.get(f)]
    return Progress(status="pending", level=1, flows=codes, nodes=[n for f in codes for n in entered[f]])


def pending_nodes(progress: Progress, user_id: str, is_member: Membership) -> list[Node]:
    """本级中这个账号尚未处理的节点（直接列为审批人，或是节点所配角色的账号，AP-16）。"""
    if progress.status != "pending":
        return []
    return [n for n in progress.current_nodes()
            if n.status == "pending" and any(m.status == "pending" and is_member(m, user_id) for m in n.members)]


def can_withdraw(progress: Progress, applicant_id: str, user_id: str) -> bool:
    """AP-12：只有发起人能撤回；只要有人做过通过，就不能撤回。"""
    return progress.status == "pending" and user_id == applicant_id and not progress.anyone_passed()


def _mark(node: Node, action: Action, status: MemberStatus, is_member: Membership) -> None:
    for member in node.members:
        if member.status == "pending" and is_member(member, action.user_id):
            member.status = status
            member.processed_by = action.user_id
            member.processed_by_name = action.user_name
            member.processed_at = action.at
            member.comment = action.comment


def _node_passed(node: Node) -> bool:
    if node.mode == "or":
        return any(m.status == "passed" for m in node.members)
    return all(m.status == "passed" for m in node.members)


def advance(progress: Progress, next_nodes: NextNodes) -> Destination:
    """本级全部节点通过之后：各审批流分别判断下一级（AP-04）；都没有下一级时审批通过。直接修改 `progress`。"""
    entering: list[Node] = []
    for flow in progress.active_flows():
        found = next_nodes(flow, progress.level + 1)
        if found:
            entering += found
        else:
            progress.ended[flow] = progress.level
    if not entering:
        progress.status = "approved"
        return "end"
    progress.level += 1
    progress.nodes += entering
    return "next"


def decide(progress: Progress, action: Action, *, applicant_id: str, is_member: Membership, next_nodes: NextNodes) -> Decision:
    """处理一次通过、驳回或撤回；不修改传入的进度。"""
    result = copy.deepcopy(progress)
    if action.kind == "withdraw":
        if not can_withdraw(progress, applicant_id, action.user_id):
            return Decision(False, "stay", progress, reason="只有发起人能撤回，并且还没有人通过")
        result.status = "withdrawn"
        return Decision(True, "closed", result)

    mine = pending_nodes(result, action.user_id, is_member)
    if not mine:
        return Decision(False, "stay", progress, reason="当前用户不是本级尚未处理的审批人")
    if action.kind == "reject":
        for node in mine:
            _mark(node, action, "rejected", is_member)
            node.status = "rejected"
        result.status = "rejected"
        return Decision(True, "closed", result, tuple(mine))

    for node in mine:
        _mark(node, action, "passed", is_member)
        if _node_passed(node):
            node.status = "passed"
    if any(n.status != "passed" for n in result.current_nodes()):
        return Decision(True, "stay", result, tuple(mine))
    return Decision(True, advance(result, next_nodes), result, tuple(mine))


def fingerprint(payload: Any) -> str:
    """结果指纹：内容按键名排序、去掉空白后的 JSON 取 SHA-256（AP-08）。"""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
