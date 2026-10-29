"""identity 端口的替代实现（C08 第 3 节）。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from ..ports import Clock
from ..types import AccountBatch, AccountRef, Department, ErrorCode, Identity, ImportReport, PlatformError
from ._script import Scripted


@dataclass
class _Session:
    identity: Identity
    csrf_token: str
    role_selected: bool
    last_active: datetime
    role_revoked: bool = False


class FakeAuthenticator(Scripted):
    """`Authenticator`：会话由 `open_session` 预设，按 `clock` 的时间判断过期（identity 的 ID-10）。

    - 没有会话、会话不存在、已注销或已过期：SESSION_REQUIRED；账号停用后（`disable_account`）同样如此（ID-05）。
    - 会话选定的角色被撤销（`revoke_role`）：SESSION_ROLE_REVOKED。
    - 还没有选定角色：ROLE_SELECTION_REQUIRED。
    - 写请求的 CSRF 令牌不一致：CSRF_FAILED（ID-03）。
    - 通过时，`touch` 为 True 才从这次请求起重新计时。
    """

    scriptable = ('authenticate',)

    def __init__(self, clock: Clock, idle: timedelta = timedelta(minutes=120)) -> None:
        super().__init__()
        self._clock = clock
        self.idle = idle
        self._sessions: dict[str, _Session] = {}

    def open_session(self, identity: Identity, csrf_token: str, *, role_selected: bool = True) -> str:
        """为 `identity` 开一个会话，会话编号取 `identity.session_id`；`role_selected` 为 False 时还没有选定角色。"""
        self._sessions[identity.session_id] = _Session(identity, csrf_token, role_selected, self._clock.now())
        return identity.session_id

    def close_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def disable_account(self, user_id: str) -> None:
        for sid in [s for s, v in self._sessions.items() if v.identity.user_id == user_id]:
            del self._sessions[sid]

    def revoke_role(self, user_id: str, role_code: str) -> None:
        for session in self._sessions.values():
            if session.identity.user_id == user_id and session.identity.role_code == role_code:
                session.role_revoked = True

    def authenticate(self, session_id: str | None, csrf_token: str | None, is_write: bool, touch: bool = True) -> Identity:
        self._record("authenticate", session_id, csrf_token, is_write, touch)
        now = self._clock.now()
        session = self._sessions.get(session_id) if session_id else None
        if session is not None and now - session.last_active >= self.idle:
            del self._sessions[session.identity.session_id]
            session = None
        if session is None:
            raise PlatformError(ErrorCode.SESSION_REQUIRED, "请先登录")
        if session.role_revoked:
            raise PlatformError(ErrorCode.SESSION_ROLE_REVOKED, "当前角色已被撤销")
        if not session.role_selected:
            raise PlatformError(ErrorCode.ROLE_SELECTION_REQUIRED, "请先选择角色")
        if is_write and csrf_token != session.csrf_token:
            raise PlatformError(ErrorCode.CSRF_FAILED, "CSRF 令牌无效")
        if touch:
            session.last_active = now
        return replace(session.identity)


class FakeDirectory(Scripted):
    """`DirectoryReader` 和 `AccountImporter`：账号和角色分配存在内存中，由 `add_account` 预设或经导入写入。

    导入时已存在的账号（账号编号或账号名相同）不覆盖，它的角色分配也不导入，列入 `skipped`。
    `ImportReport.imported` 为导入的账号数。
    """

    scriptable = ('enabled_accounts_with_role', 'account', 'department', 'import_batch')

    def __init__(self) -> None:
        super().__init__()
        self._accounts: dict[str, AccountRef] = {}
        self._roles: dict[str, set[str]] = {}
        self.password_hashes: dict[str, str] = {}
        self.departments: dict[str, tuple[str, str | None]] = {}

    def add_account(self, account: AccountRef, roles: Iterable[str] = ()) -> None:
        self._accounts[account.user_id] = account
        self._roles[account.user_id] = set(roles)

    def enabled_accounts_with_role(self, role_code: str) -> list[AccountRef]:
        self._record("enabled_accounts_with_role", role_code)
        return sorted((a for uid, a in self._accounts.items() if a.enabled and role_code in self._roles.get(uid, set())),
                      key=lambda a: a.user_id)

    def account(self, user_id: str) -> AccountRef | None:
        self._record("account", user_id)
        return self._accounts.get(user_id)

    def department(self, department_id: str) -> Department | None:
        """`departments` 中的部门（可以直接放入，也由 `import_batch` 写入）。"""
        self._record("department", department_id)
        found = self.departments.get(department_id)
        return None if found is None else Department(department_id=department_id, name=found[0], parent_id=found[1])

    def import_batch(self, batch: AccountBatch) -> ImportReport:
        self._record("import_batch", batch)
        usernames = {a.username for a in self._accounts.values()}
        imported: set[str] = set()
        skipped: list[tuple[str, str]] = []
        for item in batch.accounts:
            if item.user_id in self._accounts or item.username in usernames:
                skipped.append((f"account:{item.user_id}", "账号已存在，没有覆盖"))
                continue
            self._accounts[item.user_id] = AccountRef(item.user_id, item.username, item.display_name, item.department_id, item.enabled)
            self._roles[item.user_id] = set()
            self.password_hashes[item.user_id] = item.password_hash
            usernames.add(item.username)
            imported.add(item.user_id)
        for assignment in batch.assignments:
            if assignment.user_id in imported:
                self._roles[assignment.user_id].add(assignment.role_code)
        for department in batch.departments:
            self.departments.setdefault(department.department_id, (department.name, department.parent_id))
        return ImportReport(imported=len(imported), skipped=skipped)
