"""`AccountImporter` 的契约测试（C08 第 3 节；导入规则见 identity 的 ID-08）。

真实实现（identity）的测试继承 `AccountImporterContract`，提供 `harness` fixture，实现 `AccountImporterHarness`。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeDirectory
from cost_platform.contracts.ports import AccountImporter, DirectoryReader
from cost_platform.contracts.types import (
    AccountBatch,
    AccountRef,
    ImportedAccount,
    ImportedDepartment,
    ImportedRole,
    RoleAssignment,
)

_HASH = "$2a$10$abcdefghijklmnopqrstuuAbCdEfGhIjKlMnOpQrStUvWxYz01234"
ACCOUNTS = [
    ImportedAccount(user_id="9101", username="ct_import_a", display_name="导入甲", department_id="91", enabled=True, password_hash=_HASH),
    ImportedAccount(user_id="9102", username="ct_import_b", display_name="导入乙", department_id=None, enabled=False, password_hash=_HASH),
]
BATCH = AccountBatch(
    accounts=ACCOUNTS,
    roles=[ImportedRole(code="CT_IMPORTED", name="导入的角色")],
    assignments=[RoleAssignment(user_id="9101", role_code="CT_IMPORTED"), RoleAssignment(user_id="9102", role_code="CT_IMPORTED")],
    departments=[ImportedDepartment(department_id="91", name="导入的部门", parent_id=None)],
)


def _ref(a: ImportedAccount) -> AccountRef:
    return AccountRef(a.user_id, a.username, a.display_name, a.department_id, a.enabled)


class AccountImporterHarness(Protocol):
    importer: AccountImporter
    reader: DirectoryReader
    """读取同一份账号数据，用来核对导入的结果。"""


class AccountImporterContract:
    @pytest.fixture
    def harness(self) -> AccountImporterHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_imports_accounts_and_assignments(self, harness: AccountImporterHarness) -> None:
        """imported 只数账号，角色、分配和部门不计入（C08 第 1 节）。"""
        report = harness.importer.import_batch(BATCH)
        assert report.skipped == []
        assert report.imported == len(ACCOUNTS)
        for account in ACCOUNTS:
            assert harness.reader.account(account.user_id) == _ref(account)
        # 停用的账号也导入，但不在启用账号中
        assert harness.reader.enabled_accounts_with_role("CT_IMPORTED") == [_ref(ACCOUNTS[0])]

    def test_existing_accounts_are_not_overwritten(self, harness: AccountImporterHarness) -> None:
        """已存在的账号不覆盖，角色分配也不改，列入 skipped，标识为 account:<userId>。"""
        harness.importer.import_batch(BATCH)
        changed = replace(BATCH, accounts=[replace(a, display_name="改过的名字", enabled=True) for a in ACCOUNTS],
                          assignments=[*BATCH.assignments, RoleAssignment(user_id="9101", role_code="CT_EXTRA")])
        report = harness.importer.import_batch(changed)
        assert report.imported == 0
        assert sorted(ident for ident, _ in report.skipped) == ["account:9101", "account:9102"]
        assert all(reason for _, reason in report.skipped)
        for account in ACCOUNTS:
            assert harness.reader.account(account.user_id) == _ref(account)
        assert harness.reader.enabled_accounts_with_role("CT_IMPORTED") == [_ref(ACCOUNTS[0])]
        assert harness.reader.enabled_accounts_with_role("CT_EXTRA") == []

    def test_same_id_or_same_username_counts_as_existing(self, harness: AccountImporterHarness) -> None:
        """账号编号相同、或账号名相同，都算已存在（C08 第 3 节），各自列入 skipped，标识取导入的账号编号。"""
        harness.importer.import_batch(BATCH)
        same_id = replace(ACCOUNTS[0], username="ct_import_other")
        same_name = replace(ACCOUNTS[0], user_id="9103")
        report = harness.importer.import_batch(AccountBatch(accounts=[same_id, same_name], roles=[], assignments=[], departments=[]))
        assert report.imported == 0
        assert sorted(ident for ident, _ in report.skipped) == ["account:9101", "account:9103"]
        assert harness.reader.account("9101") == _ref(ACCOUNTS[0])
        assert harness.reader.account("9103") is None

    def test_mixed_batch_counts_only_imported(self, harness: AccountImporterHarness) -> None:
        harness.importer.import_batch(replace(BATCH, accounts=ACCOUNTS[:1], assignments=BATCH.assignments[:1]))
        report = harness.importer.import_batch(BATCH)
        assert report.imported == 1
        assert [ident for ident, _ in report.skipped] == ["account:9101"]
        assert harness.reader.account("9102") == _ref(ACCOUNTS[1])


class FakeAccountImporterHarness:
    def __init__(self) -> None:
        self.importer = self.reader = FakeDirectory()


class TestFakeAccountImporter(AccountImporterContract):
    @pytest.fixture
    def harness(self) -> FakeAccountImporterHarness:
        return FakeAccountImporterHarness()


def test_password_hash_not_in_repr() -> None:
    """ImportedAccount 的密码哈希不进日志（C08 第 3 节）。"""
    assert _HASH not in repr(ACCOUNTS[0])
