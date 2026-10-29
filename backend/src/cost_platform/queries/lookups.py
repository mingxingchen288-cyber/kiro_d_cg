"""Lookup（QE-09、QE-11）和字典（C09 第 4 节），对应旧系统 `DynamicDataService.queryLookupData` 和
`MetadataService.getDictItems`。

Lookup：关键字先去掉首尾空白；为空时返回全部候选，不为空时在 `keywordColumns` 中按包含匹配（各列之间为或，大小写敏感，
与旧系统相同）；`keywordColumns` 为空表示不支持关键字搜索，这时关键字不为空返回 400。`filter` 只查 `column` 等于值的行，
`column` 必须是 Lookup 的列，值为空时不过滤。一条查总数、一条查行；按 `orderBy` 排序，没有配置时按第一列排序（旧系统没有
排序，分页不稳定）。访问要求与其他查询接口相同，Lookup 不另设权限，也不加行权限。
"""

from __future__ import annotations

from sqlalchemy import text

from cost_platform.contracts.ports import UnitOfWorkFactory
from cost_platform.contracts.types import (
    DictItem,
    DictResponse,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    LookupRow,
    LookupSearchRequest,
    LookupSearchResponse,
    PlatformError,
)

from .catalog import CatalogOf
from .sql import Binds, as_text, dialect, escape_like, page_binds, page_clause, where_sql, wire_text


class LookupQueries:
    def __init__(self, uow_factory: UnitOfWorkFactory, catalog: CatalogOf) -> None:
        self._uow = uow_factory
        self._catalog = catalog

    def search(self, ctx: ExecutionContext, lookup_code: str, request: LookupSearchRequest) -> LookupSearchResponse:
        config = self._catalog(ctx).lookup(lookup_code)
        if config is None:
            raise PlatformError(ErrorCode.NOT_FOUND, f"Lookup {lookup_code} 不存在")
        keyword = request.keyword.strip()
        searchable = bool(config.keyword_columns)
        if keyword and not searchable:
            raise PlatformError(ErrorCode.INVALID_REQUEST, f"Lookup {lookup_code} 不支持按关键字搜索")
        if request.filter is not None and request.filter.column not in config.columns:
            message = f"{request.filter.column} 不是 Lookup {lookup_code} 的列"
            raise PlatformError(ErrorCode.VALIDATION_FAILED, message, [ErrorDetail(field=request.filter.column, message=message)])
        with self._uow.begin() as uow:
            name = dialect(uow)
            binds = Binds()
            clauses = []
            value = None if request.filter is None else request.filter.value
            if request.filter is not None and value is not None and value.strip():
                clauses.append(f"q.{request.filter.column} = {binds.add(value)}")
            if keyword:
                pattern = binds.add(f"%{escape_like(keyword)}%")
                matches = " OR ".join(f"{as_text(name, 'q.' + c)} LIKE {pattern} ESCAPE '\\'" for c in config.keyword_columns)
                clauses.append(f"({matches})")
            where = where_sql(clauses)
            total = uow.connection.execute(text(f"SELECT COUNT(*) FROM {config.table} q{where}"), binds.values).scalar()
            order = config.order_by or config.columns[0]
            columns = ", ".join(f"q.{c}" for c in config.columns)
            sql = f"SELECT {columns} FROM {config.table} q{where} ORDER BY {order} {page_clause(name)}"
            records = uow.connection.execute(text(sql), {**binds.values, **page_binds(request.start_row, request.end_row)}).all()
        rows = [LookupRow(values={c: wire_text(v) for c, v in zip(config.columns, r, strict=True)}) for r in records]
        return LookupSearchResponse(rows=rows, total=int(total or 0), keyword_search=searchable)


class DictQueries:
    def __init__(self, catalog: CatalogOf) -> None:
        self._catalog = catalog

    def items(self, ctx: ExecutionContext, dict_type: str) -> DictResponse:
        """按 `order` 排列；类型不存在时 `items` 为空。"""
        config = self._catalog(ctx).dict_config(dict_type)
        if config is None:
            return DictResponse(items=[])
        return DictResponse(items=[DictItem(value=i.value, label=i.label) for i in sorted(config.items, key=lambda i: i.order)])
