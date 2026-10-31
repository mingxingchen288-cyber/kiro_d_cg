"""第 8 批（模拟验证）：改已有账号的账号名（ID-11，盘点 B11）、当前用户的部门名称（ID-09，盘点 B10）。

业务例子取自旧系统人员管理（cmx `T_COST_USER`）：技术中心的韩群 HY221020，部门 1069 技术中心。旧系统"用户名"列
可编辑，重名由唯一约束拒绝；改名后用新账号名登录。部门名称同旧系统 `AuthService.getUserInfo` 每次按部门编号查。
"""

from __future__ import annotations

import pytest

from cost_platform.contracts.types import AccountUpdate, ErrorCode, PlatformError

from .support import ACCOUNTANT, Env


def _rename(env: Env, user_id: str, username: str) -> None:
    account = env.accounts.get(user_id)
    assert account is not None
    env.admin.update_account(user_id, AccountUpdate(username=username, display_name=account.display_name,
                                                    department_id=account.department_id,
                                                    role_codes=list(account.role_codes), enabled=account.enabled))


def _tech_center(env: Env) -> str:
    return env.admin.create_department("技术中心", None).department_id


def test_rename_account_then_login_with_new_name() -> None:
    """管理员把 HY221020 改成 HY221021：新名字能登录、旧名字不能；已登录的会话换成新账号名，不用重新登录。"""
    env = Env()
    uid = env.add_account("HY221020", "Abc123..", [ACCOUNTANT], display_name="韩群", department_id=_tech_center(env))
    session_id, _ = env.identity.login("HY221020", "Abc123..")

    _rename(env, uid, "HY221021")

    assert env.accounts.get(uid).username == "HY221021"  # type: ignore[union-attr]
    assert env.identity.authenticate(session_id, None, False).username == "HY221021"
    _, result = env.identity.login("HY221021", "Abc123..")
    assert (result.user.user_id, result.user.username, result.user.display_name) == (uid, "HY221021", "韩群")
    with pytest.raises(PlatformError) as caught:
        env.identity.login("HY221020", "Abc123..")
    assert caught.value.code is ErrorCode.LOGIN_FAILED


def test_rename_to_used_name_is_rejected() -> None:
    """改成别人已用的账号名：422 VALIDATION_FAILED，提示写在 username 上，什么都不改（同新建时重名）。"""
    env = Env()
    env.add_account("HY090702", "Abc123..", [ACCOUNTANT], display_name="汪春龙")
    uid = env.add_account("HY221020", "Abc123..", [ACCOUNTANT], display_name="韩群")

    with pytest.raises(PlatformError) as caught:
        _rename(env, uid, "HY090702")
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    assert caught.value.details[0].field == "username"
    assert caught.value.message == "账号名 HY090702 已存在"
    assert env.accounts.get(uid).username == "HY221020"  # type: ignore[union-attr]


def test_update_without_username_keeps_name() -> None:
    """停用、改姓名等不带 username 的修改照旧，账号名不变。"""
    env = Env()
    uid = env.add_account("HY221020", "Abc123..", [ACCOUNTANT], display_name="韩群")
    env.admin.update_account(uid, AccountUpdate(display_name="韩群（技术）", department_id=None, role_codes=[ACCOUNTANT],
                                                enabled=True))
    account = env.accounts.get(uid)
    assert (account.username, account.display_name) == ("HY221020", "韩群（技术）")  # type: ignore[union-attr]


def test_department_name_in_login_identity_and_me() -> None:
    """登录响应、`/api/me` 的当前用户和执行上下文都带部门名称；没有部门时为 None。"""
    env = Env()
    uid = env.add_account("HY221020", "Abc123..", [ACCOUNTANT], display_name="韩群", department_id=_tech_center(env))
    env.add_account("admin2", "Abc123..", [ACCOUNTANT], department_id=None)

    session_id, result = env.identity.login("HY221020", "Abc123..")
    assert (result.user.department_id, result.user.department_name) == (env.accounts.get(uid).department_id, "技术中心")  # type: ignore[union-attr]
    assert env.identity.authenticate(session_id, None, False).department_name == "技术中心"
    user, _, _ = env.identity.session(session_id)
    assert user.department_name == "技术中心"

    other, result = env.identity.login("admin2", "Abc123..")
    assert result.user.department_name is None
    assert env.identity.authenticate(other, None, False).department_name is None


def test_department_name_follows_account_and_department_changes() -> None:
    """管理员把韩群调到市场部：已登录的会话马上用市场部。市场部改名为"国际市场部"后，刷新页面（`/api/me`）起用新名称，
    同旧系统刷新页面时重新取用户信息。"""
    env = Env()
    uid = env.add_account("HY221020", "Abc123..", [ACCOUNTANT], display_name="韩群", department_id=_tech_center(env))
    market = env.admin.create_department("市场部", None).department_id
    session_id, _ = env.identity.login("HY221020", "Abc123..")

    env.admin.update_account(uid, AccountUpdate(display_name="韩群", department_id=market, role_codes=[ACCOUNTANT],
                                                enabled=True))
    assert env.identity.authenticate(session_id, None, False).department_name == "市场部"

    env.admin.update_department(market, "国际市场部", None)
    user, _, _ = env.identity.session(session_id)
    assert user.department_name == "国际市场部"
    assert env.identity.authenticate(session_id, None, False).department_name == "国际市场部"
