"""identity 账号存储的真实验证（d_cg）。本次没有运行，由合并后统一运行。

前提：已执行 `platform db upgrade`（含 identity 的 id_0001、id_0002）。测试数据的账号名以 `ct_id_` 开头、
契约测试的账号编号为 9001–9004，每个测试结束后删除；admin 账号只读不改。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime

import pytest
from sqlalchemy import Engine, delete, insert, select

from cost_platform.assembly.settings import Settings
from cost_platform.contracts.fakes import FakeConfigSnapshotReader
from cost_platform.contracts.types import AccountRef, ErrorCode, PlatformError
from cost_platform.db_core.engine import OracleUnitOfWorkFactory, create_oracle_engine
from cost_platform.identity.accounts import ADMIN_USERNAME, OracleAccounts
from cost_platform.identity.service import IdentityService, describe_role_from
from cost_platform.identity.sessions import MemorySessions
from cost_platform.identity.tables import pf_department, pf_user, pf_user_role

from ..contracts.test_directory_reader import DirectoryReaderContract
from .support import ACCOUNTANT, BUYER, fast_passwords, role_snapshot
from .test_passwords import JBCRYPT_ABC

pytestmark = pytest.mark.oracle

DEPARTMENT_PREFIX = "ct_id_"


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now()


@pytest.fixture(scope="module")
def engine() -> Engine:
    s = Settings.load()
    return create_oracle_engine(s.db_user, s.db_password, s.db_dsn)


def _cleanup(engine: Engine) -> None:
    """只删测试数据：账号名以 `ct_` 开头（本文件的 `ct_id_*` 和契约测试的 ct_alice 等）、部门名以 `ct_id_` 开头。"""
    test_user = pf_user.c.username.like("ct\\_%", escape="\\")
    with engine.begin() as conn:
        conn.execute(delete(pf_user_role).where(pf_user_role.c.user_id.in_(select(pf_user.c.user_id).where(test_user))))
        conn.execute(delete(pf_user).where(test_user))
        conn.execute(delete(pf_department).where(pf_department.c.name.like("ct\\_id\\_%", escape="\\")))


@pytest.fixture
def accounts(engine: Engine) -> Iterator[OracleAccounts]:
    _cleanup(engine)
    yield OracleAccounts(OracleUnitOfWorkFactory(engine), passwords=fast_passwords())
    _cleanup(engine)


def test_ensure_admin_second_run_changes_nothing(engine: Engine, accounts: OracleAccounts) -> None:
    """T-ID-1：admin 初始化执行两次，第二次不改任何数据。"""
    accounts.ensure_admin()

    def admin_rows() -> tuple[list[tuple], list[tuple]]:
        with engine.connect() as conn:
            user = list(conn.execute(select(pf_user).where(pf_user.c.username == ADMIN_USERNAME)))
            roles = list(conn.execute(select(pf_user_role).where(pf_user_role.c.user_id.in_(
                select(pf_user.c.user_id).where(pf_user.c.username == ADMIN_USERNAME)))))
        return user, roles

    before = admin_rows()
    assert accounts.ensure_admin() is False
    assert admin_rows() == before


def test_bcrypt_upgraded_on_oracle(accounts: OracleAccounts) -> None:
    """T-ID-1：BCrypt 账号登录成功后哈希改为 Argon2，失败时不改。"""
    passwords = fast_passwords()
    created = accounts.create_account("ct_id_bcrypt", "旧账号", "581", JBCRYPT_ABC[1].decode(), [ACCOUNTANT])
    config = FakeConfigSnapshotReader([role_snapshot(ACCOUNTANT, "成本会计", False)])
    identity = IdentityService(accounts, MemorySessions(), _SystemClock(), 120, describe_role_from(config),
                               passwords=passwords)

    with pytest.raises(PlatformError) as caught:
        identity.login("ct_id_bcrypt", "abd")
    assert caught.value.code is ErrorCode.LOGIN_FAILED
    assert accounts.get(created.user_id).password_hash == JBCRYPT_ABC[1].decode()  # type: ignore[union-attr]

    identity.login("ct_id_bcrypt", "abc")
    upgraded = accounts.get(created.user_id).password_hash  # type: ignore[union-attr]
    assert upgraded is not None and upgraded.startswith("$argon2id$")


def test_duplicate_username_on_oracle(accounts: OracleAccounts) -> None:
    accounts.create_account("ct_id_zhangsan", "张三", None, fast_passwords().hash("Abc123.."), [])
    with pytest.raises(PlatformError) as caught:
        accounts.create_account("ct_id_zhangsan", "张三", None, fast_passwords().hash("Abc123.."), [])
    assert caught.value.code is ErrorCode.VALIDATION_FAILED


def test_update_account_in_one_transaction(accounts: OracleAccounts) -> None:
    """ID-05：停用和角色调整在一个事务内写入，账号版本加一。"""
    created = accounts.create_account("ct_id_lisi", "李四", "581", fast_passwords().hash("Abc123.."), [ACCOUNTANT, BUYER])
    changed = accounts.update_account(created.user_id, "李四", "175", [ACCOUNTANT], enabled=False)
    assert changed is not None
    before, after = changed
    assert (before.version, before.enabled, before.role_codes) == (1, True, (BUYER, ACCOUNTANT))
    assert (after.version, after.enabled, after.role_codes, after.department_id) == (2, False, (ACCOUNTANT,), "175")
    assert accounts.get(created.user_id) == after


def test_list_accounts_paging_on_oracle(accounts: OracleAccounts) -> None:
    ids = [accounts.create_account(f"ct_id_page{i}", f"分页{i}", None, fast_passwords().hash("Abc123.."), [BUYER]).user_id
           for i in range(3)]
    rows, total = accounts.list_accounts("ct_id_page", 1, 3)
    assert total == 3 and [r.user_id for r in rows] == ids[1:]
    rows, total = accounts.list_accounts("", 0, 50, role_code=BUYER)
    assert [r.user_id for r in rows if r.username.startswith("ct_id_")] == ids


def test_departments_on_oracle(accounts: OracleAccounts) -> None:
    created = accounts.create_department(f"{DEPARTMENT_PREFIX}市场部", None)
    assert accounts.update_department(created.department_id, f"{DEPARTMENT_PREFIX}国际市场部", None) is not None
    assert f"{DEPARTMENT_PREFIX}国际市场部" in [d.name for d in accounts.departments()]
    found = accounts.department(created.department_id)
    assert found is not None and (found.name, found.parent_id) == (f"{DEPARTMENT_PREFIX}国际市场部", None)
    assert accounts.delete_department(created.department_id) is True


class OracleDirectoryHarness:
    def __init__(self, engine: Engine, accounts: OracleAccounts) -> None:
        self._engine = engine
        self.reader = accounts

    def add_account(self, account: AccountRef, roles: Iterable[str]) -> None:
        with self._engine.begin() as conn:
            conn.execute(insert(pf_user).values(user_id=int(account.user_id), username=account.username,
                                                display_name=account.display_name, department_id=account.department_id,
                                                enabled=1 if account.enabled else 0, password_hash=None, version=1))
            for code in roles:
                conn.execute(insert(pf_user_role).values(user_id=int(account.user_id), role_code=code))


class TestOracleDirectoryReader(DirectoryReaderContract):
    @pytest.fixture
    def harness(self, engine: Engine, accounts: OracleAccounts) -> OracleDirectoryHarness:
        return OracleDirectoryHarness(engine, accounts)
