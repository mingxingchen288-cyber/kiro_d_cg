"""账号管理和部门（ID-05、ID-07；C09 第 2 节的 `/api/admin/accounts`、`/api/admin/departments`）。

只做账号数据的规则；"只有管理员角色能调用"由 `router.py` 按配置快照的角色判断（C09 第 1 节）。
"""

from __future__ import annotations

from collections.abc import Sequence

from cost_platform.contracts.ports import IdGenerator, RealtimePublisher
from cost_platform.contracts.types import (
    Account,
    AccountCreate,
    AccountList,
    AccountUpdate,
    Department,
    DepartmentList,
    ErrorCode,
    ErrorDetail,
    PlatformError,
    UsersAudience,
)

from .accounts import AccountRecord, DepartmentRecord, OracleAccounts
from .passwords import Passwords
from .rules import check_password_format
from .service import RoleDescriber, publish_revoked
from .sessions import SessionStore

_MISSING_ROLE = (ErrorCode.NOT_FOUND, ErrorCode.SESSION_ROLE_REVOKED)


def to_account(record: AccountRecord) -> Account:
    return Account(user_id=record.user_id, username=record.username, display_name=record.display_name,
                   department_id=record.department_id, enabled=record.enabled, role_codes=list(record.role_codes))


def to_department(record: DepartmentRecord) -> Department:
    return Department(department_id=record.department_id, name=record.name, parent_id=record.parent_id)


class AccountAdmin:
    """账号的列表、新建、修改（停用、分配角色、部门）、改密码；部门的列表、新建、修改、删除。

    - `sessions`：账号修改提交后写入新的账号状态，旧会话按它立即失效（ID-05）。
    - `describe_role`：分配角色时核对角色存在（模块说明第 4 节），与 `IdentityService` 用同一个。
    - `publisher`、`ids`：停用账号或撤销角色后发布 `session.revoked`（C10）；不给时不发布。
    """

    def __init__(self, accounts: OracleAccounts, sessions: SessionStore, describe_role: RoleDescriber, *,
                 publisher: RealtimePublisher | None = None, ids: IdGenerator | None = None,
                 passwords: Passwords | None = None) -> None:
        self._accounts = accounts
        self._sessions = sessions
        self._describe_role = describe_role
        self._publisher = publisher
        self._ids = ids
        self._passwords = passwords or Passwords()

    # ------------------------------------------------------------ 账号

    def list_accounts(self, keyword: str = "", start: int = 0, end: int = 50, role_code: str | None = None) -> AccountList:
        """`role_code` 只列分配了该角色的账号（旧系统角色管理的"角色人员"列表），C09 没有这个参数，见 contract-gaps.md。"""
        rows, total = self._accounts.list_accounts(keyword, start, end, role_code)
        return AccountList(rows=[to_account(r) for r in rows], total=total)

    def create_account(self, request: AccountCreate) -> Account:
        password = request.password.get_secret_value()
        check_password_format(password)
        self._check_roles(request.role_codes)
        created = self._accounts.create_account(request.username, request.display_name, request.department_id,
                                                self._passwords.hash(password), request.role_codes)
        return to_account(created)

    def update_account(self, user_id: str, request: AccountUpdate) -> Account:
        """ID-05：在一个事务内修改；提交后写入新的账号状态，停用账号或撤销角色时发布 `session.revoked`。"""
        current = self._accounts.get(user_id)
        if current is None:
            raise PlatformError(ErrorCode.NOT_FOUND, f"账号 {user_id} 不存在")
        self._check_roles([c for c in request.role_codes if c not in current.role_codes])
        changed = self._accounts.update_account(user_id, request.display_name, request.department_id,
                                                request.role_codes, request.enabled)
        if changed is None:
            raise PlatformError(ErrorCode.NOT_FOUND, f"账号 {user_id} 不存在")
        before, after = changed
        self._sessions.put_state(after.state())
        audience = UsersAudience(users=[after.user_id])
        if before.enabled and not after.enabled:
            publish_revoked(self._publisher, self._ids, audience, "accountDisabled")
        elif set(before.role_codes) - set(after.role_codes):
            publish_revoked(self._publisher, self._ids, audience, "roleRevoked")
        return to_account(after)

    def set_password(self, user_id: str, password: str) -> None:
        check_password_format(password)
        if not self._accounts.set_password_hash(user_id, self._passwords.hash(password)):
            raise PlatformError(ErrorCode.NOT_FOUND, f"账号 {user_id} 不存在")

    def _check_roles(self, role_codes: Sequence[str]) -> None:
        missing = []
        for code in dict.fromkeys(role_codes):
            try:
                self._describe_role(code)
            except PlatformError as exc:
                if exc.code not in _MISSING_ROLE:
                    raise
                missing.append(code)
        if missing:
            raise PlatformError(ErrorCode.VALIDATION_FAILED, f"角色不存在：{'、'.join(missing)}",
                                [ErrorDetail(message=f"角色 {code} 不存在", field="roleCodes") for code in missing])

    # ------------------------------------------------------------ 部门

    def departments(self) -> DepartmentList:
        return DepartmentList(items=[to_department(d) for d in self._accounts.departments()])

    def create_department(self, name: str, parent_id: str | None) -> Department:
        """旧系统部门管理页的新增；C09 没有这个接口，见 contract-gaps.md。"""
        return to_department(self._accounts.create_department(name, parent_id))

    def update_department(self, department_id: str, name: str, parent_id: str | None) -> Department:
        found = self._accounts.update_department(department_id, name, parent_id)
        if found is None:
            raise PlatformError(ErrorCode.NOT_FOUND, f"部门 {department_id} 不存在")
        return to_department(found)

    def delete_department(self, department_id: str) -> None:
        if not self._accounts.delete_department(department_id):
            raise PlatformError(ErrorCode.NOT_FOUND, f"部门 {department_id} 不存在")
