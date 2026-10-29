"""审批流的保存校验（C06 第 7 节、第 10 节）。

SQL 片段（入口条件、冻结和展示的关联条件、取值）不含分号，参数只能是 C06 7.2 列出的几种，按 7.2 包好后交给数据库解析。
"""

from __future__ import annotations

from collections.abc import Collection

from cost_platform.contracts.types import (
    ApprovalFlowConfig,
    DeleteRows,
    DisplayBlock,
    EscapeHatch,
    InsertRows,
    SqlApprover,
    UpdateFields,
)

from .catalog import Entry
from .sql_check import has_semicolon, parameters, wrap_display, wrap_entry, wrap_freeze, wrap_value
from .validation import Run

SPECIAL_PARAMS = frozenset({"operation", "billId", "user_id", "user_departmentId"})
PLATFORM_PREFIX = "PF_"


def _params(run: Run, entry: Entry, path: str, sql: str, row_fields: Collection[str], master_fields: Collection[str],
            row_columns: Collection[str] | None = None, flow_params: Collection[str] | None = None) -> None:
    """参数只能是 C06 7.2 列出的几种；`:row_`、`:params_` 只用于取值（`row_columns`、`flow_params` 不为 None）。"""
    upper_columns = {c.upper() for c in row_columns} if row_columns is not None else None
    for name in parameters(sql):
        if name in SPECIAL_PARAMS:
            continue
        if name.startswith(("master_new_", "master_old_")):
            ok = name[len("master_new_"):] in master_fields
        elif name.startswith(("new_", "old_")):
            ok = name[4:] in row_fields
        elif name.startswith("row_") and upper_columns is not None:
            ok = name[4:].upper() in upper_columns
        elif name.startswith("params_") and flow_params is not None:
            ok = name[len("params_"):] in flow_params
        else:
            ok = False
        if not ok:
            run.err(entry, path, f"参数 :{name} 不是 C06 7.2 允许的参数，或者它后面的字段不存在")


def _fragment(run: Run, entry: Entry, path: str, fragment: str, wrapped: str) -> None:
    if has_semicolon(fragment):
        run.err(entry, path, "SQL 片段里不能有分号")
        return
    run.describe(entry, path, wrapped)


def _table_target(run: Run, entry: Entry, path: str, table: str) -> bool:
    """修改表、冻结表、insertRows 的表：在数据库中必须是表，不能是 `PF_` 开头的平台表。"""
    if table.upper().startswith(PLATFORM_PREFIX):
        run.err(entry, path, f"{table} 是平台自己的表，不能修改或冻结")
        return False
    kind = run.object_type(table)
    if kind is None:
        run.err(entry, path, f"表 {table} 在数据库中不存在")
        return False
    if kind != "table":
        run.err(entry, path, f"{table} 是视图，这里只能写表")
        return False
    return True


def check_flow(run: Run, entry: Entry) -> None:
    flow: ApprovalFlowConfig = entry.content
    page = run.catalog.page(flow.page)
    regions = dict(run.catalog.page_regions(flow.page))
    tables = set(regions.values())
    master_code = page.master.entity if page else None
    master_fields = run.entity_fields(master_code) if master_code else {}

    # 审核操作
    row_fields: set[str] = set()
    for code, ops in flow.operations.items():
        if page is not None and code not in tables:
            run.err(entry, f"operations.{code}", f"{code} 不是页面 {flow.page} 的主表实体或明细实体")
            continue
        entity = run.catalog.entity(code)
        if entity is not None and not entity.freezable:
            run.err(entry, f"operations.{code}", f"实体 {code} 的 freezable 为 false，不能作为审批流的表格")
        row_fields |= set(run.entity_fields(code))
    if not any(flow.operations.values()):
        run.err(entry, "operations", "至少一个表格要选一项审核操作")

    # 审批节点
    levels = {level.level for level in flow.levels}
    for i, level in enumerate(flow.levels):
        if level.level != i + 1:
            run.err(entry, f"levels[{i}].level", "级别必须从 1 开始连续")
        if not level.nodes:
            run.err(entry, f"levels[{i}].nodes", "每级至少要有一个节点")
        for j, node in enumerate(level.nodes):
            here = f"levels[{i}].nodes[{j}]"
            if not node.approvers:
                run.err(entry, f"{here}.approvers", "每个节点至少要有一个审批人")
            if node.condition_type == "sql":
                if not node.condition:
                    run.err(entry, f"{here}.condition", "入口条件为 SQL 时必须写 condition")
                else:
                    _params(run, entry, f"{here}.condition", node.condition, row_fields, master_fields)
                    _fragment(run, entry, f"{here}.condition", node.condition, wrap_entry(node.condition))
            if node.department is not None and not run.validator.departments.exists(node.department):
                run.err(entry, f"{here}.department", f"部门 {node.department} 不存在")
            for k, approver in enumerate(node.approvers):
                if isinstance(approver, SqlApprover):
                    run.query(entry, f"{here}.approvers[{k}].sql", approver.sql, approver.binds)

    # 参数
    names = [p.name for p in flow.params]
    for i, param in enumerate(flow.params):
        if param.source == "manual" and param.level is not None and param.level not in levels:
            run.err(entry, f"params[{i}].level", f"级别 {param.level} 不是本审批流已有的级别")
        if param.source == "expression":
            if not isinstance(param.value, str):
                run.err(entry, f"params[{i}].value", "取值为 expression 时 value 必须是 SQL 表达式")
            else:
                _params(run, entry, f"params[{i}].value", param.value, row_fields, master_fields, (), names)
                _fragment(run, entry, f"params[{i}].value", param.value, wrap_value(param.value))

    # 冻结节点
    for i, item in enumerate(flow.freeze):
        here = f"freeze[{i}]"
        if not _table_target(run, entry, f"{here}.table", item.table):
            continue
        registered = run.catalog.entities_on_table(item.table)
        for code in registered:
            if not run.catalog.entity(code).freezable:
                run.err(entry, f"{here}.table", f"{item.table} 属于实体 {code}，它的 freezable 为 false，不能冻结")
        key = run.catalog.entity(registered[0]).primary_key if registered else (run.primary_key(item.table) or "*")
        _params(run, entry, f"{here}.condition", item.condition, row_fields, master_fields)
        _fragment(run, entry, f"{here}.condition", item.condition, wrap_freeze(item.table, key, item.condition))

    # 展示数据
    seen: set[str] = set()
    for i, block in enumerate(flow.display):
        here = f"display[{i}]"
        if block.key in seen:
            run.err(entry, f"{here}.key", f"块的编码 {block.key} 重复")
        seen.add(block.key)
        if block.region == "affected":
            _affected(run, entry, here, block, row_fields, master_fields, names)
        else:
            _source_block(run, entry, here, block, master_code, regions)


def _source_block(run: Run, entry: Entry, here: str, block: DisplayBlock, master: str | None, regions: dict[str, str]) -> None:
    """修改内容的主表块、明细块。"""
    details = {code for region, code in regions.items() if region != "master"}
    if block.region == "master" and block.source != master:
        run.err(entry, f"{here}.source", f"master 块的 source 必须是页面的主表实体 {master}")
    if block.region == "detail" and block.source not in details:
        run.err(entry, f"{here}.source", f"detail 块的 source 必须是页面的明细实体（{'、'.join(sorted(details)) or '无'}）")
    for name in ("target_table", "key_column", "selection"):
        if getattr(block, name) is not None:
            run.err(entry, here, "master、detail 块不写 targetTable、keyColumn、selection、actions")
            break
    else:
        if block.actions:
            run.err(entry, f"{here}.actions", "master、detail 块不写 targetTable、keyColumn、selection、actions")
    fields = run.entity_fields(block.source)
    for j, column in enumerate(block.columns):
        if column.field not in fields:
            run.err(entry, f"{here}.columns[{j}].field", f"字段 {column.field} 不是实体 {block.source} 的字段")
    if block.condition is not None:
        _params(run, entry, f"{here}.condition", block.condition, fields, run.entity_fields(master) if master else {})
        source = run.read_source(block.source)
        if source is not None:
            _fragment(run, entry, f"{here}.condition", block.condition, wrap_display(source, block.condition))


def _affected(run: Run, entry: Entry, here: str, block: DisplayBlock, row_fields: set[str], master_fields: dict,
              params: list[str]) -> None:
    """受影响单据的块。"""
    if block.condition is None:
        run.err(entry, f"{here}.condition", "受影响单据的块必须写 condition")
    if block.selection is None:
        run.err(entry, f"{here}.selection", "受影响单据的块必须写 selection")
    kind = run.object_type(block.source)
    if kind is None:
        run.err(entry, f"{here}.source", f"表或视图 {block.source} 在数据库中不存在")
        return
    source_columns = {c.upper() for c in (run.columns(block.source) or {})}
    if kind == "view" and (block.target_table is None or block.key_column is None):
        run.err(entry, here, "source 是视图时必须写 targetTable 和 keyColumn")
        return
    target = block.target_table or block.source
    if not _table_target(run, entry, f"{here}.targetTable" if block.target_table else f"{here}.source", target):
        return
    target_columns = {c.upper() for c in (run.columns(target) or {})}
    if block.key_column is not None and block.key_column.upper() not in source_columns:
        run.err(entry, f"{here}.keyColumn", f"列 {block.key_column} 不在 {block.source} 中")
    if block.key_column is None and run.primary_key(target) is None:
        run.err(entry, f"{here}.keyColumn", f"表 {target} 没有单列主键，必须写 keyColumn")
    registered = run.catalog.entities_on_table(target)
    masters = {run.catalog.parent_of(code)[0] if run.catalog.parent_of(code) else code for code in registered}
    for j, column in enumerate(block.columns):
        at = f"{here}.columns[{j}]"
        if column.field.startswith("master."):
            name = column.field.removeprefix("master.")
            if not registered:
                run.err(entry, f"{at}.field", f"修改表 {target} 没有在平台注册，不能用 master. 列")
            elif not any(name in run.entity_fields(m) for m in masters):
                run.err(entry, f"{at}.field", f"字段 {name} 不属于修改表所属的主表实体")
        elif column.field.upper() not in source_columns:
            run.err(entry, f"{at}.field", f"列 {column.field} 不在 {block.source} 中")
        if column.target_column is not None and column.target_column.upper() not in target_columns:
            run.err(entry, f"{at}.targetColumn", f"列 {column.target_column} 不在修改表 {target} 中")
    if block.condition is not None:
        _params(run, entry, f"{here}.condition", block.condition, row_fields, master_fields)
        _fragment(run, entry, f"{here}.condition", block.condition, wrap_display(block.source, block.condition))
    protected = {f.column.upper(): f for code in registered for f in run.catalog.entity(code).fields
                 if f.column and (f.role == "calculated" or f.source == "erp")}
    for k, action in enumerate(block.actions):
        at = f"{here}.actions[{k}]"
        if isinstance(action, UpdateFields):
            for m, write in enumerate(action.fields):
                if write.column.upper() not in target_columns:
                    run.err(entry, f"{at}.fields[{m}].column", f"列 {write.column} 不在修改表 {target} 中")
                elif write.column.upper() in protected:
                    what = "计算字段" if protected[write.column.upper()].role == "calculated" else "ERP 列"
                    run.err(entry, f"{at}.fields[{m}].column", f"{write.column} 是{what}，不能写")
                _value(run, entry, f"{at}.fields[{m}].value", write.value, row_fields, master_fields, target_columns, params)
        elif isinstance(action, InsertRows):
            if _table_target(run, entry, f"{at}.table", action.table):
                columns = {c.upper() for c in (run.columns(action.table) or {})}
                for m, write in enumerate(action.fields):
                    if write.column.upper() not in columns:
                        run.err(entry, f"{at}.fields[{m}].column", f"列 {write.column} 不在表 {action.table} 中")
                    _value(run, entry, f"{at}.fields[{m}].value", write.value, row_fields, master_fields, target_columns, params)
        elif isinstance(action, EscapeHatch):
            operation = run.catalog.operation(action.operation)
            if operation is not None and operation.kind != "escapeHatch":
                run.err(entry, f"{at}.operation", f"操作 {action.operation} 不是逃生舱操作")
        else:
            assert isinstance(action, DeleteRows)


def _value(run: Run, entry: Entry, path: str, value: str, row_fields: set[str], master_fields: dict, columns: set[str],
           params: list[str]) -> None:
    _params(run, entry, path, value, row_fields, master_fields, columns, params)
    _fragment(run, entry, path, value, wrap_value(value))
