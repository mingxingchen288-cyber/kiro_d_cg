"""T-ID-2 的登录、选角色、会话（模拟验证）：ID-01–ID-04、ID-10 和业务例子 E19。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from cost_platform.contracts.types import (
    AccountUpdate,
    ErrorCode,
    PlatformError,
    SessionRevokedEvent,
    SessionsAudience,
)

from .support import ACCOUNTANT, BUYER, Env
from .test_passwords import JBCRYPT_ABC


def _code(call: object, *args: object, **kwargs: object) -> ErrorCode:
    with pytest.raises(PlatformError) as caught:
        call(*args, **kwargs)  # type: ignore[operator]
    return caught.value.code


def test_login_failures_are_all_login_failed() -> None:
    """ID-01：账号不存在、密码错误、账号停用都返回 LOGIN_FAILED。"""
    env = Env()
    env.add_account("HY260404", "Abc123..", [ACCOUNTANT])
    env.add_account("HY190510", "Abc123..", [ACCOUNTANT], enabled=False)
    assert _code(env.identity.login, "NOBODY", "Abc123..") is ErrorCode.LOGIN_FAILED
    assert _code(env.identity.login, "HY260404", "wrong-pass") is ErrorCode.LOGIN_FAILED
    assert _code(env.identity.login, "HY190510", "Abc123..") is ErrorCode.LOGIN_FAILED


def test_single_role_is_selected_automatically() -> None:
    env = Env()
    uid = env.add_account("HY260404", "Abc123..", [ACCOUNTANT], display_name="程苏慧")
    session_id, result = env.identity.login("HY260404", "Abc123..")
    assert result.selected_role is not None and result.selected_role.code == ACCOUNTANT
    assert result.selected_role.name == "成本会计"
    assert result.user.user_id == uid and result.user.display_name == "程苏慧" and result.user.department_id == "581"
    who = env.identity.authenticate(session_id, None, False)
    assert (who.user_id, who.role_code, who.session_id) == (uid, ACCOUNTANT, session_id)


def test_choose_one_of_several_roles() -> None:
    """ID-02：多个角色时先选；选不属于该账号的角色返回 PERMISSION_DENIED。"""
    env = Env()
    env.add_account("HY090702", "Abc123..", [ACCOUNTANT, BUYER])
    session_id, result = env.identity.login("HY090702", "Abc123..")
    assert result.selected_role is None and [r.code for r in result.roles] == [BUYER, ACCOUNTANT]
    assert _code(env.identity.authenticate, session_id, None, False) is ErrorCode.ROLE_SELECTION_REQUIRED
    assert _code(env.identity.select_role, session_id, result.csrf_token, "ADMIN") is ErrorCode.PERMISSION_DENIED

    chosen = env.identity.select_role(session_id, result.csrf_token, BUYER)
    assert chosen.selected_role.code == BUYER and chosen.selected_role.name == "采购"
    assert env.identity.authenticate(session_id, None, False).role_code == BUYER


def test_write_without_csrf_token_is_rejected() -> None:
    """ID-03。"""
    env = Env()
    env.add_account("HY260404", "Abc123..", [ACCOUNTANT])
    session_id, result = env.identity.login("HY260404", "Abc123..")
    assert _code(env.identity.authenticate, session_id, None, True) is ErrorCode.CSRF_FAILED
    assert env.identity.authenticate(session_id, result.csrf_token, True).role_code == ACCOUNTANT


def test_e19_idle_120_minutes() -> None:
    """E19：用户 120 分钟没有查询和保存，下一个请求返回 401；期间页面自动发出的后台请求（touch=False）不顺延。"""
    env = Env()
    env.add_account("HY260404", "Abc123..", [ACCOUNTANT])
    session_id, _ = env.identity.login("HY260404", "Abc123..")

    env.clock.advance(timedelta(minutes=100))
    env.identity.authenticate(session_id, None, False, touch=False)  # 后台请求，不顺延
    env.clock.advance(timedelta(minutes=20))
    assert _code(env.identity.authenticate, session_id, None, False) is ErrorCode.SESSION_REQUIRED

    session_id, _ = env.identity.login("HY260404", "Abc123..")
    env.clock.advance(timedelta(minutes=100))
    env.identity.authenticate(session_id, None, False)  # 用户的查询，从这次起重新计时
    env.clock.advance(timedelta(minutes=119))
    assert env.identity.authenticate(session_id, None, False, touch=False).session_id == session_id
    env.clock.advance(timedelta(minutes=1))
    assert _code(env.identity.authenticate, session_id, None, False) is ErrorCode.SESSION_REQUIRED


def test_bcrypt_hash_upgraded_after_successful_login_only() -> None:
    """ID-04：旧账号的 BCrypt 哈希登录失败时不改；登录成功后改写为 Argon2，之后用 Argon2 登录。"""
    env = Env()
    uid = env.add_account("CS005", "unused..", [ACCOUNTANT])
    env.accounts.set_password_hash(uid, JBCRYPT_ABC[1].decode())

    assert _code(env.identity.login, "CS005", "abd") is ErrorCode.LOGIN_FAILED
    assert env.accounts.get(uid).password_hash == JBCRYPT_ABC[1].decode()  # type: ignore[union-attr]

    env.identity.login("CS005", "abc")
    upgraded = env.accounts.get(uid).password_hash  # type: ignore[union-attr]
    assert upgraded is not None and upgraded.startswith("$argon2id$")
    assert env.passwords.verify(upgraded, "abc").ok
    env.identity.login("CS005", "abc")
    assert env.accounts.get(uid).password_hash == upgraded  # type: ignore[union-attr]


def test_logout_ends_session_and_notifies_it() -> None:
    env = Env()
    env.add_account("HY260404", "Abc123..", [ACCOUNTANT])
    session_id, result = env.identity.login("HY260404", "Abc123..")
    env.identity.logout(session_id, result.csrf_token)
    assert _code(env.identity.authenticate, session_id, None, False) is ErrorCode.SESSION_REQUIRED
    [event] = env.events.events
    assert isinstance(event, SessionRevokedEvent)
    assert event.audience == SessionsAudience(sessions=[session_id]) and event.payload.reason == "loggedOut"


def test_change_own_password() -> None:
    """旧系统顶栏"修改密码"：当前用户改自己的密码，之后用新密码登录。"""
    env = Env()
    env.add_account("HY260404", "Abc123..", [ACCOUNTANT])
    session_id, result = env.identity.login("HY260404", "Abc123..")
    env.identity.change_own_password(session_id, result.csrf_token, "Xyz789..")
    assert _code(env.identity.login, "HY260404", "Abc123..") is ErrorCode.LOGIN_FAILED
    env.identity.login("HY260404", "Xyz789..")


def test_department_change_reaches_open_session() -> None:
    """管理员改了账号的部门，已登录会话的 Identity 随之更新（行权限按部门时用到）。"""
    env = Env()
    uid = env.add_account("HY260404", "Abc123..", [ACCOUNTANT], display_name="程苏慧")
    session_id, _ = env.identity.login("HY260404", "Abc123..")
    env.admin.update_account(uid, AccountUpdate(display_name="程苏慧", department_id="175", role_codes=[ACCOUNTANT],
                                                enabled=True))
    assert env.identity.authenticate(session_id, None, False).department_id == "175"
    assert env.events.events == []
