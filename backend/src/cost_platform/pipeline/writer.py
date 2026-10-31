"""写入变更（架构第 7 节第 9 步，WP-06、WP-09）：按变更计划写业务表，只写有变化的列。

提交审批的单据（`CommandState.pending_documents`）整张不写（approval AP-01）。顺序：
1. 新增的主表行（取得主键后填进它的新增明细的关联字段）；
2. 删除的主表行先按关联字段删除它的全部明细，每张明细表一条语句；
3. 明细的删除、修改、新增；
4. 主表行的修改；
5. 主表行的删除。
同一实体的同一种操作按写入的列分组，每组一条批量语句；主表写 0 或 1 条语句（每张单据）。

实体配了 `updatedByColumn`（C06 第 2 节）时，新增、修改的行在同一条语句里另写这一列为当前用户的登录名（WP-20），
不多出语句；它不是实体字段，不进命令结果和审计差异。配了 `createdByColumn`（C06 v28）时，新增的行同样另写这一列，
修改不写（同旧系统 DynamicDataService.java 的 insert 写 CREATE_BY、update 不写）。
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Callable

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import CommandState, DocumentRef, EntityConfig, EntityField, ExecutionContext, RowChange
from cost_platform.contracts.values import from_wire

from .document_store import RowStore

UPDATED_BY = "@updatedBy"
"""写给 `RowStore` 的修改人字段名：不是实体字段，只在写入时加到实体和变更计划的副本上。"""
CREATED_BY = "@createdBy"
"""写给 `RowStore` 的创建人字段名，同 `UPDATED_BY`，只用于新增。"""

Write = Callable[[UnitOfWork, EntityConfig, list[RowChange]], None]


def _is_master(change: RowChange) -> bool:
    return change.entity == change.document.entity


def _stamped(entity: EntityConfig, changes: list[RowChange], username: str,
             adding: bool) -> tuple[EntityConfig, list[RowChange]]:
    """WP-20：实体配了 `updatedByColumn`（新增、修改）或 `createdByColumn`（只新增）时，返回带这些字段的实体副本和
    变更计划副本（每行加上当前用户的登录名）；都没配时原样返回。同旧系统 DynamicDataService.java 的 insert 写
    CREATE_BY、UPDATE_BY，update 写 UPDATE_BY，值为当前用户名。"""
    extras = []
    if entity.updated_by_column is not None:
        extras.append(EntityField(name=UPDATED_BY, column=entity.updated_by_column, label="修改人", type="text",
                                  source="own", role="system"))
    if adding and entity.created_by_column is not None:
        extras.append(EntityField(name=CREATED_BY, column=entity.created_by_column, label="创建人", type="text",
                                  source="own", role="system"))
    if not extras:
        return entity, changes
    target = entity.model_copy(update={"fields": [*entity.fields, *extras]})
    stamp = {f.name: username for f in extras}
    return target, [dataclasses.replace(c, values={**c.values, **stamp}) for c in changes]


def _write_stamped(write: Write, uow: UnitOfWork, entity: EntityConfig, changes: list[RowChange], username: str,
                   adding: bool) -> None:
    """新增、修改：按 `_stamped` 写；新增行取得的主键写回原来的 `RowChange`。"""
    target, rows = _stamped(entity, changes, username, adding)
    write(uow, target, rows)
    for original, written in zip(changes, rows, strict=True):
        original.row_key = written.row_key


class ChangeWriter:
    def __init__(self, store: RowStore) -> None:
        self._store = store

    def apply(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        """写入 `changes` 中不属于提交审批的单据的行。新增行取得的主键写回 `RowChange.row_key` 和候选数据，
        `RowChange.document` 改为取得主键后的单据。"""
        plan = [c for c in state.changes.rows if c.document not in state.pending_documents]
        if not plan:
            return
        entity = ctx.config.entity

        def by_entity(changes: list[RowChange]) -> dict[str, list[RowChange]]:
            groups: dict[str, list[RowChange]] = defaultdict(list)
            for change in changes:
                groups[change.entity].append(change)
            return groups

        masters = [c for c in plan if _is_master(c)]
        details = [c for c in plan if not _is_master(c)]
        username = ctx.identity.username
        for code, group in by_entity([c for c in masters if c.op == "add"]).items():
            _write_stamped(self._store.insert, uow, entity(code), group, username, adding=True)
            for change in group:
                self._master_added(state, ctx, change, plan)

        removed = {c.document for c in masters if c.op == "delete"}
        cascades: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        for ref in sorted(removed, key=lambda r: (r.entity, r.record_key)):
            for link in entity(ref.entity).details:
                detail = entity(link.entity)
                cascades[(link.entity, detail.table.upper(), link.parent_key)].append(ref.record_key)
        done: set[tuple[str, str]] = set()
        for (code, table, parent_key), keys in cascades.items():
            column = next(f.column for f in entity(code).fields if f.name == parent_key) or parent_key
            if (table, column.upper()) in done:
                continue  # 两个明细实体是同一张表（例如原辅料、包材都在 T_COST_PINGGU_DTL）：只删一次
            done.add((table, column.upper()))
            self._store.delete_children(uow, entity(code), parent_key, keys)

        kept = [c for c in details if c.document not in removed]
        for op, write in (("delete", self._store.delete), ("modify", self._store.update), ("add", self._store.insert)):
            for code, group in by_entity([c for c in kept if c.op == op]).items():
                if op == "delete":
                    write(uow, entity(code), group)
                else:
                    _write_stamped(write, uow, entity(code), group, username, adding=op == "add")
                if op == "add":
                    for change in group:
                        self._detail_added(state, ctx, change)
        for op, write in (("modify", self._store.update), ("delete", self._store.delete)):
            for code, group in by_entity([c for c in masters if c.op == op]).items():
                if op == "delete":
                    write(uow, entity(code), group)
                else:
                    _write_stamped(write, uow, entity(code), group, username, adding=False)

    @staticmethod
    def _master_added(state: CommandState, ctx: ExecutionContext, change: RowChange, plan: list[RowChange]) -> None:
        old_ref = change.document
        key = change.row_key or ""
        new_ref = DocumentRef(old_ref.entity, key)
        entity = ctx.config.entity(old_ref.entity)
        pk = next(f for f in entity.fields if f.name == entity.primary_key)
        doc = state.candidate.get(old_ref)
        if doc is not None:
            doc.master.row_key = key
            doc.master.values[pk.name] = from_wire(pk.type, key)
        links = {link.entity: link.parent_key for link in entity.details}
        for other in plan:
            if other.document != old_ref:
                continue
            other.document = new_ref
            if other is change or other.entity not in links:
                continue
            parent_key = links[other.entity]
            parent = next(f for f in ctx.config.entity(other.entity).fields if f.name == parent_key)
            other.values[parent_key] = from_wire(parent.type, key)
            if doc is not None:
                row = next((r for r in doc.details.get(other.entity, []) if r.client_row_id == other.client_row_id), None)
                if row is not None:
                    row.values[parent_key] = other.values[parent_key]
        if doc is not None:
            doc.ref = new_ref
            state.candidate[new_ref] = state.candidate.pop(old_ref)
        state.involved[:] = [new_ref if r == old_ref else r for r in state.involved]

    @staticmethod
    def _detail_added(state: CommandState, ctx: ExecutionContext, change: RowChange) -> None:
        entity = ctx.config.entity(change.entity)
        pk = next(f for f in entity.fields if f.name == entity.primary_key)
        for doc in state.candidate.values():
            for row in doc.details.get(change.entity, []):
                if row.client_row_id is not None and row.client_row_id == change.client_row_id:
                    row.row_key = change.row_key
                    row.values[pk.name] = from_wire(pk.type, change.row_key)
                    return
