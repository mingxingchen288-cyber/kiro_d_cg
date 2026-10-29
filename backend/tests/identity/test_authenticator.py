"""`Authenticator` 的契约测试（C08 第 14 节），被测实现为 identity 的 `IdentityService`（模拟验证）。

会话经真实的登录流程建立：harness 为每个用户建账号、登录，需要时再选角色；撤销角色经账号管理（`AccountAdmin`）完成。
"""

from __future__ import annotations

from collections import deque
from datetime import timedelta

import pytest

from cost_platform.contracts.types import AccountRef, AccountUpdate, Identity
from cost_platform.identity.service import IdentityService, describe_role_from

from ..contracts.test_authenticator import AuthenticatorContract
from .support import Env, role_snapshot
from .test_accounts import insert_account

PASSWORD = "Abc123.."
SECOND_ROLE = "CT_SECOND"


class IdentityAuthenticatorHarness:
    def __init__(self) -> None:
        self.env = Env()
        self.idle = timedelta(minutes=self.env.idle_minutes)
        self._tokens: deque[str] = deque()
        self.authenticator = IdentityService(self.env.accounts, self.env.sessions, self.env.clock, self.env.idle_minutes,
                                             describe_role_from(self.env.config), publisher=self.env.events,
                                             ids=self.env.ids, passwords=self.env.passwords, new_token=self._tokens.popleft)
        self._csrf: dict[str, str] = {}
        self._count = 0

    def open_session(self, user: Identity, csrf_token: str, *, role_selected: bool = True) -> str:
        """按 `user` 的编号、账号名、姓名、部门建账号并登录。给账号两个角色，登录时不会自动选定；需要时再选 `user.role_code`。"""
        for code in (user.role_code, SECOND_ROLE):
            self.env.config.put(role_snapshot(code, code, False))
        if self.env.accounts.get(user.user_id) is None:
            insert_account(self.env.uow.engine, AccountRef(user.user_id, user.username, user.display_name,
                                                            user.department_id, True), [user.role_code, SECOND_ROLE])
            self.env.accounts.set_password_hash(user.user_id, self.env.passwords.hash(PASSWORD))
        self._count += 1
        self._tokens.extend([f"t{self._count}", csrf_token])
        session_id, result = self.authenticator.login(user.username, PASSWORD)
        assert result.selected_role is None
        if role_selected:
            self.authenticator.select_role(session_id, csrf_token, user.role_code)
        self._csrf[session_id] = csrf_token
        return session_id

    def logout(self, session_id: str) -> None:
        self.authenticator.logout(session_id, self._csrf[session_id])

    def revoke_role(self, user_id: str, role_code: str) -> None:
        account = self.env.accounts.get(user_id)
        assert account is not None
        self.env.admin.update_account(user_id, AccountUpdate(
            display_name=account.display_name, department_id=account.department_id,
            role_codes=[c for c in account.role_codes if c != role_code], enabled=account.enabled))

    def advance(self, delta: timedelta) -> None:
        self.env.clock.advance(delta)


class TestIdentityAuthenticator(AuthenticatorContract):
    @pytest.fixture
    def harness(self) -> IdentityAuthenticatorHarness:
        return IdentityAuthenticatorHarness()
