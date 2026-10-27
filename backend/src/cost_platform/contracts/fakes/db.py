"""db-core 端口的替代实现（C08 第 2 节）。

事务和只读连接用内存中的 SQLite，提交、回滚和只读都是数据库的真实行为，契约测试可以用 SQL 验证。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, RootTransaction
from sqlalchemy.pool import StaticPool

from ..types import ColumnInfo
from ._script import Scripted


class FakeUnitOfWork:
    """一个事务。`committed`、`rolled_back` 供测试检查事务的结局。"""

    def __init__(self, connection: Connection, owner: FakeUnitOfWorkFactory) -> None:
        self.connection = connection
        self._tx: RootTransaction = connection.begin()
        self._owner = owner
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self._owner._record("commit")
        self._tx.commit()
        self.committed = True

    def rollback(self) -> None:
        self._owner._record("rollback")
        self._end()

    def _end(self) -> None:
        if self._tx.is_active:
            self._tx.rollback()
            self.rolled_back = True


class FakeUnitOfWorkFactory(Scripted):
    """`UnitOfWorkFactory`：每次 `begin` 在同一个内存 SQLite 库上开启一个事务。

    可以预设错误的方法：`begin`、`commit`、`rollback`，例如
    `fail("begin", PlatformError(ErrorCode.DATABASE_UNAVAILABLE, "数据库不可用"))`。
    `units` 按顺序记录开启过的事务。
    """

    scriptable = ("begin", "commit", "rollback")

    def __init__(self) -> None:
        super().__init__()
        self.engine = create_engine("sqlite://", poolclass=StaticPool)
        self.units: list[FakeUnitOfWork] = []

    @contextmanager
    def begin(self) -> Iterator[FakeUnitOfWork]:
        self._record("begin")
        with self.engine.connect() as connection:
            uow = FakeUnitOfWork(connection, self)
            self.units.append(uow)
            try:
                yield uow
            finally:
                uow._end()


class FakeSchemaInspector(Scripted):
    """`SchemaInspector`：表结构由 `add_table` 预设。"""

    scriptable = ('columns',)

    def __init__(self) -> None:
        super().__init__()
        self._tables: dict[str, dict[str, ColumnInfo]] = {}

    def add_table(self, table: str, columns: Sequence[ColumnInfo]) -> None:
        self._tables[table] = {c.name: c for c in columns}

    def columns(self, table: str) -> dict[str, ColumnInfo] | None:
        self._record("columns", table)
        found = self._tables.get(table)
        return None if found is None else dict(found)


class FakeConnectionFactory(Scripted):
    """`ConnectionFactory`：旧库是附加在内存 SQLite 上、名为 CMX 的库，按 `CMX.表名` 读取。

    `legacy_readonly` 打开的连接处于只读状态，写语句由 SQLite 拒绝（抛 sqlalchemy.exc.DBAPIError）。
    旧库的表由 `add_legacy_table` 预设。
    """

    scriptable = ('legacy_readonly',)

    def __init__(self) -> None:
        super().__init__()
        self.engine = create_engine("sqlite://", poolclass=StaticPool)
        with self.engine.connect() as connection:
            connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS CMX")
            connection.commit()

    def add_legacy_table(self, table: str, columns: Mapping[str, str], rows: Sequence[Mapping[str, Any]] = ()) -> None:
        """在旧库中建表并写入数据：`columns` 为列名到 SQL 类型的对应。"""
        names = list(columns)
        with self.engine.connect() as connection:
            connection.execute(text(f"CREATE TABLE CMX.{table} ({', '.join(f'{n} {t}' for n, t in columns.items())})"))
            for row in rows:
                connection.execute(text(f"INSERT INTO CMX.{table} ({', '.join(names)}) VALUES ({', '.join(':' + n for n in names)})"),
                                   dict(row))
            connection.commit()

    @contextmanager
    def legacy_readonly(self) -> Iterator[Connection]:
        self._record("legacy_readonly")
        with self.engine.connect() as connection:
            tx = connection.begin()
            connection.exec_driver_sql("PRAGMA query_only = ON")
            try:
                yield connection
            finally:
                if tx.is_active:
                    tx.rollback()
                connection.exec_driver_sql("PRAGMA query_only = OFF")
