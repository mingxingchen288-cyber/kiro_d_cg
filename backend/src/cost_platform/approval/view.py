"""审批详情的"修改内容"（C06 7.5、7.6，C09 第 6 节的 `view`）、结果指纹（AP-08），以及最终批准时受影响单据要写的值（AP-10）。

- 来源单据：当前数据（`DocumentReader`，不加锁）加全部待审修改，按计算规则重算，得到修改后。
- 受影响单据：修改前是数据库中的当前值（按修改表的主键从展示表或视图读出）；修改后取勾选的行要写的值（取值按 C06 7.2
  执行），修改表注册过时再按所属页面的计算规则重算这一行所属的单据（包括 `master.` 列）；按 `targetColumn` 对应不上
  修改表的列（视图自己算出来的列）只显示当前值。
- 指纹：`view` 去掉只和当前用户有关的 `editable` 后取 SHA-256；通过时按提交的勾选再算一遍，不一致返回 409 RECONFIRM_REQUIRED。

对照旧系统 `ApprovalPresentationService`、`ApprovalCostPreviewService`（审批对象按写入字段算出待写值，按所属成本单整单试算）。
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from cost_platform.contracts.decimal_text import format_decimal
from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    ApprovalView,
    BusinessValue,
    DeleteRows,
    DisplayBlock,
    DisplayColumn,
    DocumentData,
    DocumentRef,
    EntityConfig,
    EscapeHatch,
    ExecutionContext,
    FlowParam,
    InsertRows,
    MasterAdd,
    MasterDelete,
    MasterModify,
    Row,
    RowRef,
    UpdateFields,
    Value,
    ViewAffectedTable,
    ViewCell,
    ViewDetailTable,
    ViewMasterTable,
    ViewRow,
    dump_wire,
)

from .calc import Recalculator, coerce
from .catalog import ApprovalCatalog
from .deps import ApprovalDeps
from .model import AffectedRow, ApprovalRecord, FlowSnapshot
from .patch import Applied, Change, apply_patch, bill_key
from .routing import fingerprint
from .rows import Owner, column_field, find_row, owners
from .sql import RowScope, entry_sql, binds_for, key_text, keys_sql, params_in, scalar

# ============================================================ 单元格

def _round(value: Decimal, precision: int | None) -> Decimal:
    if precision is None:
        return value
    return value.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)


def cell(value: object, precision: int | None = None) -> BusinessValue:
    """显示用的值。数值有小数位 `precision` 时按它四舍五入并补足位数（75 → "75.00"，13.006532 → "13.0065"，C06 7.6；
    同旧系统 ApprovalPresentationGrid.vue 的 `toFixed(precision)`）；没有小数位时按原值，去掉末尾的零（75.00 → "75"）。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (Decimal, int, float)):
        number = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
        if precision is not None:
            return format_decimal(_round(number, precision))
        return format_decimal(number.normalize()) if number == number.to_integral_value() else format_decimal(number).rstrip("0").rstrip(".")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _same(a: BusinessValue, b: BusinessValue) -> bool:
    return a == b


# ============================================================ 来源单据

@dataclass
class SourceState:
    """来源单据：`before` 为当前数据（新增的单据为空），`after` 为加上全部待审修改并重算后的数据。"""

    before: DocumentData | None
    after: DocumentData
    applied: Applied


@dataclass
class Write:
    """受影响单据一行的一个操作（C06 7.5 的 `actions`）：`values` 为修改表的列 -> 要写的值。"""

    action: Literal["update", "insert", "delete", "escape"]
    table: str
    key: str | None
    key_column: str | None
    values: dict[str, Value] = field(default_factory=dict)
    operation: str | None = None


@dataclass
class RowPlan:
    """一个审批流一块中勾选的一行（`all`、`hidden` 为全部行）和它的操作，按 AP-10 的执行顺序排列。"""

    flow: FlowSnapshot
    block: DisplayBlock
    row: AffectedRow
    writes: list[Write]


@dataclass
class Computation:
    view: ApprovalView
    fingerprint: str
    source: SourceState
    scopes: dict[int, RowScope]
    plans: list[RowPlan]


def view_fingerprint(view: ApprovalView) -> str:
    data = dump_wire(ApprovalView, view)
    for block in data.get("affected", []):
        block.pop("editable", None)
    return fingerprint(data)


def typed(param: FlowParam, value: object) -> Value:
    if value is None or value == "":
        return None
    kind = {"string": "text", "number": "number", "boolean": "boolean", "date": "date"}[param.type]
    return coerce(kind, value)  # type: ignore[arg-type]


def manual_params(record: ApprovalRecord) -> dict[str, Any]:
    """各级和最终批准时已经填写的人工参数（AP-20：都保存下来，只在最终批准时由取值使用）。"""
    found: dict[str, Any] = {}
    for values in record.params.values():
        found.update(values)
    return found


# ============================================================ 计算

_Key = tuple[str, str]


def _columns(blocks: Iterable[DisplayBlock]) -> list[DisplayColumn]:
    """几个审批流的同一张表：列取并集，按审批流的 `order` 排列（C06 7.6）。"""
    found: dict[str, DisplayColumn] = {}
    for block in blocks:
        for column in block.columns:
            found.setdefault(column.field, column)
    return list(found.values())


class Evaluator:
    def __init__(self, deps: ApprovalDeps) -> None:
        self.deps = deps
        self.calc = Recalculator(deps.rules)

    # ---------------------------------------------------------------- 来源单据和触发行

    def source(self, ctx: ExecutionContext, record: ApprovalRecord, current: DocumentData | None = None) -> SourceState:
        """`current` 为调用方已读到的当前数据（最终批准的命令中为加锁读到的数据）；不给时经 `DocumentReader` 读取。"""
        before = current
        if before is None and not isinstance(record.patch.master, MasterAdd):
            before = self.deps.documents.load(record.source)
        applied = apply_patch(before, record.patch, record.key_map, ctx.config)
        after = self.calc.compute(ctx, applied, page=record.page, operation=record.operation, user_id=record.applicant_id,
                                  department_id=record.applicant_department)
        return SourceState(before, after, applied)

    def scopes(self, ctx: ExecutionContext, record: ApprovalRecord, source: SourceState) -> dict[int, RowScope]:
        """每个触发行的参数（C06 7.2）：`:new_` 取合并待审修改并计算后的值，`:old_` 取当前值。"""
        entity = ctx.config.entity(record.source.entity)
        master_new = {} if source.applied.master_deleted else dict(source.after.master.values)
        master_old = dict(source.before.master.values) if source.before is not None else {}
        bill = master_old.get(entity.primary_key) or master_new.get(entity.primary_key) or bill_key(record.patch, record.key_map)
        found: dict[int, RowScope] = {}
        for trigger in record.triggers:
            before = find_row(source.before, trigger.entity, trigger.row_key, None) if trigger.op != "add" else None
            after = find_row(source.after, trigger.entity, trigger.row_key, trigger.client_row_id) if trigger.op != "delete" else None
            found[trigger.id] = RowScope(trigger.op, dict(after.values) if after else {}, dict(before.values) if before else {},
                                         master_new, master_old, bill, record.applicant_id, record.applicant_department)
        return found

    def params(self, uow: UnitOfWork, flow: FlowSnapshot, scope: RowScope, manual: Mapping[str, Any]) -> dict[str, Value]:
        """审批流参数的值（C06 7.1）：`constant` 为常量，`expression` 由后端按这个触发行求值，`manual` 为审批人填写的。"""
        values: dict[str, Value] = {}
        for param in flow.config.params:
            if param.source == "constant":
                raw = param.value
            elif param.source == "expression":
                raw = scalar(self.deps.sql, uow, str(param.value), scope)
            else:
                raw = manual.get(param.name)
            values[param.name] = typed(param, raw)
        return values

    # ---------------------------------------------------------------- 受影响单据

    def key_column(self, block: DisplayBlock) -> str:
        found = block.key_column or self.deps.schema.primary_key(block.source)
        if found is None:
            raise ValueError(f"展示数据 {block.key} 没有 keyColumn，{block.source} 也没有单列主键")
        return found

    @staticmethod
    def target_table(block: DisplayBlock) -> str:
        return block.target_table or block.source

    def target_key_column(self, table: str, catalog: ApprovalCatalog) -> str:
        found = self.deps.schema.primary_key(table)
        if found is None:
            entity = next(iter(catalog.entities_on_table(table)), None)
            if entity is not None:
                found = next((f.column for f in entity.config.fields if f.name == entity.config.primary_key), None)
        if found is None:
            raise ValueError(f"修改表 {table} 没有单列主键")
        return found

    def rows_by_key(self, uow: UnitOfWork, source: str, column: str, keys: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        found: dict[str, list[dict[str, Any]]] = {}
        wanted = list(dict.fromkeys(keys))
        for start in range(0, len(wanted), 1000):
            statement, binds = keys_sql(source, column, wanted[start:start + 1000])
            for row in self.deps.sql.rows(uow, statement, binds):
                value = row.get(column.upper())
                if value is not None:
                    found.setdefault(key_text(value), []).append(row)
        return found

    def writes(self, uow: UnitOfWork, flow: FlowSnapshot, block: DisplayBlock, row: AffectedRow, scope: RowScope,
               target_row: Mapping[str, Value], manual: Mapping[str, Any], key_column: str) -> list[Write]:
        """这一行要执行的操作和要写的值；取值的参数取找到这一行的触发行和这一行的当前值（`:row_列名`）。"""
        local = scope.with_row(target_row, self.params(uow, flow, scope, manual))
        target = self.target_table(block)
        found: list[Write] = []
        for action in block.actions:
            if isinstance(action, UpdateFields):
                values = {f.column: scalar(self.deps.sql, uow, f.value, local) for f in action.fields}
                found.append(Write("update", target, row.key, key_column, values))
            elif isinstance(action, InsertRows):
                values = {f.column: scalar(self.deps.sql, uow, f.value, local) for f in action.fields}
                found.append(Write("insert", action.table, None, None, values))
            elif isinstance(action, DeleteRows):
                found.append(Write("delete", target, row.key, key_column))
            elif isinstance(action, EscapeHatch):
                found.append(Write("escape", target, row.key, key_column, operation=action.operation))
        return found

    def target_rows(self, uow: UnitOfWork, block: DisplayBlock, table: str, key_column: str,
                    keys: Sequence[str]) -> dict[str, dict[str, Any]]:
        """取值引用了 `:row_列名` 时，读出修改表这些行的当前值。"""
        uses_row = any(name.startswith("row_") for action in block.actions if isinstance(action, (UpdateFields, InsertRows))
                       for f in action.fields for name in params_in(f.value))
        if not uses_row or not keys:
            return {}
        return {k: rows[0] for k, rows in self.rows_by_key(uow, table, key_column, keys).items()}

    # ---------------------------------------------------------------- 整个审批

    def compute(self, uow: UnitOfWork, ctx: ExecutionContext, record: ApprovalRecord, affected: Sequence[AffectedRow], *,
                editable: set[_Key] | frozenset[_Key] = frozenset(), manual: Mapping[str, Any] | None = None,
                current: DocumentData | None = None) -> Computation:
        """按 `affected` 中每行的 `checked` 计算 `view`、指纹和要执行的操作。`manual` 为审批人填写的人工参数，默认取已保存的。"""
        catalog = self.deps.catalog(ctx)
        source = self.source(ctx, record, current)
        scopes = self.scopes(ctx, record, source)
        params = manual_params(record) if manual is None else manual

        # 1. 各块勾选的行要执行的操作（AP-10 的顺序：审批流按 order，块按 display 的顺序，行按找到的先后）
        plans: list[RowPlan] = []
        blocks: list[tuple[FlowSnapshot, DisplayBlock, list[AffectedRow], dict[str, list[dict[str, Any]]]]] = []
        for flow in record.flows:
            for block in flow.config.display:
                if block.region != "affected":
                    continue
                rows = sorted((a for a in affected if a.flow == flow.code and a.block == block.key), key=lambda a: a.seq)
                key_column = self.key_column(block)
                target = self.target_table(block)
                present = [a for a in rows if not a.missing and a.key is not None]
                current_rows = self.rows_by_key(uow, block.source, key_column, [a.key for a in present])  # type: ignore[misc]
                chosen = [a for a in present if block.selection in ("all", "hidden") or a.checked]
                target_key = self.target_key_column(target, catalog) if chosen else key_column
                targets = self.target_rows(uow, block, target, target_key, [a.key for a in chosen])  # type: ignore[misc]
                for row in chosen:
                    scope = scopes[row.triggers[0]]
                    plans.append(RowPlan(flow, block, row, self.writes(uow, flow, block, row, scope, targets.get(row.key or "", {}),
                                                                       params, target_key)))
                blocks.append((flow, block, rows, current_rows))

        # 2. 注册过的修改表：按"表 + 主键"找出所属单据，勾选的行要写的值合在一起，按所属页面的计算规则重算
        owner_of: dict[tuple[str, str], Owner] = {}
        by_table: dict[str, list[str]] = {}
        for plan in plans:
            for write in plan.writes:
                if write.action in ("update", "delete") and write.key is not None and catalog.entities_on_table(write.table):
                    by_table.setdefault(write.table, []).append(write.key)
        for flow, block, rows, _ in blocks:
            table = self.target_table(block)
            if catalog.entities_on_table(table) and any(c.field.startswith("master.") for c in block.columns):
                by_table.setdefault(table, []).extend(a.key for a in rows if not a.missing and a.key is not None)
        for table, keys in by_table.items():
            for key, owner in owners(self.deps.sql, uow, catalog, table, keys).items():
                owner_of[(table.upper(), key)] = owner
        docs = sorted({o.document for o in owner_of.values()}, key=lambda r: (r.entity, r.record_key))
        before_docs = self.deps.documents.load_many(docs) if docs else {}
        after_docs = self._recompute(ctx, record, plans, owner_of, before_docs)

        # 3. 修改内容
        master, details = self._source_tables(uow, ctx, record, source, scopes)
        affected_tables = []
        plan_of = {(p.flow.code, p.block.key, p.row.seq): p for p in plans}
        for flow, block, rows, current_rows in blocks:
            if block.selection == "hidden":
                continue
            affected_tables.append(self._affected_table(ctx, catalog, flow, block, rows, current_rows, plan_of, owner_of,
                                                        before_docs, after_docs, (flow.code, block.key) in editable,
                                                        len(record.flows) > 1))
        view = ApprovalView(master=master, details=details, affected=affected_tables)
        return Computation(view=view, fingerprint=view_fingerprint(view), source=source, scopes=scopes, plans=plans)

    def _recompute(self, ctx: ExecutionContext, record: ApprovalRecord, plans: Sequence[RowPlan],
                   owner_of: Mapping[tuple[str, str], Owner], before_docs: Mapping[DocumentRef, DocumentData]) -> dict[DocumentRef, DocumentData]:
        changes: dict[DocumentRef, Applied] = {}
        for plan in plans:
            for write in plan.writes:
                owner = owner_of.get((write.table.upper(), write.key or ""))
                if owner is None or owner.document not in before_docs or write.action not in ("update", "delete"):
                    continue
                applied = changes.setdefault(owner.document, Applied(copy.deepcopy(before_docs[owner.document])))
                doc = applied.document
                row = find_row(doc, owner.entity.code, write.key, None)
                if row is None:
                    continue
                if write.action == "delete":
                    if owner.entity.is_root:
                        applied.master_deleted = True
                    else:
                        doc.details[owner.entity.code].remove(row)
                        applied.deleted.append(row)
                    applied.changes.append(Change(owner.entity.code, write.key or "", "delete", (), dict(row.values)))
                    continue
                types = {f.name: f.type for f in owner.entity.config.fields}
                values = {}
                for column, value in write.values.items():
                    name = column_field(owner.entity.config, column)
                    if name is not None:
                        values[name] = coerce(types[name], value)
                old = {k: row.values.get(k) for k in values}
                row.values.update(values)
                applied.changes.append(Change(owner.entity.code, write.key or "", "modify", tuple(values), old))
        return {ref: self.calc.compute(ctx, applied, page=None, operation=None, user_id=record.applicant_id,
                                       department_id=record.applicant_department) for ref, applied in changes.items()}

    # ---------------------------------------------------------------- 来源单据的表格

    def _fill_lookups(self, uow: UnitOfWork, ctx: ExecutionContext, record: ApprovalRecord, source: SourceState) -> None:
        """名称这类没有物理列的字段，已有的行由读取视图带出；新增的行、换了 Lookup 字段值的行（例如换了物料）库里还没有，
        视图带不出来。这些行按页面上这个字段的 Lookup（C06 第 3 节的 `fill`）用修改后的值查一次，把回填字段中没有物理列的
        填进修改后的值。没有配置 Lookup 的字段不处理。"""
        view = ctx.config.page_view(record.page)
        doc = source.after
        regions = [(view.master.entity, view.master.fields, [doc.master]),
                   *((d.entity, d.fields, doc.details.get(d.entity, [])) for d in view.details)]
        for code, fields, rows in regions:
            entity = ctx.config.entity(code)
            columnless = {f.name for f in entity.fields if f.column is None}
            for view_field in fields:
                setting = view_field.lookup
                lookup = ctx.config.lookup(setting.code) if setting is not None else None
                if setting is None or lookup is None or view_field.name not in setting.fill:
                    continue
                targets = {name: column for name, column in setting.fill.items() if name in columnless}
                pending: dict[str, list[Row]] = {}
                for row in rows:
                    value = row.values.get(view_field.name)
                    before = find_row(source.before, code, row.row_key, None) if row.row_key else None
                    if value is None or (before is not None and key_text(before.values.get(view_field.name)) == key_text(value)):
                        continue
                    pending.setdefault(key_text(value), []).append(row)
                if not targets or not pending:
                    continue
                key_column = setting.fill[view_field.name]
                columns = [key_column, *dict.fromkeys(targets.values())]
                statement, binds = keys_sql(lookup.table, key_column, list(pending), columns)
                for found in self.deps.sql.rows(uow, statement, binds):
                    for row in pending.get(key_text(found.get(key_column.upper())), []):
                        for name, column in targets.items():
                            row.values[name] = found.get(column.upper())

    def _source_tables(self, uow: UnitOfWork, ctx: ExecutionContext, record: ApprovalRecord, source: SourceState,
                       scopes: Mapping[int, RowScope]) -> tuple[ViewMasterTable, list[ViewDetailTable]]:
        self._fill_lookups(uow, ctx, record, source)
        master_code = record.source.entity
        master_entity = ctx.config.entity(master_code)
        flows_of: dict[tuple[str, str], list[str]] = {}
        for trigger in record.triggers:
            flows_of[(trigger.entity, trigger.row_key or trigger.client_row_id or "")] = list(trigger.flows)
        master_blocks = [b for f in record.flows for b in f.config.display if b.region == "master"]
        detail_blocks: dict[str, list[DisplayBlock]] = {}
        for flow in record.flows:
            for block in flow.config.display:
                if block.region == "detail":
                    detail_blocks.setdefault(block.source, []).append(block)
        patch = record.patch
        bill = bill_key(patch, record.key_map)
        master_op = ("add" if isinstance(patch.master, MasterAdd) else "delete" if isinstance(patch.master, MasterDelete)
                     else "modify" if isinstance(patch.master, MasterModify) else None)
        before_master = source.before.master if source.before is not None else None
        after_master = None if source.applied.master_deleted else source.after.master
        flows = flows_of.get((master_code, bill), [])

        if master_blocks or detail_blocks:
            first = master_blocks[0] if master_blocks else None
            columns = _columns(master_blocks)
            rows = []
            show = first is None or first.condition is None or self._holds(uow, first.condition, self._row_scope(
                ctx, record, source, master_code, bill, "modify" if master_op is None else master_op))
            if master_blocks and show:
                rows.append(self._source_row(columns, master_entity, before_master, after_master, master_op, flows))
            master = ViewMasterTable(key=first.key if first else "master", title=first.title if first else record.page_title,
                                     columns=[c.label for c in columns], rows=rows)
            details = []
            for code, blocks in detail_blocks.items():
                entity = ctx.config.entity(code)
                columns = _columns(blocks)
                lead = blocks[0]
                rows = [self._source_row(columns, entity, before, after, op, flows_of.get((code, key), []))
                        for key, op, before, after in self._detail_rows(uow, ctx, record, source, code, lead)]
                details.append(ViewDetailTable(key=lead.key, title=lead.title, columns=[c.label for c in columns], rows=rows))
            return master, details

        # 没有配置 master、detail 块：主表显示有变化的字段，每个明细表一个 Tab，显示有变化的行和字段（C06 7.6）
        changed = [f.name for f in master_entity.fields
                   if cell(before_master.values.get(f.name) if before_master else None)
                   != cell(after_master.values.get(f.name) if after_master else None)]
        columns = [DisplayColumn(field=n, label=next(f.label for f in master_entity.fields if f.name == n)) for n in changed]
        master = ViewMasterTable(key="master", title=record.page_title, columns=[c.label for c in columns],
                                 rows=[self._source_row(columns, master_entity, before_master, after_master, master_op, flows)])
        details = []
        for link in master_entity.details:
            entity = ctx.config.entity(link.entity)
            rows_data = [r for r in self._detail_rows(uow, ctx, record, source, link.entity, None)]
            if not rows_data:
                continue
            names: dict[str, None] = {}
            for _, _, before, after in rows_data:
                for f in entity.fields:
                    if cell(before.values.get(f.name) if before else None) != cell(after.values.get(f.name) if after else None):
                        names[f.name] = None
            columns = [DisplayColumn(field=n, label=next(f.label for f in entity.fields if f.name == n)) for n in names]
            title = next((d.title for d in ctx.config.page_view(record.page).details if d.entity == link.entity), link.entity)
            details.append(ViewDetailTable(key=link.entity, title=title, columns=[c.label for c in columns], rows=[
                self._source_row(columns, entity, before, after, op, flows_of.get((link.entity, key), []))
                for key, op, before, after in rows_data]))
        return master, details

    def _row_scope(self, ctx: ExecutionContext, record: ApprovalRecord, source: SourceState, entity: str, key: str,
                   op: str) -> RowScope:
        master_entity = ctx.config.entity(record.source.entity)
        master_new = {} if source.applied.master_deleted else dict(source.after.master.values)
        master_old = dict(source.before.master.values) if source.before is not None else {}
        before = find_row(source.before, entity, key, None)
        after = find_row(source.after, entity, key, None)
        bill = master_old.get(master_entity.primary_key) or master_new.get(master_entity.primary_key)
        return RowScope(op if op in ("add", "modify", "delete") else "modify", dict(after.values) if after else {},  # type: ignore[arg-type]
                        dict(before.values) if before else {}, master_new, master_old, bill, record.applicant_id,
                        record.applicant_department)

    def _holds(self, uow: UnitOfWork, condition: str, scope: RowScope) -> bool:
        statement = entry_sql(condition)
        return bool(self.deps.sql.rows(uow, statement, binds_for(statement, scope)))

    def _detail_rows(self, uow: UnitOfWork, ctx: ExecutionContext, record: ApprovalRecord, source: SourceState, code: str,
                     block: DisplayBlock | None) -> list[tuple[str, str | None, Row | None, Row | None]]:
        """明细块的行：（主键、操作、修改前、修改后）。不写条件时为本次新增、修改、删除的行；写了条件时对这张表的每一行判断。"""
        ops: dict[str, str] = {}
        for change in source.applied.changes:
            if change.entity == code:
                ops[change.row_key] = change.op
        deleted = {r.row_key: r for r in source.applied.deleted if r.entity == code}
        if block is None or block.condition is None:
            keys = list(ops)
        else:
            after_rows = [r.row_key or "" for r in source.after.details.get(code, [])]
            keys = [k for k in [*after_rows, *deleted] if self._holds(uow, block.condition, self._row_scope(
                ctx, record, source, code, k, ops.get(k, "modify")))]
        found = []
        for key in keys:
            op = ops.get(key)
            before = find_row(source.before, code, key, None) if op != "add" else None
            after = None if key in deleted else find_row(source.after, code, key, None)
            found.append((key, op, before, after))
        return found

    @staticmethod
    def _source_row(columns: Sequence[DisplayColumn], entity: EntityConfig, before: Row | None, after: Row | None,
                    op: str | None, flows: list[str]) -> ViewRow:
        scales = {f.name: f.scale for f in entity.fields}
        cells = []
        for column in columns:
            name = column.field.removeprefix("master.")
            precision = column.precision if column.precision is not None else scales.get(name)
            cells.append(ViewCell(before=None if op == "add" or before is None else cell(before.values.get(name), precision),
                                  after=None if op == "delete" or after is None else cell(after.values.get(name), precision)))
        if op is None:
            op = "modify" if any(c.before != c.after for c in cells) else "none"
        return ViewRow(op=op, cells=cells, flows=flows)  # type: ignore[arg-type]

    # ---------------------------------------------------------------- 受影响单据的表格

    def _affected_scales(self, block: DisplayBlock, catalog: ApprovalCatalog) -> list[int | None]:
        """受影响单据各列的小数位（C06 7.6）：写了 `precision` 取它；没写时取页面视图，即读取这一块 `source` 的实体
        （修改表上注册的实体中，读取视图或表就是 `source` 的那个）字段的 `scale`，`master.` 列取所属主表实体的字段。
        找不到这样的实体时（修改表没注册），没写 `precision` 的列按原值显示。"""
        source = block.source.upper()
        entity = next((e for e in catalog.entities_on_table(self.target_table(block))
                       if (e.config.read_view or e.config.table).upper() == source), None)
        scales: list[int | None] = []
        for column in block.columns:
            scale = column.precision
            if scale is None and entity is not None:
                if column.field.startswith("master."):
                    name = column.field.removeprefix("master.")
                    scale = next((f.scale for f in entity.root_config.fields if f.name == name), None)
                else:
                    target = (column.target_column or column.field).upper()
                    scale = next((f.scale for f in entity.config.fields if (f.column or f.name).upper() == target), None)
            scales.append(scale)
        return scales

    def _affected_table(self, ctx: ExecutionContext, catalog: ApprovalCatalog, flow: FlowSnapshot, block: DisplayBlock,
                        rows: Sequence[AffectedRow], current_rows: Mapping[str, list[dict[str, Any]]],
                        plan_of: Mapping[tuple[str, str, int], RowPlan], owner_of: Mapping[tuple[str, str], Owner],
                        before_docs: Mapping[DocumentRef, DocumentData], after_docs: Mapping[DocumentRef, DocumentData],
                        user_can_edit: bool, with_flow_name: bool) -> ViewAffectedTable:
        """一块受影响单据：勾选框按修改表的主键分，主键相同的几行只有第一行带 `ref` 和 `checked`；记录已不存在的行排在最后
        （AP-21）。几个审批流合成的审批，标题后注明审批流名称（C06 7.6）。"""
        table = self.target_table(block)
        target_columns = {c.upper() for c in (self.deps.schema.columns(table) or {})}
        scales = self._affected_scales(block, catalog)
        selection = block.selection or "checked"
        view_rows: list[ViewRow] = []
        for row in [a for a in rows if not a.missing] + [a for a in rows if a.missing]:
            if row.missing:
                cells = [ViewCell(before=cell(row.data.get(c.field.upper()), s), after=cell(row.data.get(c.field.upper()), s))
                         for c, s in zip(block.columns, scales, strict=True)]
                view_rows.append(ViewRow(op="none", cells=cells, missing=True))
                continue
            plan = plan_of.get((flow.code, block.key, row.seq))
            owner = owner_of.get((table.upper(), row.key or ""))
            before_doc = before_docs.get(owner.document) if owner else None
            after_doc = after_docs.get(owner.document) if owner else None
            sources = current_rows.get(row.key or "") or [row.data]
            updates: dict[str, Value] = {}
            deleting = False
            if plan is not None:
                for write in plan.writes:
                    if write.action == "update" and write.table.upper() == table.upper():
                        updates.update({k.upper(): v for k, v in write.values.items()})
                    elif write.action == "delete" and write.table.upper() == table.upper():
                        deleting = True
            for position, data in enumerate(sources):
                cells = []
                for column, scale in zip(block.columns, scales, strict=True):
                    before_value, after_value = self._affected_cell(column, data, owner, before_doc, after_doc, plan is not None,
                                                                    updates, target_columns, row.key or "")
                    cells.append(ViewCell(before=cell(before_value, scale), after=None if deleting else cell(after_value, scale)))
                if plan is None:
                    op = "none"
                elif deleting:
                    op = "delete"
                else:
                    op = "modify" if any(c.before != c.after for c in cells) else "none"
                first = position == 0
                view_rows.append(ViewRow(op=op, cells=cells, ref=RowRef(key=row.key or "") if first else None,  # type: ignore[arg-type]
                                         checked=(plan is not None) if first else None))
        title = f"{block.title}（{flow.name}）" if with_flow_name else block.title
        return ViewAffectedTable(flow=flow.code, key=block.key, title=title, selection=selection,  # type: ignore[arg-type]
                                 editable=user_can_edit and selection == "checked", columns=[c.label for c in block.columns],
                                 rows=view_rows)

    def _affected_cell(self, column: DisplayColumn, data: Mapping[str, Any], owner: Owner | None, before_doc: DocumentData | None,
                       after_doc: DocumentData | None, checked: bool, updates: Mapping[str, Value], target_columns: set[str],
                       key: str) -> tuple[object, object]:
        if column.field.startswith("master."):
            name = column.field.removeprefix("master.")
            before = before_doc.master.values.get(name) if before_doc else None
            after = after_doc.master.values.get(name) if (checked and after_doc) else before
            return before, after
        before = data.get(column.field.upper())
        if not checked:
            return before, before
        target = (column.target_column or column.field).upper()
        if owner is not None and after_doc is not None:
            name = column_field(owner.entity.config, target)
            row = find_row(after_doc, owner.entity.code, key, None)
            if name is None or row is None:
                return before, before
            return before, row.values.get(name)
        if target in target_columns and target in updates:
            return before, updates[target]
        return before, before
