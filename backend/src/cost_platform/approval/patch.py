"""待审修改（AP-01、AP-02）：提交时给新增行取主键，把修改合并到当前数据上（详情和最终批准用），以及最终批准时展开为
写入意图交给 write-pipeline（AP-10，C08 第 6 节 `RowIntent`）。

待审修改就是本命令中这张单据的 `DocumentPatch`（C02 第 1 节），新增行的临时编号对应提交时取得的主键（`key_map`）。
复制出的行（`copyOf`）的值换成提交那一刻 write-pipeline 按源行解出的值（`resolved_patch`）。
对照旧系统 `ConfiguredApprovalRuntime.reserveNewIds`（送审时按序列给新增行取号）和 `applyPending`（批准时按快照应用）。
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
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
    RowChange,
    RowIntent,
    RowOp,
    Value,
)
from cost_platform.contracts.values import from_wire, to_wire

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


def _insertable(entity: EntityConfig, parent_key: str | None) -> set[str]:
    """新增行能写进表的字段：C02 第 1 节、C06 第 2 节中不可写的字段（主键、主从关联字段、`erpRow.column`、计算字段、
    只在视图中的字段、没有 `erpRow` 的实体的 ERP 列）以外的字段。"""
    erp = entity.erp_row
    erp_names = {f.name for f in entity.fields if erp is not None and erp.column in (f.name, f.column)}
    return {f.name for f in entity.fields
            if f.column is not None and f.role != "calculated" and f.name not in {entity.primary_key, parent_key, *erp_names}
            and not (f.source == "erp" and erp is None)}


def resolved_patch(patch: DocumentPatch, changes: Sequence[RowChange], config: ConfigSnapshot) -> DocumentPatch:
    """要存为待审修改的 Patch：复制出的行（`copyOf`，C02 第 1 节、write-pipeline WP-21）的值换成提交这一刻 write-pipeline
    按源行解出的值，其余原样。

    触发审批在合并、计算之后执行，`changes` 中新增行的值 = 合并时解出的值（可写的取命令中的值，不可写、可见、能写进表的
    取源行的值，没复制的字段不在其中）+ 关联字段、`erpRow.column` + 计算带出的计算字段。这里只留能写进表的字段
    （`_insertable`），即合并时解出的那部分；关联字段和 `erpRow.column` 在最终通过时由 write-pipeline 照常填上。
    审批详情（`apply_patch`）显示的、最终通过（`patch_intents`）写入的都是这些值，不在通过时再读源行：源行在审批期间
    可能被改，旧系统复制在复制那一刻就取定了值，送审时随待审数据存下（`ConfiguredApprovalRuntime` 的 `records.patch`、
    `applyPending`）。"""
    master = patch.master
    copies = isinstance(master, MasterAdd) and master.copy_of is not None or any(
        isinstance(d, DetailAdd) and d.copy_of is not None for d in patch.details)
    if not copies:
        return patch
    added = {(c.entity, c.client_row_id): c for c in changes if c.op == "add" and c.client_row_id is not None}
    parent_keys = {link.entity: link.parent_key for link in config.entity(patch.entity).details}

    def resolve(code: str, client_row_id: str, values: FieldValues) -> FieldValues:
        change = added.get((code, client_row_id))
        if change is None:
            return values
        entity = config.entity(code)
        types = {f.name: f.type for f in entity.fields}
        keep = _insertable(entity, parent_keys.get(code))
        return {name: to_wire(types[name], value) for name, value in change.values.items() if name in keep}

    if isinstance(master, MasterAdd) and master.copy_of is not None:
        master = master.model_copy(update={"values": resolve(patch.entity, master.client_row_id, master.values)})
    details = [d.model_copy(update={"values": resolve(d.entity, d.client_row_id, d.values)})
               if isinstance(d, DetailAdd) and d.copy_of is not None else d for d in patch.details]
    return patch.model_copy(update={"master": master, "details": details})


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
    （WP-09）。复制出的行带上 `copy_of`：值是提交时解出的（`resolved_patch`），write-pipeline 不补默认值。
    主表为 `none` 时只有明细的意图。"""
    master_entity = config.entity(patch.entity)
    key = bill_key(patch, key_map)
    ref = DocumentRef(patch.entity, key)
    parent_keys = {link.entity: link.parent_key for link in master_entity.details}
    intents: list[RowIntent] = []
    master = patch.master
    if isinstance(master, MasterAdd):
        intents.append(RowIntent(ref, patch.entity, "add", key, master.client_row_id, values_of(master_entity, master.values),
                                 copy_of=master.copy_of))
    elif isinstance(master, MasterModify):
        intents.append(RowIntent(ref, patch.entity, "modify", key, None, values_of(master_entity, master.changes)))
    elif isinstance(master, MasterDelete):
        intents.append(RowIntent(ref, patch.entity, "delete", key, None, {}))
    master_key = key_value(master_entity, key)
    for detail in patch.details:
        entity = config.entity(detail.entity)
        if isinstance(detail, DetailAdd):
            values = {**values_of(entity, detail.values), parent_keys[detail.entity]: master_key}
            intents.append(RowIntent(ref, detail.entity, "add", key_map[detail.client_row_id], detail.client_row_id, values,
                                     copy_of=detail.copy_of))
        elif isinstance(detail, DetailModify):
            intents.append(RowIntent(ref, detail.entity, "modify", detail.row_key, None, values_of(entity, detail.changes)))
        elif isinstance(detail, DetailDelete):
            intents.append(RowIntent(ref, detail.entity, "delete", detail.row_key, None, {}))
    return intents
