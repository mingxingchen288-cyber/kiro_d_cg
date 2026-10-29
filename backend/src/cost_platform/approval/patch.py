"""待审修改（AP-01、AP-02）：提交时给新增行取主键，把修改合并到当前数据上（详情和最终批准用），以及最终批准时展开为
写入意图交给 write-pipeline（AP-10，C08 第 6 节 `RowIntent`）。

待审修改就是本命令中这张单据的 `DocumentPatch`（C02 第 1 节），新增行的临时编号对应提交时取得的主键（`key_map`）。
对照旧系统 `ConfiguredApprovalRuntime.reserveNewIds`（送审时按序列给新增行取号）和 `applyPending`（批准时按快照应用）。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from decimal import Decimal

from cost_platform.contracts.ports import ConfigSnapshot, UnitOfWork
from cost_platform.contracts.types import (
    DetailAdd,
    DetailDelete,
    DetailModify,
    DocumentData,
    DocumentPatch,
    DocumentRef,
    EntityConfig,
    FieldValues,
    MasterAdd,
    MasterDelete,
    MasterModify,
    Row,
    RowIntent,
    RowOp,
    Value,
)
from cost_platform.contracts.values import from_wire

from .sql import KeyAllocator


def patch_ref(patch: DocumentPatch) -> DocumentRef:
    """命令中这张单据的引用：新增的单据在取得主键前为主表行的临时编号（C08 `RowChange.document`）。"""
    master = patch.master
    return DocumentRef(patch.entity, master.client_row_id if isinstance(master, MasterAdd) else master.row_key)


def assign_keys(uow: UnitOfWork, keys: KeyAllocator, config: ConfigSnapshot, patch: DocumentPatch) -> dict[str, str]:
    """等待审批的新增行在提交时从序列 `<表名>_SEQ` 取得正式主键（AP-02）。"""
    found: dict[str, str] = {}
    if isinstance(patch.master, MasterAdd):
        found[patch.master.client_row_id] = keys.next_key(uow, config.entity(patch.entity).table)
    for detail in patch.details:
        if isinstance(detail, DetailAdd):
            found[detail.client_row_id] = keys.next_key(uow, config.entity(detail.entity).table)
    return found


def bill_key(patch: DocumentPatch, key_map: dict[str, str]) -> str:
    master = patch.master
    return key_map[master.client_row_id] if isinstance(master, MasterAdd) else master.row_key


def values_of(entity: EntityConfig, wire: FieldValues) -> dict[str, Value]:
    types = {f.name: f.type for f in entity.fields}
    return {name: from_wire(types[name], value) for name, value in wire.items() if name in types}


def key_value(entity: EntityConfig, key: str) -> Value:
    field_type = next((f.type for f in entity.fields if f.name == entity.primary_key), "text")
    return Decimal(key) if field_type == "number" else key


@dataclass(frozen=True)
class Change:
    """待审修改中的一行：求值请求的 `changed`（C07 第 2 节）。"""

    entity: str
    row_key: str
    op: RowOp
    fields: tuple[str, ...]
    old: dict[str, Value]


@dataclass
class Applied:
    """当前数据加上待审修改（还没有计算）；删除的行另外列出（求值请求中仍放在单据里，C07 第 2 节）。"""

    document: DocumentData
    changes: list[Change] = field(default_factory=list)
    deleted: list[Row] = field(default_factory=list)
    master_deleted: bool = False


def apply_patch(current: DocumentData | None, patch: DocumentPatch, key_map: dict[str, str], config: ConfigSnapshot) -> Applied:
    master_entity = config.entity(patch.entity)
    key = bill_key(patch, key_map)
    ref = DocumentRef(patch.entity, key)
    parent_keys = {link.entity: link.parent_key for link in master_entity.details}
    if current is None:
        document = DocumentData(ref=ref, master=Row(patch.entity, key, None, {}), details={l.entity: [] for l in master_entity.details})
    else:
        document = copy.deepcopy(current)
        document.ref = ref
    applied = Applied(document)
    master = patch.master
    if isinstance(master, MasterAdd):
        values = {**values_of(master_entity, master.values), master_entity.primary_key: key_value(master_entity, key)}
        document.master = Row(patch.entity, key, master.client_row_id, values)
        applied.changes.append(Change(patch.entity, key, "add", tuple(values), {}))
    elif isinstance(master, MasterModify):
        values = values_of(master_entity, master.changes)
        old = {k: document.master.values.get(k) for k in values}
        document.master.values.update(values)
        applied.changes.append(Change(patch.entity, key, "modify", tuple(values), old))
    elif isinstance(master, MasterDelete):
        applied.master_deleted = True
        applied.deleted.append(copy.deepcopy(document.master))
        applied.changes.append(Change(patch.entity, key, "delete", (), dict(document.master.values)))
        for code, rows in document.details.items():
            applied.deleted += rows
            applied.changes += [Change(code, r.row_key or "", "delete", (), dict(r.values)) for r in rows]
            document.details[code] = []
    master_key = document.master.values.get(master_entity.primary_key, key_value(master_entity, key))
    for detail in patch.details:
        entity = config.entity(detail.entity)
        rows = document.details.setdefault(detail.entity, [])
        if isinstance(detail, DetailAdd):
            row_key = key_map[detail.client_row_id]
            values = {**values_of(entity, detail.values), entity.primary_key: key_value(entity, row_key),
                      parent_keys[detail.entity]: master_key}
            rows.append(Row(detail.entity, row_key, detail.client_row_id, values))
            applied.changes.append(Change(detail.entity, row_key, "add", tuple(values), {}))
            continue
        row = next((r for r in rows if r.row_key == detail.row_key), None)
        if row is None:  # 行已不存在：按 write-pipeline 的 rowNotFound 处理，这里只是不显示
            continue
        if isinstance(detail, DetailModify):
            values = values_of(entity, detail.changes)
            old = {k: row.values.get(k) for k in values}
            row.values.update(values)
            applied.changes.append(Change(detail.entity, detail.row_key, "modify", tuple(values), old))
        elif isinstance(detail, DetailDelete):
            rows.remove(row)
            applied.deleted.append(row)
            applied.changes.append(Change(detail.entity, detail.row_key, "delete", (), dict(row.values)))
    return applied


def patch_intents(patch: DocumentPatch, key_map: dict[str, str], config: ConfigSnapshot) -> list[RowIntent]:
    """最终批准时，待审修改展开为写入意图（AP-10 第一步）：新增行用提交时取得的主键（`row_key`），审批通过时用它写入
    （WP-09）。主表为 `none` 时只有明细的意图。"""
    master_entity = config.entity(patch.entity)
    key = bill_key(patch, key_map)
    ref = DocumentRef(patch.entity, key)
    parent_keys = {link.entity: link.parent_key for link in master_entity.details}
    intents: list[RowIntent] = []
    master = patch.master
    if isinstance(master, MasterAdd):
        intents.append(RowIntent(ref, patch.entity, "add", key, master.client_row_id, values_of(master_entity, master.values)))
    elif isinstance(master, MasterModify):
        intents.append(RowIntent(ref, patch.entity, "modify", key, None, values_of(master_entity, master.changes)))
    elif isinstance(master, MasterDelete):
        intents.append(RowIntent(ref, patch.entity, "delete", key, None, {}))
    master_key = key_value(master_entity, key)
    for detail in patch.details:
        entity = config.entity(detail.entity)
        if isinstance(detail, DetailAdd):
            values = {**values_of(entity, detail.values), parent_keys[detail.entity]: master_key}
            intents.append(RowIntent(ref, detail.entity, "add", key_map[detail.client_row_id], detail.client_row_id, values))
        elif isinstance(detail, DetailModify):
            intents.append(RowIntent(ref, detail.entity, "modify", detail.row_key, None, values_of(entity, detail.changes)))
        elif isinstance(detail, DetailDelete):
            intents.append(RowIntent(ref, detail.entity, "delete", detail.row_key, None, {}))
    return intents
