"""导出（QE-06，C06 第 9 节），对应旧系统 `export/service/CustomExportService.java`。

两种方式：
- 默认导出当前页面（`mode: page`）：能打开页面就能导出。按请求中的筛选、高级查询、行权限和排序导出主表的全部满足条件的行，
  行和顺序与列表相同（同一套条件和排序，不分页）；列为请求中的列，必须对当前角色可见，否则 422。一张工作表，名称为页面标题，
  第一行为字段标题。
- 按导出配置（`mode: config`）：authz 的 `can_export` 为 true 才能使用，否则 403。配置的 SQL 不改动，外面包一层：
  `scope` 为 `current` 时按当前查询条件和行权限、为 `all` 时只按行权限，用 `EXISTS (SELECT 1 FROM 页面主表 a WHERE
  a.主键 = q.keyColumn AND 条件)` 限定（与旧系统 buildPageExistsClause 相同，旧系统 all 不限定，新契约改为按行权限）；
  没有任何条件时不限定。外层用行号保持 SQL 自己的顺序；SQL 没有 ORDER BY 且请求的排序字段是导出列时按它排序（旧系统
  appendOrderByClause）。明细 SQL 同样按 `linkColumn` 限定。

版式与旧系统相同（见 xlsx.py 的样式说明）：主表一张工作表；`perMaster` 时每张有明细的主单一张"明细_<主单主键>"，块依次为
标题行"【明细 sheet】"、表头行、数据行，块之间空一行；主表中 keyColumn 所在列的单元格链接到这张主单的明细工作表，明细工作表
标题行的第一格和 linkColumn 所在列的单元格链接回主表对应的行。`perDetail` 时每个明细配置一张工作表。
链接列按旧系统 resolveLinkColumnIndex 定位：先按导出列的 `field`（去掉下划线、不区分大小写），再按 `header`，再按前 20 行
的值推断唯一相等的列（cost-pinggu-export 的 DOCID 不在导出列中，推断到 "Summary ID"）。
表头为一行，`header` 原样写出（旧系统不按 `/` 拆多级表头，cost-pinggu-export 的表头本身含 `/`），不加粗。

读取：在只读事务中（Oracle 为 `SET TRANSACTION READ ONLY`，主表和明细的多条查询看到同一时点的数据，导出期间其他提交
不造成重复或遗漏），每条查询按批读取（`yield_per`）。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote

from sqlalchemy import text

from cost_platform.contracts.ports import PermissionChecker, UnitOfWork, UnitOfWorkFactory
from cost_platform.contracts.types import (
    ConfigExportRequest,
    EntityField,
    ErrorCode,
    ExecutionContext,
    ExportColumn,
    ExportConfig,
    ExportItem,
    ExportList,
    PageExportRequest,
    PlatformError,
    Value,
)
from cost_platform.contracts.values import to_wire

from .catalog import CatalogOf
from .lists import PageScope, master_clauses, page_scope
from .sql import Binds, Columns, Conditions, db_value, dialect, key_text, order_sql, row_number, row_values, where_sql
from .xlsx import BLOCK_HEADER, BODY, HEADER, LINK, Cell, Sheet, Workbook, location

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BATCH = 1000
_SIMPLE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")
_SHEET_CHARS = re.compile(r"[\\/?*\[\]:]")


@dataclass(frozen=True)
class ExportFile:
    file_name: str
    content: bytes

    @property
    def content_disposition(self) -> str:
        return f"attachment; filename*=UTF-8''{quote(self.file_name, safe='')}"


def _cell_text(value: Value | object) -> str | bool | None:
    """导出 SQL 的值：数值为十进制文本，日期时间为 yyyy-MM-dd HH:mm:ss，日期为 yyyy-MM-dd（与旧系统 normalizeCellValue 相同）。"""
    value = db_value(value)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return key_text(value)


def _field_text(field: EntityField, value: Value) -> str | bool | None:
    """默认导出的值按字段类型：数值为十进制文本，日期时间与旧系统相同写成 yyyy-MM-dd HH:mm:ss，是非为是非单元格。"""
    if value is None or field.type == "boolean":
        return None if value is None else bool(value)
    if field.type == "datetime" and isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    wire = to_wire(field.type, value)
    return None if wire is None else str(wire)


def _ref(name: str) -> str:
    """包装查询中引用 SQL 结果的列：简单标识符原样（Oracle 按大写），其他加双引号（例如 "Summary ID"）。"""
    return name if _SIMPLE.match(name) else '"' + name.replace('"', '""') + '"'


def sanitize_sheet_name(name: str) -> str:
    cleaned = _SHEET_CHARS.sub("_", name).strip() or "detail"
    return cleaned[:31]


def unique_sheet_name(name: str, used: set[str]) -> str:
    """重名时加 _1、_2……，总长不超过 31（旧系统 ensureUniqueSheetName）。"""
    candidate, suffix = name, 1
    while candidate in used:
        extra = f"_{suffix}"
        candidate = name[:31 - len(extra)] + extra
        suffix += 1
    used.add(candidate)
    return candidate


def _link_value(value: object) -> str | None:
    if value is None:
        return None
    text_value = key_text(value).strip()
    return text_value or None


def _normalize_column(name: str | None) -> str | None:
    return None if not name else name.replace("_", "").strip().upper()


@dataclass
class _Rows:
    """一条导出 SQL 的结果：导出列的值（单元格）和链接列的值。"""

    columns: list[ExportColumn]
    cells: list[list[str | bool | None]]
    links: list[str | None]

    def link_index(self, link_column: str) -> int:
        """链接列在导出列中的位置（旧系统 resolveLinkColumnIndex）；找不到时为 -1。"""
        target = _normalize_column(link_column)
        for attr in ("field", "header"):
            for i, column in enumerate(self.columns):
                if _normalize_column(getattr(column, attr)) == target:
                    return i
        candidates: set[int] | None = None
        samples = 0
        for cells, key in zip(self.cells, self.links, strict=True):
            if key is None:
                continue
            matched = {i for i, v in enumerate(cells) if v is not None and not isinstance(v, bool) and v.strip() == key}
            candidates = matched if candidates is None else candidates & matched
            if not candidates:
                return -1
            samples += 1
            if samples >= 20:
                break
        return next(iter(candidates)) if candidates is not None and len(candidates) == 1 else -1


class Exports:
    def __init__(self, uow_factory: UnitOfWorkFactory, permission: PermissionChecker, catalog: CatalogOf,
                 *, batch_size: int = BATCH) -> None:
        self._uow = uow_factory
        self._permission = permission
        self._catalog = catalog
        self._batch = batch_size

    def available(self, ctx: ExecutionContext, page_code: str) -> ExportList:
        """当前角色可用的导出配置（C09 第 4 节）。"""
        ctx.config.page_view(page_code)
        configs = self._catalog(ctx).exports(page_code)
        return ExportList(items=[ExportItem(export_code=code, name=cfg.name) for code, cfg in configs.items()
                                 if self._permission.can_export(ctx, page_code, code)])

    def export(self, ctx: ExecutionContext, page_code: str, request: PageExportRequest | ConfigExportRequest) -> ExportFile:
        if isinstance(request, PageExportRequest):
            return self._page(ctx, page_code, request)
        return self._config(ctx, page_code, request)

    # ---------------------------------------------------------------- 默认导出当前页面

    def _page(self, ctx: ExecutionContext, page_code: str, request: PageExportRequest) -> ExportFile:
        scope = page_scope(ctx, page_code)
        source = scope.source
        fields = [scope.master.field(name) for name in request.columns]
        labels = {f.name: f.label for f in scope.view.master.fields}
        workbook = Workbook()
        sheet = workbook.sheet(sanitize_sheet_name(scope.view.title))
        sheet.append([Cell(labels.get(f.name, f.label), HEADER) for f in fields])
        with self._uow.begin() as uow:
            name = self._read_only(uow)
            binds = Binds()
            where = where_sql(master_clauses(self._permission, ctx, page_code, scope, binds, Conditions(binds, name), request.request))
            sql = f"SELECT {source.select_list('a')} FROM {source.name} a{where} ORDER BY {order_sql(scope.master, request.request.sort_model)}"
            ordered = source.ordered()
            for record in uow.connection.execute(text(sql), binds.values, execution_options={"yield_per": self._batch}):
                values = row_values(ordered, record)
                sheet.append([Cell(_field_text(f, values[f.name])) for f in fields])
        return ExportFile(file_name=f"{scope.view.title}.xlsx", content=workbook.to_bytes())

    # ---------------------------------------------------------------- 按导出配置

    def _config(self, ctx: ExecutionContext, page_code: str, request: ConfigExportRequest) -> ExportFile:
        if not self._permission.can_export(ctx, page_code, request.export_code):
            raise PlatformError(ErrorCode.PERMISSION_DENIED, f"没有导出 {request.export_code} 的权限")
        scope = page_scope(ctx, page_code)
        config = self._catalog(ctx).exports(page_code).get(request.export_code)
        if config is None:
            raise PlatformError(ErrorCode.NOT_FOUND, f"导出配置 {request.export_code} 不存在")
        with self._uow.begin() as uow:
            name = self._read_only(uow)
            binds = Binds()
            limited = request.request if request.scope == "current" else None
            clauses = master_clauses(self._permission, ctx, page_code, scope, binds, Conditions(binds, name), limited)
            sorts = [(item.col_id, item.sort) for item in request.request.sort_model]
            master = self._rows(uow, name, scope, config.master.sql, config.master.key_column, config.master.columns,
                                clauses, binds, sorts)
            details = [(d.sheet, d.link_column, self._rows(uow, name, scope, d.sql, d.link_column, d.columns, clauses, binds, []))
                       for d in config.details]
        return ExportFile(file_name=f"{config.file_name}.xlsx", content=_layout(config, master, details).to_bytes())

    def _rows(self, uow: UnitOfWork, dialect_name: str, scope: PageScope, sql: str, link_column: str,
              columns: list[ExportColumn], clauses: Sequence[str], binds: Binds, sorts: Sequence[tuple[str, str]]) -> _Rows:
        source = scope.source
        numbered = f"SELECT qe_src.*, {row_number(dialect_name)} AS QE_RN FROM ({sql}) qe_src"
        where = ""
        if clauses:
            where = (f" WHERE EXISTS (SELECT 1 FROM {source.name} a WHERE {source.column(source.entity.primary_key, 'a')} "
                     f"= q.{_ref(link_column)} AND {' AND '.join(clauses)})")
        order = ["QE_RN"]
        if sorts and " ORDER BY " not in f" {' '.join(sql.upper().split())} ":
            fields = {c.field.casefold(): c.field for c in columns}
            order = [f"q.{_ref(fields[col.casefold()])} {direction.upper()}" for col, direction in sorts
                     if col.casefold() in fields] + order
        result = uow.connection.execute(text(f"SELECT * FROM ({numbered}) q{where} ORDER BY {', '.join(order)}"), binds.values,
                                        execution_options={"yield_per": self._batch})
        names = Columns(result.keys())
        positions = [names.index(c.field) for c in columns]
        link = names.index(link_column)
        rows = _Rows(columns=columns, cells=[], links=[])
        for record in result:
            rows.cells.append([None if p is None else _cell_text(record[p]) for p in positions])
            rows.links.append(None if link is None else _link_value(record[link]))
        return rows

    @staticmethod
    def _read_only(uow: UnitOfWork) -> str:
        name = dialect(uow)
        if name == "oracle":
            uow.connection.execute(text("SET TRANSACTION READ ONLY"))
        return name


def _layout(config: ExportConfig, master: _Rows, details: list[tuple[str, str, _Rows]]) -> Workbook:
    workbook = Workbook(config.font)
    used: set[str] = set()
    master_name = unique_sheet_name(sanitize_sheet_name(config.master.sheet or "master"), used)
    master_sheet = workbook.sheet(master_name)
    first_row: dict[str, int] = {}
    for i, key in enumerate(master.links):
        if key is not None:
            first_row.setdefault(key, i)
    head_rows = 1

    def back(key: str | None) -> str | None:
        """链接回主表中这张主单的第一行。"""
        return None if key is None or key not in first_row else location(master_name, first_row[key] + head_rows)

    targets: dict[str, str] = {}
    detail_sheets: list[tuple[Sheet, list[tuple[str, _Rows, list[int]]], str | None]] = []
    if config.detail_layout == "perMaster":
        grouped = [(title, link, rows, _group(rows)) for title, link, rows in details]
        for key in master.links:
            if key is None:
                continue
            blocks = [(title, rows, groups[key]) for title, _, rows, groups in grouped if groups.get(key)]
            if not blocks:
                continue
            name = unique_sheet_name(sanitize_sheet_name(f"明细_{key}"), used)
            targets.setdefault(key, location(name, 0))
            detail_sheets.append((Sheet(name), blocks, key))
    else:
        for title, _, rows in details:
            name = unique_sheet_name(sanitize_sheet_name(title), used)
            for i, key in enumerate(rows.links):
                if key is not None:
                    targets.setdefault(key, location(name, i + head_rows))
            detail_sheets.append((Sheet(name), [(title, rows, list(range(len(rows.cells))))], None))

    link_at = master.link_index(config.master.key_column)
    master_sheet.append([Cell(c.header or c.field, HEADER) for c in master.columns])
    for cells, key in zip(master.cells, master.links, strict=True):
        master_sheet.append(_cells(cells, link_at, None if key is None else targets.get(key)))

    links = {title: link for title, link, _ in details}
    for sheet, blocks, key in detail_sheets:
        workbook.sheets.append(sheet)
        first_title, first_rows, first_index = blocks[0]
        link_at = _subset(first_rows, first_index).link_index(links[first_title])
        if key is None:  # perDetail
            sheet.append([Cell(c.header or c.field, HEADER) for c in first_rows.columns])
            for i in first_index:
                sheet.append(_cells(first_rows.cells[i], link_at, back(first_rows.links[i])))
            continue
        for number, (title, rows, index) in enumerate(blocks):
            sheet.append([Cell(f"【{title}】", LINK if back(key) else BODY, back(key))])
            sheet.append([Cell(c.header or c.field, BLOCK_HEADER) for c in rows.columns])
            for i in index:
                sheet.append(_cells(rows.cells[i], link_at, back(rows.links[i])))
            if number < len(blocks) - 1:
                sheet.append([Cell("")])
    return workbook


def _group(rows: _Rows) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for i, key in enumerate(rows.links):
        if key is not None:
            groups.setdefault(key, []).append(i)
    return groups


def _subset(rows: _Rows, index: Iterable[int]) -> _Rows:
    picked = list(index)
    return _Rows(columns=rows.columns, cells=[rows.cells[i] for i in picked], links=[rows.links[i] for i in picked])


def _cells(values: Sequence[str | bool | None], link_at: int, target: str | None) -> list[Cell]:
    return [Cell(v, LINK, target) if i == link_at and target and v is not None else Cell(v) for i, v in enumerate(values)]
