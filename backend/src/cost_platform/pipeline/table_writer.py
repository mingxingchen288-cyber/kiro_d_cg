"""写没在平台注册的表（WP-19，C06 7.5）：审批流全部通过后，approval 对受影响单据勾选的行执行的操作。

按主键用 `SELECT … FOR UPDATE WAIT n` 加行锁读出整行；approval 做冻结检查后，按主键只写指定的列，不校验、不计算，
只写实际变化的列（架构 10.4 第 3 步）；数值按 WP-15 处理小数位（列的小数位取 `SchemaInspector`）。改前、改后的列值
记入审计差异，由 `changes(uow)` 取出，随命令记录写入（WP-11，不看页面的 audit）。新增行的主键取序列 `<表名>_SEQ`。

等锁超时（ORA-30006）、死锁（ORA-00060）、表或列不存在等数据库错误不在这里处理：异常离开命令事务时由 db-core 按
C08 第 2 节映射（DOCUMENT_BUSY、INTERNAL_ERROR），整个命令回滚。表名和列名来自已发布的审批流配置（config 保存时
已核对，C06 第 10 节），值一律用绑定变量。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from weakref import WeakKeyDictionary

from sqlalchemy import Date, DateTime, Numeric, String, bindparam, column, insert, literal_column, table, text
from sqlalchemy.types import TypeEngine

from cost_platform.contracts.decimal_text import format_decimal
from cost_platform.contracts.ports import SchemaInspector, UnitOfWork
from cost_platform.contracts.types import DocumentRef, RowChange, Value

from .values import ColumnScales, round_decimal


def _from_db(raw: object) -> Value:
    if isinstance(raw, int) and not isinstance(raw, bool):
        return Decimal(raw)
    return raw  # type: ignore[return-value]


def _type_of(value: Value) -> TypeEngine[Any] | None:
    if isinstance(value, Decimal):
        return Numeric(asdecimal=True)
    if isinstance(value, datetime):
        return DateTime()
    if isinstance(value, date):
        return Date()
    if isinstance(value, str):
        return String()
    return None


def _key_text(value: object) -> str:
    return format_decimal(Decimal(value)) if isinstance(value, (int, Decimal)) and not isinstance(value, bool) else str(value)


class _Unit:
    """一个命令事务中的锁定行和改动。"""

    def __init__(self) -> None:
        self.locked: dict[tuple[str, str, str], dict[str, Value]] = {}
        self.changes: list[RowChange] = []


class OracleTableWriter:
    def __init__(self, lock_wait_seconds: int, inspector: SchemaInspector) -> None:
        self._wait = int(lock_wait_seconds)
        self._inspector = inspector
        self._scales = ColumnScales(inspector)
        self._units: WeakKeyDictionary[UnitOfWork, _Unit] = WeakKeyDictionary()

    def _unit(self, uow: UnitOfWork) -> _Unit:
        if uow not in self._units:
            self._units[uow] = _Unit()
        return self._units[uow]

    def changes(self, uow: UnitOfWork) -> list[RowChange]:
        """本事务中写没注册的表的改动，作为审计差异（`result.audit_changes` 的 `extra`）。"""
        return list(self._unit(uow).changes)

    def lock_row(self, uow: UnitOfWork, table_name: str, key_column: str, key: str) -> dict[str, Value] | None:
        """读出整行并加行锁；不存在时为 None。列名为数据库中的列名（大写）。"""
        sql = f"SELECT * FROM {table_name} WHERE {key_column} = :k FOR UPDATE WAIT {self._wait}"
        result = uow.connection.execute(text(sql), {"k": key})
        record = result.mappings().first()
        if record is None:
            return None
        row = {str(name).upper(): _from_db(value) for name, value in record.items()}
        self._unit(uow).locked[(table_name.upper(), key_column.upper(), key)] = row
        return dict(row)

    def _stored(self, table_name: str, values: dict[str, Value]) -> dict[str, Value]:
        stored: dict[str, Value] = {}
        for name, value in values.items():
            column_name = name.upper()
            if isinstance(value, Decimal):
                value = round_decimal(value, self._scales.scale(table_name, column_name))
            stored[column_name] = None if value == "" else value
        return stored

    def update(self, uow: UnitOfWork, table_name: str, key_column: str, key: str, values: dict[str, Value]) -> None:
        """按主键只写指定的列；行已用 `lock_row` 读出时，值与当前值相同的列不写，都相同时不发 SQL。"""
        new = self._stored(table_name, values)
        unit = self._unit(uow)
        current = unit.locked.get((table_name.upper(), key_column.upper(), key))
        if current is not None:
            new = {c: v for c, v in new.items() if not _same(current.get(c), v)}
        if not new:
            return
        names = list(new)
        assignments = ", ".join(f"{c} = :v{i}" for i, c in enumerate(names))
        statement = text(f"UPDATE {table_name} SET {assignments} WHERE {key_column} = :k").bindparams(
            *(bindparam(f"v{i}", type_=_type_of(new[c])) for i, c in enumerate(names) if _type_of(new[c]) is not None))
        old = {c: current.get(c) for c in new} if current is not None else {}
        uow.connection.execute(statement, {**{f"v{i}": new[c] for i, c in enumerate(names)}, "k": key})
        if current is not None:
            current.update(new)
        unit.changes.append(RowChange(document=DocumentRef(table_name.upper(), key), entity=table_name.upper(), op="modify",
                                      row_key=key, client_row_id=None, values=new, old=old))

    def insert(self, uow: UnitOfWork, table_name: str, values: dict[str, Value]) -> str:
        """主键取 `<表名>_SEQ.NEXTVAL`，用 RETURNING 取回，返回新主键。主键列取 `SchemaInspector.primary_key`。"""
        new = self._stored(table_name, values)
        pk = str(self._inspector.primary_key(table_name)).upper()
        columns = self._inspector.columns(table_name) or {}
        pk_info = next((info for name, info in columns.items() if name.upper() == pk), None)
        pk_type: TypeEngine[Any] = Numeric(asdecimal=True) if pk_info is None or pk_info.data_type.upper() == "NUMBER" else String()
        target = table(table_name.upper(), column(pk, pk_type), *(column(c, _type_of(v)) for c, v in new.items() if c != pk))
        statement = (insert(target).values({pk: literal_column(f"{table_name}_SEQ.NEXTVAL")})
                     .returning(target.c[pk]))
        record = uow.connection.execute(statement, {c: v for c, v in new.items() if c != pk}).first()
        key = _key_text(record[0])
        self._unit(uow).changes.append(RowChange(document=DocumentRef(table_name.upper(), key), entity=table_name.upper(),
                                                 op="add", row_key=key, client_row_id=None,
                                                 values={c: v for c, v in new.items() if c != pk}, old={}))
        return key

    def delete(self, uow: UnitOfWork, table_name: str, key_column: str, key: str) -> None:
        unit = self._unit(uow)
        current = unit.locked.pop((table_name.upper(), key_column.upper(), key), None)
        uow.connection.execute(text(f"DELETE FROM {table_name} WHERE {key_column} = :k"), {"k": key})
        unit.changes.append(RowChange(document=DocumentRef(table_name.upper(), key), entity=table_name.upper(), op="delete",
                                      row_key=key, client_row_id=None, values={}, old=dict(current or {})))


def _same(a: Value, b: Value) -> bool:
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return a == b
    return (a or None) == (b or None) if isinstance(a, str) or isinstance(b, str) else a == b
