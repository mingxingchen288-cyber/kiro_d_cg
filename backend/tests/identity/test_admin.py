"""T-ID-3 的账号管理与会话撤销（模拟验证）：ID-05、ID-07。"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from cost_platform.contracts.types import (
    AccountCreate,
    AccountUpdate,
    ErrorCode,
    PlatformError,
    SessionRevokedEvent,
    UsersAudience,
)

from .support import ACCOUNTANT, BUYER, Env


def _code(call: object, *args: object) -> ErrorCode:
    with pytest.raises(PlatformError) as caught:
        call(*args)  # type: ignore[operator]
    return caught.value.code


def _update(env: Env, user_id: str, **changes: object) -> None:
    account = env.accounts.get(user_id)
    assert account is not None
    values = {"display_name": account.display_name, "department_id": account.department_id,
              "role_codes": list(account.role_codes), "enabled": account.enabled, **changes}
    env.admin.update_account(user_id, AccountUpdate(**values))  # type: ignore[arg-type]


def test_disable_account_ends_its_sessions() -> None:
    env = Env()
    uid = env.add_account("HY260404", "Abc123..", [ACCOUNTANT])
    session_id, _ = env.identity.login("HY260404", "Abc123..")
    _update(env, uid, enabled=False)

    assert _code(env.identity.authenticate, session_id, None, False) is ErrorCode.SESSION_REQUIRED
    [event] = env.events.events
    assert isinstance(event, SessionRevokedEvent)
    assert event.audience == UsersAudience(users=[uid]) and event.payload.reason == "accountDisabled"
    assert _code(env.identity.login, "HY260404", "Abc123..") is ErrorCode.LOGIN_FAILED


def test_revoke_selected_role() -> None:
    env = Env()
    uid = env.add_account("HY090702", "Abc123..", [ACCOUNTANT, BUYER])
    session_id, result = env.identity.login("HY090702", "Abc123..")
    env.identity.select_role(session_id, result.csrf_token, BUYER)
    _update(env, uid, role_codes=[ACCOUNTANT])

    assert _code(env.identity.authenticate, session_id, None, False) is ErrorCode.SESSION_ROLE_REVOKED
    [event] = env.events.events
    assert event.audience == UsersAudience(users=[uid]) and event.payload.reason == "roleRevoked"

    # 角色被撤销的会话可以重新选择账号还有的角色
    env.identity.select_role(session_id, result.csrf_token, ACCOUNTANT)
    assert env.identity.authenticate(session_id, None, False).role_code == ACCOUNTANT


def test_create_account_then_login() -> None:
    env = Env()
    created = env.admin.create_account(AccountCreate(username="zhangsan", display_name="张三", department_id="10",
                                                     password=SecretStr("Abc123.."), role_codes=[ACCOUNTANT]))
    assert (created.username, created.display_name, created.department_id, created.enabled, created.role_codes) == \
        ("zhangsan", "张三", "10", True, [ACCOUNTANT])
    _, result = env.identity.login("zhangsan", "Abc123..")
    assert result.user.user_id == created.user_id and result.selected_role is not None


def test_duplicate_username_rejected() -> None:
    env = Env()
    env.add_account("zhangsan", "Abc123..", [ACCOUNTANT])
    request = AccountCreate(username="zhangsan", display_name="张三", department_id=None, password=SecretStr("Abc123.."),
                            role_codes=[])
    assert _code(env.admin.create_account, request) is ErrorCode.VALIDATION_FAILED


def test_assigned_role_must_exist() -> None:
    """模块说明第 4 节：分配角色时核对角色存在。"""
    env = Env()
    uid = env.add_account("zhangsan", "Abc123..", [ACCOUNTANT])
    with pytest.raises(PlatformError) as caught:
        _update(env, uid, role_codes=[ACCOUNTANT, "NO_SUCH_ROLE"])
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    assert caught.value.details[0].field == "roleCodes"
    assert env.accounts.get(uid).role_codes == (ACCOUNTANT,)  # type: ignore[union-attr]


def test_admin_sets_password() -> None:
    """管理员给账号设密码（旧系统人员管理页的"初始化密码"）。"""
    env = Env()
    uid = env.add_account("zhangsan", "Abc123..", [ACCOUNTANT])
    env.admin.set_password(uid, "Init123..")
    env.identity.login("zhangsan", "Init123..")
    assert _code(env.identity.login, "zhangsan", "Abc123..") is ErrorCode.LOGIN_FAILED


def test_departments_edit() -> None:
    """旧系统部门管理页：新增、改名、删除。"""
    env = Env()
    market = env.admin.create_department("市场部", None)
    env.admin.create_department("国内营销中心", market.department_id)
    env.admin.update_department(market.department_id, "国际市场部", None)
    names = [(d.name, d.parent_id) for d in env.admin.departments().items]
    assert names == [("国际市场部", None), ("国内营销中心", market.department_id)]
    env.admin.delete_department(market.department_id)
    assert [d.name for d in env.admin.departments().items] == ["国内营销中心"]
