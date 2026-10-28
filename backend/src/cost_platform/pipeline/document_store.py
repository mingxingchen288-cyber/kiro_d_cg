"""业务表的加锁读取和写入（WP-03、WP-09）。"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import EntityConfig, EntityField, Row, RowChange
from cost_platform.contracts.values import from_db, from_wire, to_wire


def _source(entity: EntityConfig) -> tuple[str, list[tuple[EntityField, str]]]:
    """读取的表或视图，以及每个字段在其中的列：视图按字段名，表按 `column`。"""
    if entity.read_view:
        return entity.read_view, [(f, f.name) for f in entity.fields]
    return entity.table, [(f, f.column) for f in entity.fields if f.column]


def _pk_field(entity: EntityConfig) -> EntityField:
    return next(f for f in entity.fields if f.name == entity.primary_key)


class OracleDocumentStore:
    def __init__(self, lock_wait_seconds: int) -> None:
        self._wait = int(lock_wait_seconds)

    def lock_load(self, uow: UnitOfWork, entity_code: str, entity: EntityConfig, row_keys: list[str]) -> dict[str, Row]:
        source, columns = _source(entity)
        pk = _pk_field(entity)
        pk_column = pk.name if entity.read_view else pk.column
        keys = sorted({from_wire(pk.type, k) for k in row_keys})  # type: ignore[type-var]
        binds = {f"k{i}": k for i, k in enumerate(keys)}
        select = ", ".join(column for _, column in columns)
        sql = (f"SELECT {select} FROM {source} WHERE {pk_column} IN ({', '.join(':' + b for b in binds)}) "
               f"ORDER BY {pk_column} FOR UPDATE WAIT {self._wait}")
        rows: dict[str, Row] = {}
        for record in uow.connection.execute(text(sql), binds):
            values = {field.name: from_db(field.type, raw) for (field, _), raw in zip(columns, record)}
            key = str(to_wire(pk.type, values[pk.name]))
            rows[key] = Row(entity=entity_code, row_key=key, client_row_id=None, values=values)
        return rows

    def write(self, uow: UnitOfWork, entity: EntityConfig, changes: list[RowChange]) -> None:
        """修改：按写入的列分组，每组一条批量 UPDATE。"""
        fields = {f.name: f for f in entity.fields}
        pk = _pk_field(entity)
        groups: dict[tuple[str, ...], list[RowChange]] = defaultdict(list)
        for change in changes:
            if change.op == "modify":
                groups[tuple(sorted(change.values))].append(change)
        for names, group in groups.items():
            assignments = ", ".join(f"{fields[n].column} = :v{i}" for i, n in enumerate(names))
            sql = f"UPDATE {entity.table} SET {assignments} WHERE {pk.column} = :pk"
            params = [{**{f"v{i}": c.values[n] for i, n in enumerate(names)}, "pk": from_wire(pk.type, c.row_key)}
                      for c in group]
            uow.connection.execute(text(sql), params)
