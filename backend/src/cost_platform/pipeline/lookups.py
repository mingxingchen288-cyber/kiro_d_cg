"""计算前按 Lookup 带出没有物理列的字段（WP-08 求值的准备）。

名称这类字段没有物理列（`column` 为 null，C06 第 2 节），已有的行由读取视图带出；新增的行、换了 Lookup 字段值的行
（例如换了物料）库里还没有，前端也不提交，求值时就是空的，例如原辅料的每批数量按物料名称和分类取公式。用户 2026-10-29：
"只要有物料ID即可，就可以通过视图带出来"。

求值前，这些行按页面上这个字段的 Lookup（C06 第 3 节的 `fill`）用候选数据中的值查一次 Lookup 的表：
`SELECT <键列>, <回填列> FROM <Lookup 的 table> WHERE <键列> IN (:k0, :k1, …)`，把回填字段中没有物理列的填进候选数据的行，
不进变更计划、不写库；有物理列的回填字段（例如单价）由前端按 Lookup 回填后提交。命令结果的行取自候选数据，前端能看到名称。
做法与审批详情相同（approval 的 `view._fill_lookups`）。

只处理带页面的命令（页面保存、页面上的按钮），按这个页面的页面视图找 Lookup；没有配置 Lookup 的字段不处理。
SQL 中的表名、列名来自已发布的配置（config 保存时已核对 Lookup 的表和列，C06 第 10 节），值用绑定变量。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import text

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import CommandState, EntityField, ExecutionContext, Row, RowChange, Value
from cost_platform.contracts.values import from_db, to_wire


@dataclass(frozen=True)
class LookupFill:
    """页面上一个配了 Lookup 的字段，以及它回填的、没有物理列的字段。"""

    entity: str
    field: EntityField
    """配了 Lookup 的字段（例如原辅料的 GOODSID）。"""
    table: str
    key_column: str
    """Lookup 中与这个字段对应的列（`fill[字段]`）。"""
    targets: dict[str, tuple[EntityField, str]]
    """没有物理列的回填字段 →（字段，Lookup 的列）。"""


def lookup_fills(ctx: ExecutionContext, page: str | None) -> list[LookupFill]:
    """页面视图中配了 Lookup、并且回填没有物理列的字段的那些字段。"""
    if page is None:
        return []
    view = ctx.config.page_view(page)
    found = []
    for area in [view.master, *view.details]:
        fields = {f.name: f for f in ctx.config.entity(area.entity).fields}
        for view_field in area.fields:
            setting = view_field.lookup
            if setting is None or view_field.name not in setting.fill:
                continue
            targets = {name: (fields[name], column) for name, column in setting.fill.items()
                       if name in fields and fields[name].column is None}
            lookup = ctx.config.lookup(setting.code)
            if targets and lookup is not None:
                found.append(LookupFill(area.entity, fields[view_field.name], lookup.table, setting.fill[view_field.name], targets))
    return found


def lookup_keys_read_by_rules(ctx: ExecutionContext, page: str | None,
                              used: Mapping[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    """各实体中这样的 Lookup 字段：它回填的、没有物理列的字段有规则读取（`ConfigSnapshot.rule_fields`）。改了这种字段
    也要求值，例如只换了物料、单价没变时，每批数量仍要按新的物料名称重算。"""
    keys: dict[str, set[str]] = {}
    for fill in lookup_fills(ctx, page):
        if set(fill.targets) & used.get(fill.entity, frozenset()):
            keys.setdefault(fill.entity, set()).add(fill.field.name)
    return {entity: frozenset(names) for entity, names in keys.items()}


def _candidate_row(state: CommandState, change: RowChange) -> Row | None:
    doc = state.candidate.get(change.document)
    if doc is None:
        return None
    key = change.client_row_id or change.row_key
    rows = [doc.master, *(r for rows in doc.details.values() for r in rows)]
    return next((r for r in rows if r.entity == change.entity and key in (r.client_row_id, r.row_key)), None)


def _key(field: EntityField, value: Value) -> str:
    return str(to_wire(field.type, value))


def fill_lookup_fields(uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
    """新增的行、Lookup 字段的值有变化的行，按 Lookup 查出没有物理列的回填字段，填进候选数据（见模块说明）。"""
    for fill in lookup_fills(ctx, state.command.page):
        pending: dict[str, list[Row]] = {}
        for change in state.changes.rows:
            if change.entity != fill.entity or change.op == "delete":
                continue
            if change.op == "modify" and fill.field.name not in change.values:
                continue
            row = _candidate_row(state, change)
            value = row.values.get(fill.field.name) if row is not None else None
            if row is not None and value is not None:
                pending.setdefault(_key(fill.field, value), []).append(row)
        if not pending:
            continue
        columns = list(dict.fromkeys([fill.key_column, *(column for _, column in fill.targets.values())]))
        names = [f"k{i}" for i in range(len(pending))]
        sql = f"SELECT {', '.join(columns)} FROM {fill.table} WHERE {fill.key_column} IN ({', '.join(':' + n for n in names)})"
        for record in uow.connection.execute(text(sql), dict(zip(names, pending, strict=True))):
            found = dict(zip(columns, record, strict=True))
            for row in pending.get(_key(fill.field, from_db(fill.field.type, found[fill.key_column])), []):
                for name, (target, column) in fill.targets.items():
                    row.values[name] = from_db(target.type, found[column])
