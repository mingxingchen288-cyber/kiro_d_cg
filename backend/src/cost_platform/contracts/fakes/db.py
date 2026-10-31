"""db-core 端口的替代实现（C08 第 2 节）。

事务和只读连接用内存中的 SQLite，提交、回滚和只读都是数据库的真实行为，契约测试可以用 SQL 验证。

数值的限制：声明为 NUMBER、NUMERIC、DECIMAL、INTEGER、INT 的列读出为 Decimal，写入时可以绑定 Decimal；
但 SQLite 按浮点存储小数，超过约 15 位有效数字会丢精度，SQL 表达式（例如 `A + B`）的结果仍是 float。
数值的精确往返只能在 Oracle 上验证（db-core 的 T-DB-1），不要用这里的事务验证数值精度。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection, RootTransaction
from sqlalchemy.pool import StaticPool

from ..types import ColumnInfo, DbObject
from ._script import Scripted

sqlite3.register_adapter(Decimal, str)
for _declared in ("NUMBER", "NUMERIC", "DECIMAL", "INTEGER", "INT"):
    sqlite3.register_converter(_declared, lambda raw: Decimal(raw.decode("ascii")))


def _engine() -> Engine:
    """内存 SQLite；所有连接共用同一个库，按列的声明类型转换数值。"""
    return create_engine("sqlite://", poolclass=StaticPool, connect_args={"detect_types": sqlite3.PARSE_DECLTYPES})


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
        self.engine = _engine()
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
    """`SchemaInspector`：表和视图的结构由 `add_table`、`add_view` 预设；表的主键由 `add_table` 的 `primary_key` 给出，
    列注释由 `comments` 给出（没给的列没有注释）。"""

    scriptable = ('columns', 'object_type', 'primary_key', 'column_comments', 'objects', 'view_sources')

    def __init__(self) -> None:
        super().__init__()
        self._tables: dict[str, dict[str, ColumnInfo]] = {}
        self._types: dict[str, Literal["table", "view"]] = {}
        self._keys: dict[str, str] = {}
        self._comments: dict[str, dict[str, str]] = {}
        self._sources: dict[str, list[str]] = {}

    def add_table(self, table: str, columns: Sequence[ColumnInfo], primary_key: str | None = None,
                  comments: Mapping[str, str] | None = None) -> None:
        self._tables[table] = {c.name: c for c in columns}
        self._types[table] = "table"
        self._comments[table] = dict(comments or {})
        if primary_key is not None:
            self._keys[table] = primary_key

    def add_view(self, view: str, columns: Sequence[ColumnInfo], comments: Mapping[str, str] | None = None,
                 sources: Sequence[str] = ()) -> None:
        """`sources`：视图读取的表、视图（`view_sources` 的结果）；没给时为空。"""
        self._tables[view] = {c.name: c for c in columns}
        self._types[view] = "view"
        self._comments[view] = dict(comments or {})
        self._sources[view] = sorted(sources)

    def columns(self, table: str) -> dict[str, ColumnInfo] | None:
        self._record("columns", table)
        found = self._tables.get(table)
        return None if found is None else dict(found)

    def object_type(self, name: str) -> Literal["table", "view"] | None:
        self._record("object_type", name)
        return self._types.get(name)

    def primary_key(self, table: str) -> str | None:
        self._record("primary_key", table)
        return self._keys.get(table) if self._types.get(table) == "table" else None

    def column_comments(self, table: str) -> dict[str, str | None] | None:
        self._record("column_comments", table)
        found = self._tables.get(table)
        if found is None:
            return None
        comments = self._comments.get(table, {})
        return {name: comments.get(name) for name in found}

    def objects(self, keyword: str) -> list[DbObject]:
        self._record("objects", keyword)
        upper = keyword.strip().upper()
        found = [DbObject(name=name, type=kind) for name, kind in self._types.items() if upper in name.upper()]
        return sorted(found, key=lambda o: (o.type, o.name))[:100]

    def view_sources(self, view: str) -> list[str] | None:
        self._record("view_sources", view)
        return list(self._sources[view]) if self._types.get(view) == "view" else None


class FakeConnectionFactory(Scripted):
    """`ConnectionFactory`：旧库是附加在内存 SQLite 上、名为 CMX 的库，按 `CMX.表名` 读取。

    `legacy_readonly` 打开的连接处于只读状态，写语句由 SQLite 拒绝（抛 sqlalchemy.exc.DBAPIError）。
    旧库的表由 `add_legacy_table` 预设。
    """

    scriptable = ('legacy_readonly',)

    def __init__(self) -> None:
        super().__init__()
        self.engine = _engine()
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
