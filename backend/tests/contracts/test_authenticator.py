"""`Authenticator` 的契约测试（C08 第 3 节；会话规则见 identity 的 ID-03、ID-05、ID-10）。

真实实现（identity）的测试继承 `AuthenticatorContract`，提供 `harness` fixture，实现 `AuthenticatorHarness`。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeAuthenticator, FakeClock
from cost_platform.contracts.ports import Authenticator
from cost_platform.contracts.types import ErrorCode, Identity, PlatformError

from .support import identity

USER = identity("112", "COST_ACCOUNTANT", session_id="")
CSRF = "csrf-112"


class AuthenticatorHarness(Protocol):
    authenticator: Authenticator
    idle: timedelta
    """会话的空闲时长（`PLATFORM_SESSION_IDLE_MINUTES`）。"""

    def open_session(self, user: Identity, csrf_token: str, *, role_selected: bool = True) -> str:
        """为 `user`（`session_id` 不用）登录并开一个会话，返回会话编号；`role_selected` 为 True 时已选定 `user.role_code`。"""
        ...

    def logout(self, session_id: str) -> None: ...

    def revoke_role(self, user_id: str, role_code: str) -> None: ...

    def advance(self, delta: timedelta) -> None:
        """让时间前进。"""
        ...


def _code(harness: AuthenticatorHarness, session_id: str | None, csrf: str | None = CSRF, *, is_write: bool = False,
          touch: bool = True) -> ErrorCode:
    with pytest.raises(PlatformError) as caught:
        harness.authenticator.authenticate(session_id, csrf, is_write, touch)
    return caught.value.code


class AuthenticatorContract:
    @pytest.fixture
    def harness(self) -> AuthenticatorHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_valid_session_returns_identity(self, harness: AuthenticatorHarness) -> None:
        sid = harness.open_session(USER, CSRF)
        assert harness.authenticator.authenticate(sid, None, False) == replace(USER, session_id=sid)

    def test_missing_or_unknown_session(self, harness: AuthenticatorHarness) -> None:
        harness.open_session(USER, CSRF)
        assert _code(harness, None) is ErrorCode.SESSION_REQUIRED
        assert _code(harness, "no-such-session") is ErrorCode.SESSION_REQUIRED

    def test_logged_out_session(self, harness: AuthenticatorHarness) -> None:
        sid = harness.open_session(USER, CSRF)
        harness.logout(sid)
        assert _code(harness, sid) is ErrorCode.SESSION_REQUIRED

    def test_role_not_selected(self, harness: AuthenticatorHarness) -> None:
        sid = harness.open_session(USER, CSRF, role_selected=False)
        assert _code(harness, sid) is ErrorCode.ROLE_SELECTION_REQUIRED

    def test_csrf_checked_only_for_writes(self, harness: AuthenticatorHarness) -> None:
        sid = harness.open_session(USER, CSRF)
        assert harness.authenticator.authenticate(sid, "wrong", False).user_id == USER.user_id
        assert harness.authenticator.authenticate(sid, CSRF, True).user_id == USER.user_id
        assert _code(harness, sid, "wrong", is_write=True) is ErrorCode.CSRF_FAILED
        assert _code(harness, sid, None, is_write=True) is ErrorCode.CSRF_FAILED

    def test_revoked_role(self, harness: AuthenticatorHarness) -> None:
        """会话选定的角色被撤销后为 SESSION_ROLE_REVOKED（C08 第 3 节、C03）；别的用户的会话不受影响。

        停用账号后旧会话怎样失效属于 identity 的 ID-05，由 identity 自己的测试验证。
        """
        other = replace(USER, user_id="113", username="user113")
        revoked = harness.open_session(other, CSRF)
        kept = harness.open_session(USER, CSRF)
        harness.revoke_role(other.user_id, other.role_code)
        assert _code(harness, revoked) is ErrorCode.SESSION_ROLE_REVOKED
        assert harness.authenticator.authenticate(kept, None, False).user_id == USER.user_id

    def test_idle_session_expires(self, harness: AuthenticatorHarness) -> None:
        sid = harness.open_session(USER, CSRF)
        harness.advance(harness.idle + timedelta(minutes=1))
        assert _code(harness, sid) is ErrorCode.SESSION_REQUIRED

    def test_touch_restarts_idle_time(self, harness: AuthenticatorHarness) -> None:
        sid = harness.open_session(USER, CSRF)
        harness.advance(harness.idle - timedelta(minutes=10))
        harness.authenticator.authenticate(sid, None, False, True)
        harness.advance(timedelta(minutes=20))
        assert harness.authenticator.authenticate(sid, None, False, False).session_id == sid

    def test_untouched_check_does_not_extend(self, harness: AuthenticatorHarness) -> None:
        """后台请求、握手和心跳以 touch=False 检查，不顺延会话（ID-10）。"""
        sid = harness.open_session(USER, CSRF)
        harness.advance(harness.idle - timedelta(minutes=10))
        harness.authenticator.authenticate(sid, None, False, False)
        harness.advance(timedelta(minutes=20))
        assert _code(harness, sid, touch=False) is ErrorCode.SESSION_REQUIRED


class FakeAuthenticatorHarness:
    def __init__(self) -> None:
        self.clock = FakeClock()
        self.idle = timedelta(minutes=120)
        self.authenticator = FakeAuthenticator(self.clock, self.idle)
        self._count = 0

    def open_session(self, user: Identity, csrf_token: str, *, role_selected: bool = True) -> str:
        self._count += 1
        return self.authenticator.open_session(replace(user, session_id=f"s-{self._count}"), csrf_token, role_selected=role_selected)

    def logout(self, session_id: str) -> None:
        self.authenticator.close_session(session_id)

    def revoke_role(self, user_id: str, role_code: str) -> None:
        self.authenticator.revoke_role(user_id, role_code)

    def advance(self, delta: timedelta) -> None:
        self.clock.advance(delta)


class TestFakeAuthenticator(AuthenticatorContract):
    @pytest.fixture
    def harness(self) -> FakeAuthenticatorHarness:
        return FakeAuthenticatorHarness()
