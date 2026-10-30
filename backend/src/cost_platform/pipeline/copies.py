"""复制出的行的源行（C02 第 1 节 `copyOf`，WP-21）。

旧系统复制源行的全部字段（只排除主键，`copy-row-fields.ts` 第 23–29 行），新增行提交全部字段（`useWorkingSetStore.ts`
第 834–876 行），后端插入只跳过虚拟列（`DynamicDataService.java` 第 274–327 行），所以不可编辑的字段（例如成本单的币种、
项目号）也复制到新单据。新平台照做，但不信前端给的值：命令中写明复制自哪一行（`copyOf`，同一实体的主键），合并修改前
按主键另读这些源行（不加锁，每个实体一条语句），本行不可写的复制字段取源行的值（`merge._Rows.new_values`）。

源行按用户能读的范围读取：主表实体加上角色的行权限条件，明细实体要求它所属的主表行满足行权限（同 queries 的按主键取行）；
读不到（已删除或超出行权限）时整个命令返回 409 ROW_NOT_FOUND。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy import text

from cost_platform.contracts.ports import PermissionChecker, UnitOfWork
from cost_platform.contracts.types import (
    CommandState,
    DetailAdd,
    EntityConfig,
    EntityField,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    MasterAdd,
    PlatformError,
    Value,
)
from cost_platform.contracts.values import from_db, from_wire, to_wire

SourceKey = tuple[str, str]
"""（实体，主键文本）。"""
SourceRows = Mapping[SourceKey, dict[str, Value]]


class CopySources(Protocol):
    """读复制出的行的源行；`MergePatchesStage` 在合并修改前调用。"""

    def read(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> SourceRows: ...


def wanted_sources(state: CommandState) -> tuple[dict[str, set[str]], dict[str, str]]:
    """命令中复制出的行要读的源行（实体 → 主键），以及明细实体所属的主表实体。"""
    wanted: dict[str, set[str]] = defaultdict(set)
    masters: dict[str, str] = {}
    for patch in state.command.documents:
        if isinstance(patch.master, MasterAdd) and patch.master.copy_of:
            wanted[patch.entity].add(patch.master.copy_of)
        for detail in patch.details:
            if isinstance(detail, DetailAdd) and detail.copy_of:
                wanted[detail.entity].add(detail.copy_of)
                masters[detail.entity] = patch.entity
    return wanted, masters


def source_of(sources: SourceRows, entity: str, copy_of: str | None) -> dict[str, Value] | None:
    """复制出的行的源行；不是复制出的行为 None；源行读不到时 409 ROW_NOT_FOUND。"""
    if copy_of is None:
        return None
    found = sources.get((entity, copy_of))
    if found is None:
        raise PlatformError(ErrorCode.ROW_NOT_FOUND, "复制的源行已不存在或超出行权限",
                            [ErrorDetail(message="复制的源行读不到", entity=entity, row_key=copy_of)])
    return found


def _layout(entity: EntityConfig) -> tuple[str, list[tuple[EntityField, str]]]:
    """读取的表或视图，以及每个字段在其中的列：有 readView 时经视图按字段名读，否则按 `column` 读表（C06 第 2 节）。"""
    if entity.read_view:
        return entity.read_view, [(f, f.name) for f in entity.fields]
    return entity.table, [(f, str(f.column)) for f in entity.fields if f.column]


class OracleCopySources:
    """按主键读源行，每个实体一条 SELECT，不加锁；行权限条件的写法同 queries 的按主键取行。"""

    def __init__(self, permission: PermissionChecker) -> None:
        self._permission = permission

    def read(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> SourceRows:
        wanted, masters = wanted_sources(state)
        page = state.command.page
        found: dict[SourceKey, dict[str, Value]] = {}
        for code in sorted(wanted):
            entity = ctx.config.entity(code)
            source, columns = _layout(entity)
            column_of = dict((f.name, c) for f, c in columns)
            pk = next(f for f in entity.fields if f.name == entity.primary_key)
            binds: dict[str, Any] = {}
            names = []
            for i, key in enumerate(sorted(wanted[code])):
                binds[f"cp{i}"] = from_wire(pk.type, key)
                names.append(f":cp{i}")
            clauses = [f"x.{column_of[pk.name]} IN ({', '.join(names)})"]
            master_code = masters.get(code, code)
            condition = None
            if ctx.origin.kind == "user" and page is not None:
                condition = self._permission.row_condition(ctx, page, master_code)
            if condition is not None:
                binds.update(condition.binds)
                if master_code == code:
                    clauses.append(condition.sql)
                else:
                    master = ctx.config.entity(master_code)
                    master_source, master_columns = _layout(master)
                    master_pk = dict((f.name, c) for f, c in master_columns)[master.primary_key]
                    parent_key = next(link.parent_key for link in master.details if link.entity == code)
                    clauses.append(f"EXISTS (SELECT 1 FROM {master_source} a WHERE a.{master_pk} = x.{column_of[parent_key]} "
                                   f"AND {condition.sql})")
            select = ", ".join(f"x.{c}" for _, c in columns)
            sql = f"SELECT {select} FROM {source} x WHERE {' AND '.join(clauses)}"
            for record in uow.connection.execute(text(sql), binds):
                values = {f.name: from_db(f.type, raw) for (f, _), raw in zip(columns, record, strict=True)}
                found[(code, str(to_wire(pk.type, values[pk.name])))] = values
        return found
