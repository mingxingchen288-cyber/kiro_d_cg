"""审批人（C06 7.3 的 `approvers`；AP-14、AP-16、AP-19）。

- `user`：这个账号，停用的不算；
- `role`：这个角色，该角色任一启用的账号处理即算处理（节点进度中记为一个成员）；
- `sql`：进入该级的那次命令中执行，只读，参数用绑定变量；返回的用户编号中只取启用的账号。`binds` 的每一项为
  绑定变量名 -> C06 7.2 的参数名（例如 `{"dept": "master_new_DEPTID"}`）；语句中直接写的 7.2 参数照常绑定。

节点进入但组内没有启用的账号时，拒绝这次提交或通过，返回 422 VALIDATION_FAILED，提示级别和节点名称（AP-14）。
对照旧系统 `ConfiguredApprovalRuntime.route`：ROLE 要求角色有可用人员，USER、SQL 逐个查启用状态。
"""

from __future__ import annotations

from collections.abc import Iterable

from cost_platform.contracts.ports import DirectoryReader, UnitOfWork
from cost_platform.contracts.types import ErrorCode, ErrorDetail, FlowNode, PlatformError, RoleApprover, SqlApprover, UserApprover

from .routing import Member, Membership, Node
from .sql import RowScope, SqlRunner, binds_for, db_value, key_text


def resolve(node: FlowNode, *, flow: str, level: int, index: int, uow: UnitOfWork, sql: SqlRunner, directory: DirectoryReader,
            scope: RowScope | None, strict: bool = True) -> Node:
    """进入的节点和它的审批人；`strict` 为 False 时（只用于详情中推算后面的级别）没有可用的审批人也不报错。"""
    members: dict[tuple[str, str], Member] = {}
    for approver in node.approvers:
        if isinstance(approver, UserApprover):
            account = directory.account(approver.user_id)
            if account is not None and account.enabled:
                members[("user", account.user_id)] = Member("user", account.user_id, account.display_name)
        elif isinstance(approver, RoleApprover):
            if directory.enabled_accounts_with_role(approver.role):
                members[("role", approver.role)] = Member("role", approver.role, approver.role)
        elif isinstance(approver, SqlApprover):
            extra = {name: db_value(scope.value(ref)) if scope is not None else None for name, ref in approver.binds.items()}
            for row in sql.rows(uow, approver.sql, binds_for(approver.sql, scope, extra)):
                value = next(iter(row.values()), None)
                if value is None:
                    continue
                account = directory.account(key_text(value))
                if account is not None and account.enabled:
                    members[("user", account.user_id)] = Member("user", account.user_id, account.display_name)
    if strict and not members:
        raise PlatformError(ErrorCode.VALIDATION_FAILED, f"第 {level} 级节点“{node.name}”没有启用的审批人", [
            ErrorDetail(message=f"审批流 {flow} 第 {level} 级节点“{node.name}”没有启用的账号，不能提交或通过")])
    return Node(flow=flow, level=level, index=index, name=node.name, mode=node.mode, members=list(members.values()))


class Directory:
    """按角色取启用的账号，一次请求内缓存。"""

    def __init__(self, reader: DirectoryReader) -> None:
        self.reader = reader
        self._roles: dict[str, set[str]] = {}

    def role_users(self, role: str) -> set[str]:
        if role not in self._roles:
            self._roles[role] = {a.user_id for a in self.reader.enabled_accounts_with_role(role)}
        return self._roles[role]

    def membership(self) -> Membership:
        def is_member(member: Member, user_id: str) -> bool:
            if member.kind == "user":
                return member.id == user_id
            return user_id in self.role_users(member.id)
        return is_member

    def recipients(self, members: Iterable[Member]) -> list[str]:
        """成员对应的用户编号：角色为它的全部启用账号。"""
        found: dict[str, None] = {}
        for member in members:
            if member.kind == "user":
                found[member.id] = None
            else:
                for user_id in sorted(self.role_users(member.id)):
                    found[user_id] = None
        return list(found)
