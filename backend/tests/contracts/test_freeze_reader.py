"""`FreezeReader` 的契约测试（C08 第 13 节）。

真实实现（approval）的测试继承 `FreezeReaderContract`，提供 `harness` fixture，实现 `FreezeReaderHarness`。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeFreezeReader, FakeUnitOfWorkFactory
from cost_platform.contracts.ports import FreezeReader, UnitOfWork
from cost_platform.contracts.types import FreezeEntry

A = FreezeEntry(approval_id="203", entity="COST_PINGGU", record_key="1001")
B = FreezeEntry(approval_id="204", entity="COST_PINGGU", record_key="1002")
OTHER_ENTITY = FreezeEntry(approval_id="205", entity="COST_GOODS_PRICE", record_key="1003")


class FreezeReaderHarness(Protocol):
    reader: FreezeReader
    uow: UnitOfWork

    def freeze(self, entry: FreezeEntry) -> None:
        """登记一条冻结记录（所属审批未结束）。"""
        ...


class FreezeReaderContract:
    @pytest.fixture
    def harness(self) -> FreezeReaderHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    @pytest.fixture
    def arranged(self, harness: FreezeReaderHarness) -> FreezeReaderHarness:
        for entry in (A, B, OTHER_ENTITY):
            harness.freeze(entry)
        return harness

    def test_returns_only_requested_frozen_documents(self, arranged: FreezeReaderHarness) -> None:
        """按单据主键返回冻结记录，未冻结的不在结果中。"""
        found = arranged.reader.find(arranged.uow, "COST_PINGGU", ["1001", "1009"])
        assert found == {"1001": A}

    def test_filters_by_entity(self, arranged: FreezeReaderHarness) -> None:
        assert arranged.reader.find(arranged.uow, "COST_PINGGU", ["1003"]) == {}
        assert arranged.reader.find(arranged.uow, "COST_GOODS_PRICE", ["1001", "1003"]) == {"1003": OTHER_ENTITY}

    def test_several_documents(self, arranged: FreezeReaderHarness) -> None:
        assert arranged.reader.find(arranged.uow, "COST_PINGGU", ["1002", "1001"]) == {"1001": A, "1002": B}

    def test_empty_request(self, arranged: FreezeReaderHarness) -> None:
        assert arranged.reader.find(arranged.uow, "COST_PINGGU", []) == {}


class FakeFreezeReaderHarness:
    def __init__(self) -> None:
        self._stack = ExitStack()
        self.uow = self._stack.enter_context(FakeUnitOfWorkFactory().begin())
        self.reader = FakeFreezeReader()

    def close(self) -> None:
        self._stack.close()

    def freeze(self, entry: FreezeEntry) -> None:
        self.reader.freeze(entry)


class TestFakeFreezeReader(FreezeReaderContract):
    @pytest.fixture
    def harness(self) -> Iterator[FakeFreezeReaderHarness]:
        harness = FakeFreezeReaderHarness()
        yield harness
        harness.close()


def test_fake_one_approval_per_document() -> None:
    """替代实现：同一张单据不能被第二个审批冻结；解除后可以。"""
    reader = FakeFreezeReader()
    reader.freeze(A)
    with pytest.raises(ValueError):
        reader.freeze(FreezeEntry(approval_id="999", entity=A.entity, record_key=A.record_key))
    reader.release(A.approval_id)
    reader.freeze(FreezeEntry(approval_id="999", entity=A.entity, record_key=A.record_key))
