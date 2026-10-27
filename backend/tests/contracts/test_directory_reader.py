"""`DirectoryReader` 的契约测试（C08 第 3 节）。

真实实现（identity）的测试继承 `DirectoryReaderContract`，提供 `harness` fixture，实现 `DirectoryReaderHarness`。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeDirectory
from cost_platform.contracts.ports import DirectoryReader
from cost_platform.contracts.types import AccountRef

ALICE = AccountRef(user_id="9001", username="ct_alice", display_name="甲", department_id="10", enabled=True)
BOB = AccountRef(user_id="9002", username="ct_bob", display_name="乙", department_id=None, enabled=True)
CAROL = AccountRef(user_id="9003", username="ct_carol", display_name="丙", department_id="10", enabled=False)
DAVE = AccountRef(user_id="9004", username="ct_dave", display_name="丁", department_id="20", enabled=True)


class DirectoryReaderHarness(Protocol):
    reader: DirectoryReader

    def add_account(self, account: AccountRef, roles: Iterable[str]) -> None:
        """建一个账号并分配这些角色。"""
        ...


class DirectoryReaderContract:
    @pytest.fixture
    def harness(self) -> DirectoryReaderHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    @pytest.fixture
    def arranged(self, harness: DirectoryReaderHarness) -> DirectoryReaderHarness:
        harness.add_account(ALICE, ["CT_MANAGER", "CT_CLERK"])
        harness.add_account(BOB, ["CT_MANAGER"])
        harness.add_account(CAROL, ["CT_MANAGER"])
        harness.add_account(DAVE, ["CT_CLERK"])
        return harness

    def test_enabled_accounts_with_role(self, arranged: DirectoryReaderHarness) -> None:
        """只返回启用、且分配了这个角色的账号；顺序不限。"""
        found = arranged.reader.enabled_accounts_with_role("CT_MANAGER")
        assert sorted(found, key=lambda a: a.user_id) == [ALICE, BOB]

    def test_role_without_accounts(self, arranged: DirectoryReaderHarness) -> None:
        assert arranged.reader.enabled_accounts_with_role("CT_NOBODY") == []

    def test_account_by_id(self, arranged: DirectoryReaderHarness) -> None:
        assert arranged.reader.account(BOB.user_id) == BOB
        assert arranged.reader.account(CAROL.user_id) == CAROL  # 停用的账号也能读到，enabled 为 False
        assert arranged.reader.account("9999") is None


class FakeDirectoryHarness:
    def __init__(self) -> None:
        self.reader = FakeDirectory()

    def add_account(self, account: AccountRef, roles: Iterable[str]) -> None:
        self.reader.add_account(account, roles)


class TestFakeDirectoryReader(DirectoryReaderContract):
    @pytest.fixture
    def harness(self) -> FakeDirectoryHarness:
        return FakeDirectoryHarness()
