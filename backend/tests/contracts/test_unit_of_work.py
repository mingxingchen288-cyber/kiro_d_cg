"""`UnitOfWorkFactory`、`UnitOfWork` 的契约测试（C08 第 2 节）。

真实实现（db-core）的测试继承 `UnitOfWorkContract`，提供 `harness` fixture，实现 `UnitOfWorkHarness`。
"""

from __future__ import annotations

from typing import Protocol

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection

from cost_platform.contracts.fakes import FakeUnitOfWorkFactory
from cost_platform.contracts.ports import UnitOfWork, UnitOfWorkFactory


class UnitOfWorkHarness(Protocol):
    factory: UnitOfWorkFactory

    def write(self, uow: UnitOfWork, value: str) -> None:
        """在这个事务中写入一条数据。"""
        ...

    def committed(self) -> list[str]:
        """另开连接读出已提交的全部数据，按值排序。"""
        ...


class UnitOfWorkContract:
    @pytest.fixture
    def harness(self) -> UnitOfWorkHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_connection_is_sqlalchemy_connection(self, harness: UnitOfWorkHarness) -> None:
        with harness.factory.begin() as uow:
            assert isinstance(uow.connection, Connection)

    def test_commit_keeps_writes(self, harness: UnitOfWorkHarness) -> None:
        with harness.factory.begin() as uow:
            harness.write(uow, "a")
            uow.commit()
        assert harness.committed() == ["a"]

    def test_exit_without_commit_rolls_back(self, harness: UnitOfWorkHarness) -> None:
        with harness.factory.begin() as uow:
            harness.write(uow, "a")
        assert harness.committed() == []

    def test_explicit_rollback_discards_writes(self, harness: UnitOfWorkHarness) -> None:
        with harness.factory.begin() as uow:
            harness.write(uow, "a")
            uow.rollback()
        assert harness.committed() == []

    def test_error_inside_rolls_back_and_propagates(self, harness: UnitOfWorkHarness) -> None:
        with pytest.raises(RuntimeError, match="中途失败"), harness.factory.begin() as uow:
            harness.write(uow, "a")
            raise RuntimeError("中途失败")
        assert harness.committed() == []

    def test_transactions_are_independent(self, harness: UnitOfWorkHarness) -> None:
        with harness.factory.begin() as uow:
            harness.write(uow, "a")
            uow.commit()
        with harness.factory.begin() as uow:
            harness.write(uow, "b")
        with harness.factory.begin() as uow:
            harness.write(uow, "c")
            uow.commit()
        assert harness.committed() == ["a", "c"]


class FakeUnitOfWorkHarness:
    def __init__(self) -> None:
        self.factory = FakeUnitOfWorkFactory()
        with self.factory.engine.connect() as connection:
            connection.execute(text("CREATE TABLE CT_PROBE (V VARCHAR(20))"))
            connection.commit()

    def write(self, uow: UnitOfWork, value: str) -> None:
        uow.connection.execute(text("INSERT INTO CT_PROBE (V) VALUES (:v)"), {"v": value})

    def committed(self) -> list[str]:
        with self.factory.engine.connect() as connection:
            return [r[0] for r in connection.execute(text("SELECT V FROM CT_PROBE ORDER BY V"))]


class TestFakeUnitOfWork(UnitOfWorkContract):
    @pytest.fixture
    def harness(self) -> FakeUnitOfWorkHarness:
        return FakeUnitOfWorkHarness()


def test_fake_records_outcome_and_preset_errors() -> None:
    """替代实现：`units` 记下每个事务的结局；`begin`、`commit` 可以预设错误，预设的提交失败时事务回滚。"""
    from cost_platform.contracts.types import ErrorCode, PlatformError

    harness = FakeUnitOfWorkHarness()
    factory = harness.factory
    with factory.begin() as uow:
        uow.commit()
    with factory.begin():
        pass
    assert [(u.committed, u.rolled_back) for u in factory.units] == [(True, False), (False, True)]
    factory.fail("begin", PlatformError(ErrorCode.DATABASE_UNAVAILABLE, "数据库不可用"))
    with pytest.raises(PlatformError) as caught, factory.begin():
        pass
    assert caught.value.code is ErrorCode.DATABASE_UNAVAILABLE
    factory.fail("commit", PlatformError(ErrorCode.DATABASE_UNAVAILABLE, "连接断开"))
    with pytest.raises(PlatformError), factory.begin() as uow:
        harness.write(uow, "x")
        uow.commit()
    assert harness.committed() == []
    assert factory.units[-1].rolled_back
