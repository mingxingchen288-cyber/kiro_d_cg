"""`ConnectionFactory` 的契约测试（C08 第 2 节）。

真实实现（db-core）的测试继承 `ConnectionFactoryContract`，提供 `harness` fixture，实现 `ConnectionFactoryHarness`。
"""

from __future__ import annotations

from typing import Protocol

import pytest
from sqlalchemy import exc, text
from sqlalchemy.engine import Connection

from cost_platform.contracts.fakes import FakeConnectionFactory
from cost_platform.contracts.ports import ConnectionFactory


class ConnectionFactoryHarness(Protocol):
    factory: ConnectionFactory

    def legacy_table(self) -> tuple[str, int]:
        """旧库中一张可以读取的表（不带 CMX. 前缀）和它的行数。"""
        ...


class ConnectionFactoryContract:
    @pytest.fixture
    def harness(self) -> ConnectionFactoryHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_reads_legacy_tables_as_cmx(self, harness: ConnectionFactoryHarness) -> None:
        table, count = harness.legacy_table()
        with harness.factory.legacy_readonly() as connection:
            assert isinstance(connection, Connection)
            assert connection.execute(text(f"SELECT COUNT(*) FROM CMX.{table}")).scalar() == count

    @pytest.mark.parametrize("statement", [
        "INSERT INTO CMX.{table} SELECT * FROM CMX.{table} WHERE 1 = 0",
        "DELETE FROM CMX.{table} WHERE 1 = 0",
    ], ids=["insert", "delete"])
    def test_writes_are_rejected(self, harness: ConnectionFactoryHarness, statement: str) -> None:
        """只读事务中的写语句由数据库拒绝，即使不影响任何行。"""
        table, count = harness.legacy_table()
        with harness.factory.legacy_readonly() as connection, pytest.raises(exc.DBAPIError):
            connection.execute(text(statement.format(table=table)))
        with harness.factory.legacy_readonly() as connection:
            assert connection.execute(text(f"SELECT COUNT(*) FROM CMX.{table}")).scalar() == count


class FakeConnectionFactoryHarness:
    def __init__(self) -> None:
        self.factory = FakeConnectionFactory()
        self.factory.add_legacy_table("T_COST_GOODS", {"GOODSID": "INTEGER", "NAME": "VARCHAR(50)"},
                                      [{"GOODSID": 115, "NAME": "胶囊壳"}, {"GOODSID": 116, "NAME": "铝箔"}])

    def legacy_table(self) -> tuple[str, int]:
        return "T_COST_GOODS", 2


class TestFakeConnectionFactory(ConnectionFactoryContract):
    @pytest.fixture
    def harness(self) -> FakeConnectionFactoryHarness:
        return FakeConnectionFactoryHarness()
