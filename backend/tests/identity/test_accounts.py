"""T-ID-1 的账号数据（模拟验证）：admin 初始化（ID-06）、账号名唯一（ID-07）、账号列表，以及 `DirectoryReader` 的契约测试。"""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from sqlalchemy import insert, select

from cost_platform.contracts.types import AccountRef, Department, ErrorCode, PlatformError
from cost_platform.identity.accounts import ADMIN_PASSWORD, ADMIN_ROLE, ADMIN_USERNAME, OracleAccounts
from cost_platform.identity.tables import pf_user, pf_user_role

from ..contracts.test_directory_reader import DirectoryReaderContract
from .support import ACCOUNTANT, BUYER, Env


def _rows(env: Env) -> tuple[list[tuple], list[tuple]]:
    with env.uow.engine.connect() as conn:
        return (list(conn.execute(select(pf_user).order_by(pf_user.c.user_id))),
                list(conn.execute(select(pf_user_role).order_by(pf_user_role.c.user_id, pf_user_role.c.role_code))))


def test_ensure_admin_twice_changes_nothing_the_second_time() -> None:
    env = Env()
    assert env.accounts.ensure_admin() is True
    first = _rows(env)
    admin = env.accounts.find(ADMIN_USERNAME)
    assert admin is not None and admin.enabled and admin.role_codes == (ADMIN_ROLE,)
    assert env.passwords.verify(admin.password_hash, ADMIN_PASSWORD).ok

    assert env.accounts.ensure_admin() is False
    assert _rows(env) == first


def test_duplicate_username_is_validation_failed() -> None:
    env = Env()
    env.add_account("HY260404", "Abc123..", [ACCOUNTANT], display_name="程苏慧")
    with pytest.raises(PlatformError) as caught:
        env.add_account("HY260404", "Abc123..", [BUYER])
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    assert caught.value.details[0].field == "username"


def test_list_accounts_by_keyword_role_and_page() -> None:
    env = Env()
    cheng = env.add_account("HY260404", "Abc123..", [ACCOUNTANT], display_name="程苏慧")
    wang = env.add_account("HY090702", "Abc123..", [BUYER], display_name="汪春龙")
    buyer = env.add_account("CS008", "Abc123..", [BUYER], display_name="采购")

    rows, total = env.accounts.list_accounts("hy", 0, 50)
    assert ([r.user_id for r in rows], total) == ([cheng, wang], 2)

    rows, total = env.accounts.list_accounts("采购", 0, 50)
    assert ([r.username for r in rows], total) == (["CS008"], 1)

    rows, total = env.accounts.list_accounts("", 0, 50, role_code=BUYER)
    assert ([r.user_id for r in rows], [r.role_codes for r in rows], total) == ([wang, buyer], [(BUYER,), (BUYER,)], 2)

    rows, total = env.accounts.list_accounts("", 1, 2)
    assert ([r.user_id for r in rows], total) == ([wang], 3)


def test_departments_listed() -> None:
    env = Env()
    first = env.accounts.create_department("市场部", None)
    second = env.accounts.create_department("国内营销中心", first.department_id)
    assert env.accounts.departments() == [first, second]
    assert second.parent_id == first.department_id


def test_department_read_for_directory() -> None:
    """`DirectoryReader.department`：config 保存审批流时核对节点的部门存在（C06 第 10 节）。"""
    env = Env()
    market = env.accounts.create_department("市场部", None)
    domestic = env.accounts.create_department("国内营销中心", market.department_id)
    assert env.accounts.department(domestic.department_id) == Department(
        department_id=domestic.department_id, name="国内营销中心", parent_id=market.department_id)
    assert env.accounts.department("999") is None


# ---------------------------------------------------------------- DirectoryReader 契约测试（C08 第 14 节）

class SqliteDirectoryHarness:
    """账号按契约测试给定的编号直接写入表中（契约测试要比较 user_id）。"""

    def __init__(self) -> None:
        self.env = Env()
        self.reader: OracleAccounts = self.env.accounts

    def add_account(self, account: AccountRef, roles: Iterable[str]) -> None:
        insert_account(self.env.uow.engine, account, roles)


def insert_account(engine: object, account: AccountRef, roles: Iterable[str]) -> None:
    with engine.begin() as conn:  # type: ignore[attr-defined]
        conn.execute(insert(pf_user).values(user_id=int(account.user_id), username=account.username,
                                            display_name=account.display_name, department_id=account.department_id,
                                            enabled=1 if account.enabled else 0, password_hash=None, version=1))
        codes = list(roles)
        if codes:
            conn.execute(insert(pf_user_role), [{"user_id": int(account.user_id), "role_code": c} for c in codes])


class TestDirectoryReader(DirectoryReaderContract):
    @pytest.fixture
    def harness(self) -> SqliteDirectoryHarness:
        return SqliteDirectoryHarness()
