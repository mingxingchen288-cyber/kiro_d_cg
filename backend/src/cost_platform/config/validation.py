"""保存时的校验（C06 第 10 节、CF-01）。

`Validator.check` 对要保存的配置项、以及引用了它们的配置项，逐条执行 C06 第 10 节的校验，返回全部错误明细（C03 第 1 节：
`configType`、`configKey`、`path`、`message`）。审批流的校验在 `validation_flow.py`。

- 表和列经 db-core 的 `SchemaInspector` 核对；序列、部门经 `deps.py` 的两个协议；
- SQL（关联 SQL、数据项、导出、审批人、行权限、审批流片段）经调用方的 UnitOfWork 交给数据库解析（`sql_check.QueryChecker`）；
- 规则包经 rules-core 的 `RulesEngine.load_pack` 编译，`PackInvalidError`（含依赖成环）转成错误明细。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from cost_platform.contracts.ports import RulesEngine, SchemaInspector, UnitOfWork
from cost_platform.contracts.types import (
    ColumnInfo,
    EntityConfig,
    EntityField,
    ErrorDetail,
    FieldFlags,
    FieldSetting,
    FieldMap,
    PackInvalidError,
    QueryCompare,
    RelationKeyFinder,
    ReplaceDetails,
    SqlFinder,
    UpdateRecords,
    UpdateRows,
    UpdateTargets,
    EscapeHatch,
    VisualRowPolicy,
)

from .catalog import Catalog, Entry, references, referrers
from .deps import DepartmentLookup, SequenceChecker
from .expressions import visual_fields
from .packs import affected_masters, build_pack, pack_bytes
from .sql_check import QueryChecker, SqlProblem, is_condition, is_identifier, is_single_query, parameters
from .views import BUILTIN_REQUIRES_SELECTION

GRID_COLUMNS = 24
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
ROW_PLACEHOLDERS = ("userId", "username")
"""行权限 SQL 可以用的占位符（C06 第 8 节）。"""


@dataclass
class Run:
    """一次校验：配置、事务、表结构缓存和收集到的错误。"""

    validator: Validator
    uow: UnitOfWork
    catalog: Catalog
    problems: list[ErrorDetail] = field(default_factory=list)
    _columns: dict[str, dict[str, ColumnInfo] | None] = field(default_factory=dict)
    _types: dict[str, str | None] = field(default_factory=dict)
    _keys: dict[str, str | None] = field(default_factory=dict)

    # ---------------------------------------------------------------- 记录错误

    def err(self, entry: Entry, path: str | None, message: str) -> None:
        self.problems.append(ErrorDetail(message=message, config_type=entry.type, config_key=entry.key, path=path or None))

    # ---------------------------------------------------------------- 数据库结构（同一次校验内缓存）

    def columns(self, name: str) -> dict[str, ColumnInfo] | None:
        if name not in self._columns:
            self._columns[name] = self.validator.schema.columns(name)
        return self._columns[name]

    def object_type(self, name: str) -> str | None:
        if name not in self._types:
            self._types[name] = self.validator.schema.object_type(name)
        return self._types[name]

    def primary_key(self, table: str) -> str | None:
        if table not in self._keys:
            self._keys[table] = self.validator.schema.primary_key(table)
        return self._keys[table]

    def describe(self, entry: Entry, path: str, sql: str) -> list[str] | None:
        """交给数据库解析；不通过时记录错误，返回 None。"""
        try:
            return self.validator.queries.describe(self.uow, sql)
        except SqlProblem as problem:
            self.err(entry, path, f"数据库解析不通过：{problem.message}")
            return None

    def query(self, entry: Entry, path: str, sql: str, binds: Mapping[str, str] | None = None) -> list[str] | None:
        """只能是一条查询语句，参数用绑定变量（C06 第 10 节）；通过时返回结果列名。"""
        if not is_single_query(sql):
            self.err(entry, path, "只能是一条查询语句（以 SELECT 或 WITH 开头，不能有分号和数据修改语句）")
            return None
        if binds is not None:
            missing = [p for p in parameters(sql) if p not in binds]
            if missing:
                self.err(entry, path, f"参数 {', '.join(':' + p for p in missing)} 没有在 binds 中给出取值")
                return None
        return self.describe(entry, path, sql)

    def sequence(self, entry: Entry, path: str, table: str) -> None:
        name = f"{table}_SEQ"
        if not self.validator.sequences.exists(self.uow, name):
            self.err(entry, path, f"序列 {name} 不存在：请先在数据库中建立，平台不创建序列")

    # ---------------------------------------------------------------- 实体和字段

    def entity_fields(self, code: str) -> dict[str, EntityField]:
        entity = self.catalog.entity(code)
        return {f.name: f for f in entity.fields} if entity else {}

    def read_source(self, code: str) -> str | None:
        """实体读取用的表或视图（有 readView 时为视图）。"""
        entity = self.catalog.entity(code)
        return None if entity is None else entity.read_view or entity.table

    def entity_ref(self, entry: Entry, path: str, code: str) -> EntityConfig | None:
        entity = self.catalog.entity(code)
        if entity is None:
            self.err(entry, path, f"实体 {code} 不存在")
        return entity

    def field_ref(self, entry: Entry, path: str, ref: str) -> tuple[str, EntityField] | None:
        """`实体.字段` 的写法。"""
        code, _, name = ref.partition(".")
        if not name:
            self.err(entry, path, f"{ref} 应写成 实体.字段")
            return None
        found = self.entity_fields(code).get(name)
        if found is None:
            self.err(entry, path, f"实体 {code} 没有字段 {name}" if self.catalog.entity(code) else f"实体 {code} 不存在")
            return None
        return code, found

    def layered(self, entry: Entry, path: str, entity: EntityConfig, field_def: EntityField,
                upper: Sequence[FieldFlags | FieldSetting | None], lower: FieldFlags | FieldSetting) -> None:
        """下层只能收紧可见、可编辑，必填只能增加；ERP 列和 erpRow.column 不能设为可写（C06 第 10 节）。"""
        if lower.visible is True and any(u is not None and u.visible is False for u in upper):
            self.err(entry, f"{path}.visible", f"上层已把 {field_def.name} 设为不可见，下层只能收紧可见")
        if lower.editable is True and any(u is not None and u.editable is False for u in upper):
            self.err(entry, f"{path}.editable", f"上层已把 {field_def.name} 设为不可编辑，下层只能收紧可编辑")
        if lower.required is False and any(u is not None and u.required is True for u in upper):
            self.err(entry, f"{path}.required", f"上层已把 {field_def.name} 设为必填，下层只能增加必填")
        if lower.editable is True:
            self.writable_field(entry, f"{path}.editable", entity, field_def)

    def writable_field(self, entry: Entry, path: str, entity: EntityConfig, field_def: EntityField) -> None:
        if field_def.source == "erp" and entity.erp_row is None:
            self.err(entry, path, f"实体没有 erpRow，ERP 列 {field_def.name} 不能设为可写")
        if entity.erp_row is not None and field_def.name == entity.erp_row.column:
            self.err(entry, path, f"{field_def.name} 是 erpRow.column，只由平台写，不能设为可写")


class Validator:
    def __init__(self, schema: SchemaInspector, sequences: SequenceChecker, departments: DepartmentLookup,
                 engine: RulesEngine, queries: QueryChecker | None = None) -> None:
        self.schema = schema
        self.sequences = sequences
        self.departments = departments
        self.engine = engine
        self.queries = queries or QueryChecker()

    def check(self, uow: UnitOfWork, catalog: Catalog, targets: Iterable[tuple[str, str]]) -> list[ErrorDetail]:
        """校验 `targets`（已合并进 `catalog`）以及引用了它们的配置项。"""
        from .validation_flow import check_flow

        run = Run(self, uow, catalog)
        targets = list(dict.fromkeys(targets))
        todo = list(targets)
        for config_type, key in targets:
            todo += [(e.type, e.key) for e, _ in referrers(catalog, config_type, key)]
        for config_type, key in dict.fromkeys(todo):
            entry = catalog.get(config_type, key)
            if entry is None:
                continue
            _references(run, entry)
            checker = {"entity": _entity, "page": _page, "operation": _operation, "rule": _rule, "approvalFlow": check_flow,
                       "role": _role, "lookup": _lookup, "export": _export}.get(config_type)
            if checker is not None:
                checker(run, entry)
        _packs(run, targets)
        return run.problems


# ================================================================ 各类配置项

def _references(run: Run, entry: Entry) -> None:
    """引用的实体、操作、页面、审批流、Lookup、字典都存在。"""
    for ref_type, ref_key, at in references(entry.type, entry.content):
        if ref_type == "role":
            continue  # C06 第 10 节没有要求审批人的角色已存在（角色可以随账号迁移导入）
        if not run.catalog.has(ref_type, ref_key):
            run.err(entry, at, f"引用的{_TYPE_NAMES.get(ref_type, ref_type)} {ref_key} 不存在")


_TYPE_NAMES = {"entity": "实体", "page": "页面", "operation": "操作", "approvalFlow": "审批流", "lookup": "Lookup", "dict": "字典",
               "role": "角色", "rule": "规则"}


def _entity(run: Run, entry: Entry) -> None:
    entity: EntityConfig = entry.content
    kind = run.object_type(entity.table)
    table_columns = run.columns(entity.table) or {}
    if kind is None:
        run.err(entry, "table", f"表 {entity.table} 在数据库中不存在")
    elif kind != "table":
        run.err(entry, "table", f"{entity.table} 是视图，实体的 table 必须是表")
    else:
        run.sequence(entry, "table", entity.table)
        if entity.primary_key not in table_columns:
            run.err(entry, "primaryKey", f"主键列 {entity.primary_key} 不在表 {entity.table} 中")
    view_columns: dict[str, ColumnInfo] | None = None
    if entity.read_view is not None:
        view_columns = run.columns(entity.read_view)
        if view_columns is None:
            run.err(entry, "readView", f"视图 {entity.read_view} 在数据库中不存在")
        else:
            missing = [n for n in [entity.primary_key, *(f.name for f in entity.fields)] if n not in view_columns]
            if missing:
                run.err(entry, "readView", f"视图 {entity.read_view} 缺少主键或实体字段：{'、'.join(dict.fromkeys(missing))}")
    names: dict[str, EntityField] = {}
    for i, f in enumerate(entity.fields):
        if f.name in names:
            run.err(entry, f"fields[{i}].name", f"字段 {f.name} 重复")
        names[f.name] = f
        if f.column is None:
            if entity.read_view is None:
                run.err(entry, f"fields[{i}].column", f"字段 {f.name} 的 column 为 null，只能来自 readView，但实体没有设置 readView")
        elif kind == "table" and f.column not in table_columns:
            run.err(entry, f"fields[{i}].column", f"列 {f.column} 不在表 {entity.table} 中")
        if isinstance(f.compare, QueryCompare):
            _compare(run, entry, f"fields[{i}].compare", f.compare, entity)
        elif f.compare is not None and f.compare.field not in {x.name for x in entity.fields}:
            run.err(entry, f"fields[{i}].compare.field", f"对比字段 {f.compare.field} 不是本实体的字段")
    if entity.erp_row is not None:
        if kind == "table" and entity.erp_row.column not in table_columns:
            run.err(entry, "erpRow.column", f"列 {entity.erp_row.column} 不在表 {entity.table} 中")
    for i, link in enumerate(entity.details):
        detail = run.catalog.entity(link.entity)
        if detail is not None and link.parent_key not in {f.name for f in detail.fields}:
            run.err(entry, f"details[{i}].parentKey", f"明细实体 {link.entity} 没有字段 {link.parent_key}")
    for name, flags in entity.field_defaults.items():
        if name not in names:
            run.err(entry, f"fieldDefaults.{name}", f"字段 {name} 不是本实体的字段")
        elif flags.editable is True:
            run.writable_field(entry, f"fieldDefaults.{name}.editable", entity, names[name])
    flows = run.catalog.flows()
    for i, rule in enumerate(entity.approval_required):
        for j, name in enumerate(rule.fields):
            if name not in names:
                run.err(entry, f"approvalRequired[{i}].fields[{j}]", f"字段 {name} 不是本实体的字段")
        for j, item in enumerate(rule.when.conditions if rule.when else []):
            if item.field not in names:
                run.err(entry, f"approvalRequired[{i}].when.conditions[{j}].field", f"字段 {item.field} 不是本实体的字段")
        if not any(f.enabled and f.page in rule.source_pages for f in flows.values()):
            run.err(entry, f"approvalRequired[{i}].sourcePages", "sourcePages 中的页面都没有启用的审批流")


def _compare(run: Run, entry: Entry, path: str, compare: QueryCompare, entity: EntityConfig) -> None:
    """`compare.source` 只能是查询语句或表、视图名（C06 第 10 节）。"""
    if is_identifier(compare.source):
        found = run.columns(compare.source)
        if found is None:
            run.err(entry, f"{path}.source", f"表或视图 {compare.source} 在数据库中不存在")
            return
        columns = list(found)
    else:
        columns = run.query(entry, f"{path}.source", compare.source, {}) or []
        if not columns:
            return
    for k, key in enumerate(compare.keys):
        if key.current not in {f.name for f in entity.fields}:
            run.err(entry, f"{path}.keys[{k}].current", f"字段 {key.current} 不是本实体的字段")
        if key.compare.upper() not in {c.upper() for c in columns}:
            run.err(entry, f"{path}.keys[{k}].compare", f"列 {key.compare} 不在 {compare.source} 中")
    if compare.field.upper() not in {c.upper() for c in columns}:
        run.err(entry, f"{path}.field", f"列 {compare.field} 不在 {compare.source} 中")


def _page(run: Run, entry: Entry) -> None:
    page = entry.content
    master = run.catalog.entity(page.master.entity)
    if page.layout == "single" and page.details:
        run.err(entry, "details", "单表页不能有明细")
    links = {d.entity for d in master.details} if master else set()
    areas = [("master", page.master)]
    for i, area in enumerate(page.details):
        if master is not None and area.entity not in links:
            run.err(entry, f"details[{i}].entity", f"实体 {area.entity} 不是主表实体 {page.master.entity} 的明细")
        areas.append((f"details[{i}]", area))
    for at, area in areas:
        entity = run.catalog.entity(area.entity)
        if entity is None:
            continue
        names = {f.name: f for f in entity.fields}
        for name, setting in area.fields.items():
            here = f"{at}.fields.{name}"
            if name not in names:
                run.err(entry, here, f"字段 {name} 不是实体 {area.entity} 的字段")
                continue
            run.layered(entry, here, entity, names[name], [entity.field_defaults.get(name)], setting)
            if setting.lookup is not None:
                _lookup_setting(run, entry, f"{here}.lookup", setting.lookup, names)
            if setting.aggregate is not None and names[name].type != "number":
                run.err(entry, f"{here}.aggregate", f"{name} 不是数值字段，不能求和")
        for j, cell in enumerate(area.form_layout):
            here = f"{at}.formLayout[{j}]"
            if cell.field not in names:
                run.err(entry, f"{here}.field", f"表单布局引用的字段 {cell.field} 不存在")
            if cell.x < 0 or cell.y < 0 or cell.w < 1 or cell.h < 1 or cell.x + cell.w > GRID_COLUMNS:
                run.err(entry, here, f"表单布局越出 {GRID_COLUMNS} 列：x 从 0 起，x + w 不超过 {GRID_COLUMNS}，w、h 不小于 1")
        for j, button in enumerate(area.buttons):
            here = f"{at}.buttons[{j}]"
            if button.action in BUILTIN_REQUIRES_SELECTION:
                if button.operation is not None or button.requires_selection is not None:
                    run.err(entry, here, f"内置动作 {button.action} 不能写 operation 和 requiresSelection")
            elif button.operation is None or button.requires_selection is None:
                run.err(entry, here, f"业务动作 {button.action} 必须写 operation 和 requiresSelection")


def _lookup_setting(run: Run, entry: Entry, path: str, setting: Any, names: Mapping[str, EntityField]) -> None:
    lookup = run.catalog.of_type("lookup").get(setting.code)
    for name, column in setting.fill.items():
        if name not in names:
            run.err(entry, f"{path}.fill.{name}", f"回填字段 {name} 不是本区域实体的字段")
        if lookup is not None and column not in lookup.columns:
            run.err(entry, f"{path}.fill.{name}", f"列 {column} 不在 Lookup {setting.code} 的 columns 中")
    if setting.filter is not None:
        if lookup is not None and setting.filter.column not in lookup.columns:
            run.err(entry, f"{path}.filter.column", f"列 {setting.filter.column} 不在 Lookup {setting.code} 的 columns 中")
        if setting.filter.from_ == "row" and (setting.filter.field is None or setting.filter.field not in names):
            run.err(entry, f"{path}.filter.field", "按本行字段筛选时，field 必须是本区域实体的字段")


def _operation(run: Run, entry: Entry) -> None:
    operation = entry.content
    writable = {code: set(fields) for code, fields in operation.writable_fields.items()}
    for code, fields in operation.writable_fields.items():
        entity = run.catalog.entity(code)
        if entity is None:
            continue
        names = {f.name: f for f in entity.fields}
        for j, name in enumerate(fields):
            here = f"writableFields.{code}[{j}]"
            if name not in names:
                run.err(entry, here, f"字段 {name} 不是实体 {code} 的字段")
            else:
                run.writable_field(entry, here, entity, names[name])
    for i, step in enumerate(operation.actions):
        here = f"actions[{i}]"
        if isinstance(step, UpdateTargets):
            for j, target in enumerate(step.targets):
                dest = target.detail_entity or target.entity
                for name, ref in target.match.items():
                    if name not in run.entity_fields(dest):
                        run.err(entry, f"{here}.targets[{j}].match.{name}", f"字段 {name} 不是实体 {dest} 的字段")
                    run.field_ref(entry, f"{here}.targets[{j}].match.{name}", ref)
                _mapping(run, entry, f"{here}.targets[{j}].fieldMapping", target.field_mapping, dest, writable)
        elif isinstance(step, UpdateRecords):
            _finder(run, entry, f"{here}.find", step)
            _mapping(run, entry, f"{here}.fieldMapping", step.field_mapping, step.find.entity, writable)
        elif isinstance(step, ReplaceDetails):
            _replace_details(run, entry, here, step, writable)
        elif isinstance(step, UpdateRows):
            _update_rows(run, entry, here, step, writable)
        elif isinstance(step, EscapeHatch):
            target = run.catalog.operation(step.operation)
            if target is not None and target.kind != "escapeHatch":
                run.err(entry, f"{here}.operation", f"操作 {step.operation} 不是逃生舱操作")
    if operation.kind == "escapeHatch":
        _escape_writes(run, entry, operation.writes)


def _mapping(run: Run, entry: Entry, path: str, mapping: Sequence[FieldMap], dest: str, writable: Mapping[str, set[str]]) -> None:
    """`fieldMapping.to` 必须在操作允许写入的范围内，不能是计算字段，也不能是只读的 ERP 列（C06 第 6 节、第 10 节）。"""
    entity = run.catalog.entity(dest)
    names = {f.name: f for f in entity.fields} if entity else {}
    for k, item in enumerate(mapping):
        run.field_ref(entry, f"{path}[{k}].from", item.from_)
        if entity is None:
            continue
        target = names.get(item.to)
        if target is None:
            run.err(entry, f"{path}[{k}].to", f"字段 {item.to} 不是实体 {dest} 的字段")
            continue
        if item.to not in writable.get(dest, set()):
            run.err(entry, f"{path}[{k}].to", f"字段 {item.to} 不在本操作 writableFields.{dest} 中")
        if target.role == "calculated":
            run.err(entry, f"{path}[{k}].to", f"{item.to} 是计算字段，不能写")
        run.writable_field(entry, f"{path}[{k}].to", entity, target)


def _finder(run: Run, entry: Entry, path: str, step: UpdateRecords) -> None:
    finder = step.find
    if isinstance(finder, RelationKeyFinder):
        if finder.target_key not in run.entity_fields(finder.entity):
            run.err(entry, f"{path}.targetKey", f"字段 {finder.target_key} 不是实体 {finder.entity} 的字段")
        run.field_ref(entry, f"{path}.sourceKey", finder.source_key)
        if finder.rows != "all":
            run.err(entry, f"{path}.rows", "按钮命令不带修改，按关联键查找时 rows 只能为 all")
        return
    assert isinstance(finder, SqlFinder)
    details: set[str] = set()
    for name, ref in finder.binds.items():
        found = run.field_ref(entry, f"{path}.binds.{name}", ref)
        if found is not None and run.catalog.parent_of(found[0]) is not None:
            details.add(found[0])
    if len(details) > 1:
        run.err(entry, f"{path}.binds", f"绑定变量最多引用一个明细实体，现在引用了 {'、'.join(sorted(details))}")
    columns = run.query(entry, f"{path}.sql", finder.sql, finder.binds)
    if columns is not None:
        missing = [c for c in [finder.record_key_column, *finder.row_key_columns] if c.upper() not in columns]
        if missing:
            run.err(entry, f"{path}.sql", f"关联 SQL 的结果缺少列：{'、'.join(missing)}")


def _sql_columns(run: Run, entry: Entry, path: str, columns: Sequence[str], dest: str,
                 writable: Mapping[str, set[str]]) -> None:
    """`replaceDetails`、`updateRows` 的 SQL 中要写的列（C06 第 6 节）：列名就是 `dest` 的字段名（不区分大小写），
    字段在本操作的 `writableFields` 中，不是计算字段、不是只在视图中的字段，也不是只读的 ERP 列。"""
    entity = run.catalog.entity(dest)
    if entity is None:
        return
    names = {f.name.upper(): f for f in entity.fields}
    for column in columns:
        target = names.get(column.upper())
        if target is None:
            run.err(entry, path, f"SQL 的列 {column} 不是实体 {dest} 的字段：列名要写成字段名")
            continue
        if target.name not in writable.get(dest, set()):
            run.err(entry, path, f"SQL 的列 {target.name} 不在本操作 writableFields.{dest} 中")
        if target.role == "calculated":
            run.err(entry, path, f"SQL 的列 {target.name} 是计算字段，由计算规则得出，不能写")
        elif target.column is None:
            run.err(entry, path, f"SQL 的列 {target.name} 只在视图中，不能写：名称这类字段由页面的 Lookup 带出")
        run.writable_field(entry, path, entity, target)


def _replace_details(run: Run, entry: Entry, path: str, step: ReplaceDetails, writable: Mapping[str, set[str]]) -> None:
    """`replaceDetails`：`entity` 是明细实体；绑定变量只引用它所属主表的字段；SQL 只能是一条查询语句，结果的每一列
    都是这个明细中本操作可写的字段（C06 第 6 节、第 10 节）。"""
    parent = run.catalog.parent_of(step.entity)
    if parent is None:
        if run.catalog.entity(step.entity) is not None:
            run.err(entry, f"{path}.entity", f"实体 {step.entity} 不是明细实体：replaceDetails 只替换单据的明细")
        return
    for name, ref in step.binds.items():
        found = run.field_ref(entry, f"{path}.binds.{name}", ref)
        if found is not None and found[0] != parent[0]:
            run.err(entry, f"{path}.binds.{name}", f"绑定变量只能引用主表 {parent[0]} 的字段，{ref} 不是")
    columns = run.query(entry, f"{path}.sql", step.sql, step.binds)
    if columns is not None:
        _sql_columns(run, entry, f"{path}.sql", columns, step.entity, writable)


def _update_rows(run: Run, entry: Entry, path: str, step: UpdateRows, writable: Mapping[str, set[str]]) -> None:
    """`updateRows`：SQL 只能是一条查询语句、不用绑定变量；结果包含 `recordKeyColumn` 和 `rowKeyColumns`（明细实体写一列
    明细主键，主表实体不写），其余每一列都是 `entity` 中本操作可写的字段（C06 第 6 节、第 10 节）。"""
    if run.catalog.entity(step.entity) is None:
        return
    detail = run.catalog.parent_of(step.entity) is not None
    if detail and len(step.row_key_columns) != 1:
        run.err(entry, f"{path}.rowKeyColumns", f"{step.entity} 是明细实体，rowKeyColumns 要写一列明细主键")
    if not detail and step.row_key_columns:
        run.err(entry, f"{path}.rowKeyColumns", f"{step.entity} 是主表实体，不写 rowKeyColumns")
    used = parameters(step.sql)
    if used:
        run.err(entry, f"{path}.sql", f"updateRows 的 SQL 不用绑定变量，现在有 {', '.join(':' + p for p in used)}")
        return
    columns = run.query(entry, f"{path}.sql", step.sql)
    if columns is None:
        return
    keys = [step.record_key_column, *step.row_key_columns]
    missing = [c for c in keys if c.upper() not in columns]
    if missing:
        run.err(entry, f"{path}.sql", f"SQL 的结果缺少列：{'、'.join(missing)}")
    folded = {k.upper() for k in keys}
    _sql_columns(run, entry, f"{path}.sql", [c for c in columns if c not in folded], step.entity, writable)


def _escape_writes(run: Run, entry: Entry, writes: Mapping[str, list[str]]) -> None:
    """逃生舱登记的表和列存在；任何实体的 ERP 列都不能出现在 `writes` 中。"""
    for table, columns in writes.items():
        found = run.columns(table)
        if found is None:
            run.err(entry, f"writes.{table}", f"表 {table} 在数据库中不存在")
            continue
        erp = {f.column for code in run.catalog.entities_on_table(table) for f in run.catalog.entity(code).fields
               if f.source == "erp" and f.column}
        for j, column in enumerate(columns):
            if column not in found:
                run.err(entry, f"writes.{table}[{j}]", f"列 {column} 不在表 {table} 中")
            if column in erp:
                run.err(entry, f"writes.{table}[{j}]", f"{column} 是 ERP 列，逃生舱不能写")


def _rule(run: Run, entry: Entry) -> None:
    from .packs import rule_entity, rule_masters

    rule = entry.content
    masters = rule_masters(run.catalog, rule)
    master = masters[0] if masters else None
    entity_code = rule_entity(run.catalog, rule, master) if master else (rule.target if rule.layer == "entity" else None)
    fields = run.entity_fields(entity_code) if entity_code else {}
    master_fields = run.entity_fields(master) if master else {}
    if rule.category == "calc":
        if rule.field is None:
            run.err(entry, "field", "计算规则必须写 field")
        if not rule.expression and not rule.branches:
            run.err(entry, "expression", "计算规则必须写 expression 或 branches")
    if rule.field is not None and entity_code is not None and rule.field not in fields:
        run.err(entry, "field", f"字段 {rule.field} 不是实体 {entity_code} 的字段")
    if rule.category == "validate" and (rule.level is None or rule.message is None):
        run.err(entry, "level", "校验规则必须写 level 和 message")
    if rule.category == "ui" and rule.effect is None:
        run.err(entry, "effect", "界面规则必须写 effect")
    conditions = [("when", rule.when), *((f"branches[{i}].when", b.when) for i, b in enumerate(rule.branches or []))]
    for at, condition in conditions:
        for j, item in enumerate(visual_fields(condition)):
            pool = fields if item.source == "row" else master_fields
            if entity_code is not None and item.field not in pool:
                run.err(entry, f"{at}.conditions[{j}].field", f"字段 {item.field} 不存在")
    for i, item in enumerate(rule.data_items):
        for name, ref in item.binds.items():
            plain = ref.removeprefix("master.")
            pool = master_fields if ref.startswith("master.") else fields
            if entity_code is not None and plain not in pool:
                run.err(entry, f"dataItems[{i}].binds.{name}", f"字段 {ref} 不存在")
        run.query(entry, f"dataItems[{i}].sql", item.sql, item.binds)


def _role(run: Run, entry: Entry) -> None:
    role = entry.content
    for page_code, grant in role.pages.items():
        page = run.catalog.page(page_code)
        if page is None:
            continue
        regions = dict(run.catalog.page_regions(page_code))
        settings = {page.master.entity: page.master.fields, **{d.entity: d.fields for d in page.details}}
        for region, columns in grant.columns.items():
            here = f"pages.{page_code}.columns.{region}"
            if region not in regions:
                run.err(entry, here, f"{region} 不是页面 {page_code} 的区域（master 或明细实体）")
                continue
            entity = run.catalog.entity(regions[region])
            if entity is None:
                continue
            names = {f.name: f for f in entity.fields}
            for name, flags in columns.items():
                if name not in names:
                    run.err(entry, f"{here}.{name}", f"字段 {name} 不是实体 {regions[region]} 的字段")
                    continue
                upper = [entity.field_defaults.get(name), settings.get(regions[region], {}).get(name)]
                run.layered(entry, f"{here}.{name}", entity, names[name], upper, flags)
        if grant.rows is not None:
            _row_policy(run, entry, f"pages.{page_code}.rows", grant.rows, page.master.entity)


def _row_policy(run: Run, entry: Entry, path: str, rows: VisualRowPolicy | str, master: str) -> None:
    """行权限：只能是一个条件表达式，不能含分号和数据修改语句（C06 第 8 节）；交给数据库解析。"""
    sql = rows.sql if isinstance(rows, VisualRowPolicy) else rows
    at = f"{path}.sql" if isinstance(rows, VisualRowPolicy) else path
    if not is_condition(sql):
        run.err(entry, at, "行权限只能是一个条件表达式，不能含分号和数据修改语句")
        return
    unknown = [p for p in _PLACEHOLDER.findall(sql) if p not in ROW_PLACEHOLDERS]
    if unknown:
        run.err(entry, at, f"占位符只能用 ${{userId}}、${{username}}，不能用 {', '.join(unknown)}")
        return
    source = run.read_source(master)
    if source is not None:
        run.describe(entry, at, f"SELECT 1 FROM {source} WHERE ({_PLACEHOLDER.sub(lambda m: ':' + m.group(1), sql)})")


def _lookup(run: Run, entry: Entry) -> None:
    lookup = entry.content
    found = run.columns(lookup.table)
    if found is None:
        run.err(entry, "table", f"表或视图 {lookup.table} 在数据库中不存在")
        return
    for i, column in enumerate(lookup.columns):
        if column not in found:
            run.err(entry, f"columns[{i}]", f"列 {column} 不在 {lookup.table} 中")
    for i, column in enumerate(lookup.keyword_columns):
        if column not in lookup.columns:
            run.err(entry, f"keywordColumns[{i}]", f"关键字列 {column} 不在 columns 中")


def _export(run: Run, entry: Entry) -> None:
    export = entry.content
    columns = run.query(entry, "master.sql", export.master.sql, {})
    if columns is not None and export.master.key_column.upper() not in columns:
        run.err(entry, "master.sql", f"导出 SQL 的结果缺少 keyColumn {export.master.key_column}")
    for i, detail in enumerate(export.details):
        columns = run.query(entry, f"details[{i}].sql", detail.sql, {})
        if columns is not None and detail.link_column.upper() not in columns:
            run.err(entry, f"details[{i}].sql", f"导出 SQL 的结果缺少 linkColumn {detail.link_column}")


def _packs(run: Run, targets: Sequence[tuple[str, str]]) -> None:
    """表达式和条件能被 rules-core 解析，计算规则的依赖不成环，规则包能编译通过（C06 第 10 节、RC-09）。"""
    masters: dict[str, list[tuple[str, str]]] = {}
    for config_type, key in targets:
        for master in affected_masters(run.catalog, config_type, key):
            masters.setdefault(master, []).append((config_type, key))
    core_version = run.validator.engine.core_version()
    for master, owners in sorted(masters.items()):
        if run.catalog.entity(master) is None:
            continue
        pack = build_pack(run.catalog, master, 1, core_version)
        try:
            run.validator.engine.load_pack(pack_bytes(pack))
        except PackInvalidError as invalid:
            for config_type, key in owners:
                owner = run.catalog.get(config_type, key)
                if owner is not None:
                    run.err(owner, None, f"规则包 {master} 不能编译：{invalid.message}")


def check_structure(drafts: Iterable[Any]) -> list[ErrorDetail]:
    """内容符合 C06 的结构（contracts 的模型）；不符合时每项列出第一处错误。"""
    from pydantic import ValidationError

    from cost_platform.contracts.types import parse_config_content

    problems = []
    for draft in drafts:
        try:
            parse_config_content(draft.type, dict(draft.content))
        except ValidationError as error:
            for first in error.errors()[:1]:
                where = "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in first["loc"]).lstrip(".")
                kind = first["type"]
                message = (f"缺少 {where}" if kind == "missing" else f"不允许出现 {where}" if kind == "extra_forbidden"
                           else f"{where or '内容'} 的值不合法")
                problems.append(ErrorDetail(message=message, config_type=draft.type, config_key=draft.key, path=where or None))
    return problems


def dumps(details: Sequence[ErrorDetail]) -> str:
    """错误明细的文本（日志用）。"""
    return json.dumps([d.model_dump(mode="json") for d in details], ensure_ascii=False)
