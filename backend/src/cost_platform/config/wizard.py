"""新建页面向导（CF-14、C09 第 3 节），对照旧系统 `metadata/service/WizardGenerateService.generate` 和
`cost-web/src/views/_builtin/meta-config/panels/composables/useWizardState.ts`。

- 读结构：视图（没有视图时为表）的每一列生成一个实体字段；表中也有的列 `column` 为同名列，表中没有的列 `column` 为 null，
  只读显示（旧系统的虚拟列）。类型按 Oracle 的数据类型：NUMBER、FLOAT、INTEGER 等为 number，DATE 为 date，TIMESTAMP 为
  datetime，其余为 text（旧系统把 TIMESTAMP 也当日期，这里保留时间）。标题取列名：`ColumnInfo` 没有列注释（旧系统取注释，
  没有注释时取列名；cmx 的这些表都没有注释），见 contract-gaps。
- 主键取表的主键；序列 `<表名>_SEQ` 必须已经存在，不存在时 422，平台不执行 DDL（旧系统会自动建序列，新平台改为由用户建）。
- 生成：实体（主表和明细）、页面、页面的保存操作 `<页面编码>.save`，在 `parentMenu` 分组下加菜单项，在 ADMIN 角色中加
  这个页面的 `*` 权限；同一个事务写入，配置代号只加一。默认按钮与旧系统相同：主表区"新增、删除、保存列配置"，
  明细区"明细新增、明细删除、保存列配置"（查询、保存是页面级按钮）。

请求中 `master`、`details[]` 的写法（C09 只写了"实体"，见 contract-gaps）：
`{"entity": 实体编码, "name": 实体名称, "table": 表名, "readView": 视图名或 null, "freezable": true,
  "erpRow": {"column", "value", "localValue"} 或省略, "erpColumns": [ERP 列], "labels": {列名: 标题}}`，
明细另有 `"title"`（明细区标题）和 `"parentKey"`（关联主表的字段）。
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from cost_platform.contracts.ports import SchemaInspector, UnitOfWork
from cost_platform.contracts.types import (
    ColumnInfo,
    ConfigDraft,
    ErrorCode,
    ErrorDetail,
    FieldType,
    PlatformError,
    SchemaColumn,
    SchemaColumnsResponse,
    WizardColumn,
    WizardColumnsRequest,
    WizardColumnsResponse,
    WizardGenerateRequest,
    WizardSequence,
)

from .catalog import Catalog
from .deps import SequenceChecker
from .service import ADMIN_ROLE, Change, validation_failed

GRID = {"sideBar": True, "cellSelection": True, "groupBy": []}
MASTER_BUTTONS = [{"action": "addRow", "label": "新增"}, {"action": "deleteRow", "label": "删除"},
                  {"action": "saveGridConfig", "label": "保存列配置"}]
DETAIL_BUTTONS = [{"action": "addRow", "label": "明细新增"}, {"action": "deleteRow", "label": "明细删除"},
                  {"action": "saveGridConfig", "label": "保存列配置"}]
_NUMBER_TYPES = ("NUMBER", "FLOAT", "DECIMAL", "INTEGER", "BINARY_FLOAT", "BINARY_DOUBLE", "NUMERIC", "INT")


def column_type(info: ColumnInfo) -> FieldType:
    upper = info.data_type.upper()
    if upper.startswith(_NUMBER_TYPES):
        return "number"
    if upper.startswith("TIMESTAMP"):
        return "datetime"
    if upper.startswith("DATE"):
        return "date"
    return "text"


def _invalid(message: str, path: str | None = None) -> PlatformError:
    return PlatformError(ErrorCode.VALIDATION_FAILED, message, [ErrorDetail(message=message, path=path)])


def schema_columns(schema: SchemaInspector, name: str) -> SchemaColumnsResponse:
    """读表或视图的结构（审批流配置用）；不存在时 `objectType` 为 null、`columns` 为空。"""
    kind = schema.object_type(name)
    columns = schema.columns(name) or {}
    return SchemaColumnsResponse(object_type=kind, primary_key=schema.primary_key(name) if kind == "table" else None,
                                 columns=[SchemaColumn(name=c.name, type=column_type(c)) for c in columns.values()])


def _structure(schema: SchemaInspector, table: str, read_view: str | None, path: str) -> tuple[dict[str, ColumnInfo], dict[str, ColumnInfo], str]:
    if schema.object_type(table) != "table":
        raise _invalid(f"表 {table} 在数据库中不存在（或不是表）", f"{path}.table")
    table_columns = schema.columns(table) or {}
    source = table_columns
    if read_view:
        found = schema.columns(read_view)
        if found is None:
            raise _invalid(f"视图 {read_view} 在数据库中不存在", f"{path}.readView")
        source = found
    key = schema.primary_key(table)
    if key is None:
        raise _invalid(f"表 {table} 没有单列主键", f"{path}.table")
    return table_columns, source, key


def wizard_columns(schema: SchemaInspector, sequences: SequenceChecker, uow: UnitOfWork,
                   request: WizardColumnsRequest) -> WizardColumnsResponse:
    """读取视图和表的结构，只读，不写任何东西（C09 第 3 节）。"""
    table_columns, source, key = _structure(schema, request.table, request.read_view, "")
    sequence = f"{request.table}_SEQ"
    return WizardColumnsResponse(
        primary_key=key, sequence=WizardSequence(name=sequence, exists=sequences.exists(uow, sequence)),
        columns=[WizardColumn(name=c.name, type=column_type(c), label=c.name, in_table=c.name in table_columns)
                 for c in source.values()])


def _text(spec: Mapping[str, Any], name: str, path: str, required: bool = True) -> str | None:
    value = spec.get(name)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value:
        raise _invalid(f"缺少 {name}", f"{path}.{name}")
    return value


def _entity(schema: SchemaInspector, spec: Mapping[str, Any], path: str, parent_key: str | None,
            details: list[dict[str, str]]) -> tuple[str, str, dict[str, Any]]:
    code = _text(spec, "entity", path)
    table = _text(spec, "table", path)
    read_view = _text(spec, "readView", path, required=False)
    assert code is not None and table is not None
    table_columns, source, key = _structure(schema, table, read_view, path)
    labels = spec.get("labels") or {}
    erp_columns = set(spec.get("erpColumns") or [])
    fields = []
    for info in source.values():
        role = "system" if info.name in (key, parent_key) else "input"
        field: dict[str, Any] = {"name": info.name, "column": info.name if info.name in table_columns else None,
                                 "label": labels.get(info.name, info.name), "type": column_type(info),
                                 "source": "erp" if info.name in erp_columns else "own", "role": role}
        if field["type"] == "number" and info.scale is not None:
            field["scale"] = info.scale
        fields.append(field)
    content: dict[str, Any] = {"table": table, "primaryKey": key, "freezable": spec.get("freezable", True), "fields": fields}
    if read_view:
        content["readView"] = read_view
    if spec.get("erpRow"):
        content["erpRow"] = spec["erpRow"]
    if details:
        content["details"] = details
    return code, str(spec.get("name") or code), content


def writable_fields(entity: Mapping[str, Any], parent_key: str | None) -> list[str]:
    """保存操作可写的字段（CF-14）：`role` 为 input、`column` 不为 null、不是主键、主从关联字段和 `erpRow.column`；
    没有 `erpRow` 的实体不含 ERP 列。生成的实体和页面没有设为不可编辑的字段。"""
    erp_row = entity.get("erpRow")
    skip = {entity["primaryKey"], parent_key, erp_row["column"] if erp_row else None}
    return [f["name"] for f in entity["fields"]
            if f["role"] == "input" and f["column"] is not None and f["name"] not in skip
            and not (f["source"] == "erp" and not erp_row)]


def _find_group(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("key") == key and item.get("kind") == "group":
            return item
        found = _find_group(item.get("children") or [], key)
        if found is not None:
            return found
    return None


def _has_page(items: list[dict[str, Any]], page_code: str) -> bool:
    return any(item.get("pageCode") == page_code or _has_page(item.get("children") or [], page_code) for item in items)


def generate(schema: SchemaInspector, request: WizardGenerateRequest, catalog: Catalog) -> Change:
    """按请求生成一套能查询、编辑、保存的配置（CF-14）；由 `ConfigService.commit` 在一个事务中校验并写入。"""
    page_code = request.page_code
    operation_code = f"{page_code}.save"
    detail_specs = [(f"details[{i}]", d) for i, d in enumerate(request.details)]
    if request.layout == "single" and detail_specs:
        raise _invalid("单表页不能有明细", "details")
    links = []
    for path, spec in detail_specs:
        links.append({"entity": _text(spec, "entity", path), "parentKey": _text(spec, "parentKey", path)})
    master_code, master_name, master = _entity(schema, request.master, "master", None, links)
    entities = [(master_code, master_name, master, None)]
    for (path, spec), link in zip(detail_specs, links, strict=True):
        code, name, content = _entity(schema, spec, path, link["parentKey"], [])
        entities.append((code, name, content, link["parentKey"]))

    problems = []
    for code, *_ in entities:
        if catalog.has("entity", code):
            problems.append(ErrorDetail(message=f"实体 {code} 已存在，向导不覆盖已有配置", config_type="entity", config_key=code))
    if catalog.has("page", page_code):
        problems.append(ErrorDetail(message=f"页面 {page_code} 已存在，向导不覆盖已有配置", config_type="page", config_key=page_code))
    if catalog.has("operation", operation_code):
        problems.append(ErrorDetail(message=f"操作 {operation_code} 已存在，向导不覆盖已有配置", config_type="operation",
                                    config_key=operation_code))
    menus = [(e.key, e) for e in catalog if e.type == "menu"]
    if any(_has_page(e.raw.get("items", []), page_code) for _, e in menus):
        problems.append(ErrorDetail(message=f"菜单中已有页面 {page_code}", config_type="menu"))
    menu_entry = next(((key, e) for key, e in menus if _find_group(e.raw.get("items", []), request.parent_menu)), None)
    if menu_entry is None:
        problems.append(ErrorDetail(message=f"菜单分组 {request.parent_menu} 不存在", path="parentMenu"))
    admin = catalog.get("role", ADMIN_ROLE)
    if admin is None:
        problems.append(ErrorDetail(message="没有 ADMIN 角色配置", config_type="role", config_key=ADMIN_ROLE))
    elif page_code in admin.raw.get("pages", {}):
        problems.append(ErrorDetail(message=f"ADMIN 角色中已有页面 {page_code}", config_type="role", config_key=ADMIN_ROLE))
    if problems:
        raise validation_failed(problems)
    assert menu_entry is not None and admin is not None

    page: dict[str, Any] = {
        "title": request.title, "layout": request.layout, "detailMode": request.detail_mode, "audit": request.audit,
        "saveOperation": operation_code,
        "master": {"entity": master_code, "buttons": copy.deepcopy(MASTER_BUTTONS), "grid": copy.deepcopy(GRID)},
    }
    if detail_specs:
        page["details"] = [{"entity": code, "title": str(spec.get("title") or name), "buttons": copy.deepcopy(DETAIL_BUTTONS),
                            "grid": copy.deepcopy(GRID)}
                           for (code, name, _, _), (_, spec) in zip(entities[1:], detail_specs, strict=True)]
    operation = {"label": "保存", "kind": "save",
                 "writableFields": {code: writable_fields(content, parent) for code, _, content, parent in entities},
                 "impact": [code for code, *_ in entities], "propagation": "continue"}
    menu_key, menu = menu_entry
    menu_content = copy.deepcopy(menu.raw)
    group = _find_group(menu_content["items"], request.parent_menu)
    assert group is not None
    group.setdefault("children", []).append({"key": page_code, "title": request.title, "kind": "page", "pageCode": page_code})
    admin_content = copy.deepcopy(admin.raw)
    admin_content.setdefault("pages", {})[page_code] = {"buttons": ["*"]}

    drafts = [ConfigDraft(type="entity", key=code, name=name, content=content) for code, name, content, _ in entities]
    drafts += [ConfigDraft(type="page", key=page_code, name=request.title, content=page),
               ConfigDraft(type="operation", key=operation_code, name=f"{request.title}保存", content=operation),
               ConfigDraft(type="menu", key=menu_key, name=menu.name, content=menu_content),
               ConfigDraft(type="role", key=ADMIN_ROLE, name=admin.name, content=admin_content)]
    return Change(drafts=drafts)


def merge_columns(entity: Mapping[str, Any], table_columns: Mapping[str, ColumnInfo],
                  source_columns: Mapping[str, ColumnInfo]) -> tuple[dict[str, Any], list[str]]:
    """已有实体从视图重新导入列（CF-14 最后一条）：新列加入，已有列的设置不变；返回新的实体内容和视图中已删除的列，
    由管理员处理。C09 没有为它单列接口，前端可以用 `wizard/columns` 读出结构后，按同样的规则合并再保存实体。"""
    content = copy.deepcopy(dict(entity))
    existing = {f["name"] for f in content["fields"]}
    for info in source_columns.values():
        if info.name in existing:
            continue
        field: dict[str, Any] = {"name": info.name, "column": info.name if info.name in table_columns else None,
                                 "label": info.name, "type": column_type(info), "source": "own", "role": "input"}
        if field["type"] == "number" and info.scale is not None:
            field["scale"] = info.scale
        content["fields"].append(field)
    removed = [f["name"] for f in content["fields"] if f["name"] not in source_columns]
    return content, removed
