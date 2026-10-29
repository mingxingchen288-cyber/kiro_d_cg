"""单据中的行：按实体和主键（或新增行的临时编号）找行，取命令中做了修改的行，取一行所属单据（C06 7.5"表 + 主键"）。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    CommandState,
    DocumentData,
    DocumentRef,
    EntityConfig,
    ErrorCode,
    PlatformError,
    Row,
    RowOp,
    Value,
)

from .catalog import ApprovalCatalog, TableEntity
from .sql import SqlRunner, key_text, keys_sql


@dataclass(frozen=True)
class ChangedRow:
    """命令中一行的修改：`new` 为合并修改并计算后的整行（删除行为空），`old` 为加锁读到的整行（新增行为空）。"""

    entity: str
    op: RowOp
    row_key: str | None
    client_row_id: str | None
    new: Mapping[str, Value]
    old: Mapping[str, Value]


def find_row(doc: DocumentData | None, entity: str, row_key: str | None, client_row_id: str | None) -> Row | None:
    if doc is None:
        return None
    rows = [doc.master] if entity == doc.master.entity else doc.details.get(entity, [])
    for row in rows:
        if row_key is not None and row.row_key == row_key:
            return row
        if client_row_id is not None and row.client_row_id == client_row_id:
            return row
    return None


def changed_rows(state: CommandState, ref: DocumentRef) -> list[ChangedRow]:
    """这张单据在本命令中有实际变化的行（`changes`），按变更计划中的顺序。"""
    candidate = state.candidate.get(ref)
    current = state.current.get(ref)
    found: list[ChangedRow] = []
    for change in state.changes.rows:
        if change.document != ref:
            continue
        before = find_row(current, change.entity, change.row_key, None) if change.op != "add" else None
        after = find_row(candidate, change.entity, change.row_key, change.client_row_id) if change.op != "delete" else None
        old = dict(before.values) if before is not None else ({} if change.op == "add" else dict(change.old))
        new: dict[str, Value] = {} if change.op == "delete" else {**old, **(dict(after.values) if after else {}), **change.values}
        found.append(ChangedRow(change.entity, change.op, change.row_key, change.client_row_id, new, old))
    return found


def field_column(entity: EntityConfig, name: str) -> str | None:
    return next((f.column for f in entity.fields if f.name == name), None)


def column_field(entity: EntityConfig, column: str) -> str | None:
    return next((f.name for f in entity.fields if f.column is not None and f.column.upper() == column.upper()), None)


@dataclass(frozen=True)
class Owner:
    """注册过的表中一行所属的实体和单据。"""

    entity: TableEntity
    document: DocumentRef


def owners(sql: SqlRunner, uow: UnitOfWork, catalog: ApprovalCatalog, table: str, keys: Sequence[str]) -> dict[str, Owner]:
    """注册过的表：按"表 + 主键"找出每一行所属的实体（同一张表属于几个实体时，取读取视图里查得到这一行的那个）和单据。
    主表实体的行就是单据本身；明细行按 `details.parentKey` 归到所属主单。找不到的行（已不存在）不在结果中。"""
    found: dict[str, Owner] = {}
    entities = catalog.entities_on_table(table)
    wanted = list(dict.fromkeys(keys))
    for entity in entities:
        rest = [k for k in wanted if k not in found]
        if not rest:
            break
        config = entity.config
        if entity.is_root and len(entities) == 1:
            for key in rest:
                found[key] = Owner(entity, DocumentRef(entity.root, key))
            break
        source = config.read_view or config.table
        by_view = config.read_view is not None
        pk = config.primary_key if by_view else (field_column(config, config.primary_key) or config.primary_key)
        columns = [pk]
        parent = None
        if entity.parent_key is not None:
            parent = entity.parent_key if by_view else (field_column(config, entity.parent_key) or entity.parent_key)
            columns.append(parent)
        for start in range(0, len(rest), 1000):
            statement, binds = keys_sql(source, pk, rest[start:start + 1000], columns)
            for row in sql.rows(uow, statement, binds):
                key = key_text(row[pk.upper()])
                if key in found:
                    continue
                record = key if parent is None else key_text(row[parent.upper()])
                found[key] = Owner(entity, DocumentRef(entity.root, record))
    return found


def registered(catalog: ApprovalCatalog, table: str) -> bool:
    return bool(catalog.entities_on_table(table))


def require_key_column(column: str | None, where: str) -> str:
    if column is None:
        raise PlatformError(ErrorCode.INTERNAL_ERROR, f"{where} 没有单列主键，无法确定修改表的主键")
    return column


def first_text(values: Mapping[str, Value], names: Iterable[str]) -> str | None:
    for name in names:
        value = values.get(name)
        if isinstance(value, str) and value:
            return value
    return None
