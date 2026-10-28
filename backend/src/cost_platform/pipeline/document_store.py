"""业务表的加锁读取、明细读取和写入（WP-03、WP-09）。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from sqlalchemy import text

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import EntityConfig, EntityField, Row, RowChange
from cost_platform.contracts.values import from_db, from_wire, to_db, to_wire


def _source(entity: EntityConfig) -> tuple[str, list[tuple[EntityField, str]]]:
    """读取的表或视图，以及每个字段在其中的列：视图按字段名，表按 `column`。"""
    if entity.read_view:
        return entity.read_view, [(f, f.name) for f in entity.fields]
    return entity.table, [(f, f.column) for f in entity.fields if f.column]


def _field(entity: EntityConfig, name: str) -> EntityField:
    return next(f for f in entity.fields if f.name == name)


def _read_column(entity: EntityConfig, name: str) -> str:
    """字段在读取来源（视图或表）中的列名。"""
    return name if entity.read_view else str(_field(entity, name).column)


def _rows(entity_code: str, entity: EntityConfig, columns: Sequence[tuple[EntityField, str]],
          records: Iterable[Sequence[object]]) -> dict[str, Row]:
    pk = _field(entity, entity.primary_key)
    rows: dict[str, Row] = {}
    for record in records:
        values = {field.name: from_db(field.type, raw) for (field, _), raw in zip(columns, record)}
        key = str(to_wire(pk.type, values[pk.name]))
        rows[key] = Row(entity=entity_code, row_key=key, client_row_id=None, values=values)
    return rows


class OracleDocumentStore:
    def __init__(self, lock_wait_seconds: int) -> None:
        self._wait = int(lock_wait_seconds)

    def lock_load(self, uow: UnitOfWork, entity_code: str, entity: EntityConfig, row_keys: list[str]) -> dict[str, Row]:
        source, columns = _source(entity)
        pk = _field(entity, entity.primary_key)
        pk_column = _read_column(entity, pk.name)
        keys = sorted({from_wire(pk.type, k) for k in row_keys})  # type: ignore[type-var]
        binds = {f"k{i}": k for i, k in enumerate(keys)}
        select = ", ".join(column for _, column in columns)
        sql = (f"SELECT {select} FROM {source} WHERE {pk_column} IN ({', '.join(':' + b for b in binds)}) "
               f"ORDER BY {pk_column} FOR UPDATE WAIT {self._wait}")
        return _rows(entity_code, entity, columns, uow.connection.execute(text(sql), binds))

    def load_details(self, uow: UnitOfWork, entity_code: str, entity: EntityConfig, parent_key: str,
                     record_key: str) -> dict[str, Row]:
        """一条查询读出这张单据的全部明细行，不加锁（单据锁在主表行上）。"""
        source, columns = _source(entity)
        parent = _field(entity, parent_key)
        sql = (f"SELECT {', '.join(column for _, column in columns)} FROM {source} "
               f"WHERE {_read_column(entity, parent_key)} = :record ORDER BY {_read_column(entity, entity.primary_key)}")
        records = uow.connection.execute(text(sql), {"record": from_wire(parent.type, record_key)})
        return _rows(entity_code, entity, columns, records)

    def write(self, uow: UnitOfWork, entity: EntityConfig, changes: list[RowChange]) -> None:
        """修改：按写入的列分组，每组一条批量 UPDATE，写到 `table` 的列。"""
        fields = {f.name: f for f in entity.fields}
        pk = fields[entity.primary_key]
        groups: dict[tuple[str, ...], list[RowChange]] = defaultdict(list)
        for change in changes:
            if change.op == "modify":
                groups[tuple(sorted(change.values))].append(change)
        for names, group in groups.items():
            assignments = ", ".join(f"{fields[n].column} = :v{i}" for i, n in enumerate(names))
            sql = f"UPDATE {entity.table} SET {assignments} WHERE {pk.column} = :pk"
            params = [{**{f"v{i}": to_db(fields[n].type, c.values[n]) for i, n in enumerate(names)},
                       "pk": from_wire(pk.type, c.row_key)} for c in group]
            uow.connection.execute(text(sql), params)
