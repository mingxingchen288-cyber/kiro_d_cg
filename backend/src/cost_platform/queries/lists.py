"""列表（QE-01–QE-05）、按主键取行和单据加载（C09 第 4 节的前三个接口）。

列表：页面视图 → 校验筛选和排序字段（只能用可见字段，QE-02）→ 生成 SQL（行权限 AND 筛选 AND 高级查询，排序加主键，分页）
→ 一条查总数和汇总、一条查行 → 标记冻结（QE-05）→ 对比（QE-10）→ 返回。只读，不加锁。

单据加载：在一个只读事务中查主表行（带行权限条件），再按主从关联字段查每个明细，明细按主键排序；明细经 readView 读取。
明细随主表：行权限只加在主表上（与旧系统相同），被冻结的单据主表和全部明细都标为冻结（C08 第 1 节 FreezeEntry）。

对应旧系统 `DynamicDataService.query`、`getById`。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import text

from cost_platform.contracts.ports import FreezeReader, PermissionChecker, UnitOfWork, UnitOfWorkFactory
from cost_platform.contracts.types import (
    ByKeysRequest,
    DataRow,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    FrozenMark,
    ListRequest,
    ListResponse,
    PageView,
    PlatformError,
    RecordResponse,
    RowsResponse,
    Value,
)
from cost_platform.contracts.values import to_wire

from .catalog import CatalogOf
from .compare import compare_rows
from .sql import (
    Binds,
    Conditions,
    Scope,
    Source,
    advanced_sql,
    batches,
    dialect,
    filter_model_sql,
    key_text,
    number,
    order_sql,
    page_binds,
    page_clause,
    row_condition_sql,
    row_values,
    to_data_row,
    where_sql,
)


@dataclass(frozen=True)
class PageScope:
    """一个页面在当前角色下可查询的范围：主表别名 `a`，明细别名 `d0`、`d1`……"""

    view: PageView
    master: Scope
    details: dict[str, tuple[Scope, str]]
    """明细实体 ->（范围，明细中关联主表的字段）。"""

    @property
    def source(self) -> Source:
        return self.master.source

    @property
    def root_table(self) -> str:
        """冻结记录的根表：页面主表实体的表（C08 第 1 节）。"""
        return self.master.source.entity.table


def page_scope(ctx: ExecutionContext, page_code: str) -> PageScope:
    """页面不存在为 404、角色不能访问为 403（由配置快照的 page_view 给出）。"""
    view = ctx.config.page_view(page_code)
    master_source = Source.of(view.master.entity, ctx.config.entity(view.master.entity))
    master = Scope.of(master_source, "a", [f.name for f in view.master.fields if f.visible])
    details: dict[str, tuple[Scope, str]] = {}
    for i, area in enumerate(view.details):
        source = Source.of(area.entity, ctx.config.entity(area.entity))
        details[area.entity] = (Scope.of(source, f"d{i}", [f.name for f in area.fields if f.visible]), area.parent_key)
    return PageScope(view=view, master=master, details=details)


def master_clauses(permission: PermissionChecker, ctx: ExecutionContext, page_code: str, scope: PageScope, binds: Binds,
                   conditions: Conditions, request: ListRequest | None) -> list[str]:
    """主表的查询条件：行权限（QE-01）、筛选模型、高级查询（含明细 EXISTS，QE-12）。request 为 None 时只有行权限。"""
    clauses = row_condition_sql(permission.row_condition(ctx, page_code, scope.source.code), binds)
    if request is not None:
        clauses += filter_model_sql(conditions, scope.master, request.filter_model)
        if request.advanced is not None:
            pk = scope.source.column(scope.source.entity.primary_key, scope.master.alias)
            clauses += advanced_sql(conditions, request.advanced, scope.master, scope.details, pk)
    return clauses


class PageQueries:
    """C09 第 4 节的列表、按主键取行和单据加载。

    构造参数：`uow_factory`、`permission` 为必填（assembly 现有的用法）；`freeze` 为 approval 的 `FreezeReader`，
    没有注入时所有行的 `frozen` 为 null；`catalog` 给出汇总字段，没有注入时 `aggregates` 为空。
    """

    def __init__(self, uow_factory: UnitOfWorkFactory, permission: PermissionChecker, *,
                 freeze: FreezeReader | None = None, catalog: CatalogOf | None = None) -> None:
        self._uow = uow_factory
        self._permission = permission
        self._freeze = freeze
        self._catalog = catalog

    # ---------------------------------------------------------------- 列表

    def list(self, ctx: ExecutionContext, page_code: str, request: ListRequest) -> ListResponse:
        scope = page_scope(ctx, page_code)
        source = scope.source
        sums = list(self._catalog(ctx).sum_fields(page_code, "master")) if self._catalog else []
        with self._uow.begin() as uow:
            name = dialect(uow)
            binds = Binds()
            where = where_sql(master_clauses(self._permission, ctx, page_code, scope, binds, Conditions(binds, name), request))
            order = order_sql(scope.master, request.sort_model)
            totals = ["COUNT(*)", *(f"SUM({source.column(f, 'a')})" for f in sums)]
            stats = uow.connection.execute(text(f"SELECT {', '.join(totals)} FROM {source.name} a{where}"), binds.values).one()
            records = uow.connection.execute(
                text(f"SELECT {source.select_list('a')} FROM {source.name} a{where} ORDER BY {order} {page_clause(name)}"),
                {**binds.values, **page_binds(request.start_row, request.end_row)}).all()
            values = [row_values(source.ordered(), r) for r in records]
            rows = self._rows(uow, source, values, scope.root_table, [self._own_key(source, v) for v in values])
        aggregates = {f: to_wire("number", number(stats[i + 1])) for i, f in enumerate(sums)}
        return ListResponse(rows=rows, total=int(stats[0] or 0), aggregates=aggregates)

    # ---------------------------------------------------------------- 按主键取行

    def by_keys(self, ctx: ExecutionContext, page_code: str, request: ByKeysRequest) -> RowsResponse:
        """按主键取主表或某个明细的行，按请求中的顺序返回；不存在或超出行权限的行不返回。"""
        scope = page_scope(ctx, page_code)
        master = scope.source
        if request.entity == master.code:
            source, parent_key = master, None
        elif request.entity in scope.details:
            detail_scope, parent_key = scope.details[request.entity]
            source = detail_scope.source
        else:
            raise PlatformError(ErrorCode.VALIDATION_FAILED, f"页面 {page_code} 上没有 {request.entity}",
                                [ErrorDetail(entity=request.entity)])
        keys = list(dict.fromkeys(source.key(k) for k in request.row_keys))
        found: list[dict[str, Value]] = []
        with self._uow.begin() as uow:
            for chunk in batches(keys):
                binds = Binds()
                clauses = [f"x.{source.columns[source.entity.primary_key]} IN ({', '.join(binds.add(k) for k in chunk)})"]
                condition = row_condition_sql(self._permission.row_condition(ctx, page_code, master.code), binds)
                if condition and parent_key is None:
                    clauses += condition
                elif condition:
                    clauses.append(f"EXISTS (SELECT 1 FROM {master.name} a WHERE {master.column(master.entity.primary_key, 'a')} "
                                   f"= x.{source.columns[parent_key]} AND {condition[0]})")
                records = uow.connection.execute(
                    text(f"SELECT {source.select_list('x')} FROM {source.name} x{where_sql(clauses)}"), binds.values)
                found += [row_values(source.ordered(), r) for r in records]
            roots = [self._own_key(source, v) if parent_key is None else key_text(v[parent_key]) for v in found]
            rows = self._rows(uow, source, found, scope.root_table, roots)
        position = {key_text(k): i for i, k in enumerate(keys)}
        return RowsResponse(rows=sorted(rows, key=lambda r: position.get(r.row_key, len(position))))

    # ---------------------------------------------------------------- 单据加载

    def record(self, ctx: ExecutionContext, page_code: str, record_key: str) -> RecordResponse:
        """主表行和每个明细的全部行；主表行不存在或超出行权限时 404。"""
        scope = page_scope(ctx, page_code)
        source = scope.source
        key = source.key(record_key)
        with self._uow.begin() as uow:
            binds = Binds()
            clauses = [f"{source.column(source.entity.primary_key, 'a')} = {binds.add(key)}",
                       *row_condition_sql(self._permission.row_condition(ctx, page_code, source.code), binds)]
            found = uow.connection.execute(
                text(f"SELECT {source.select_list('a')} FROM {source.name} a{where_sql(clauses)}"), binds.values).first()
            if found is None:
                raise PlatformError(ErrorCode.NOT_FOUND, "单据不存在")
            values = row_values(source.ordered(), found)
            root = self._own_key(source, values)
            frozen = self._frozen(uow, scope.root_table, [root]).get(root)
            master = to_data_row(source, values, frozen, compare_rows(uow, source, [values])[0])
            details: dict[str, list[DataRow]] = {}
            for entity, (detail_scope, parent_key) in scope.details.items():
                detail = detail_scope.source
                sql = (f"SELECT {detail.select_list('x')} FROM {detail.name} x WHERE x.{detail.columns[parent_key]} = :qe_record "
                       f"ORDER BY x.{detail.columns[detail.entity.primary_key]}")
                rows = [row_values(detail.ordered(), r) for r in uow.connection.execute(text(sql), {"qe_record": key})]
                details[entity] = [to_data_row(detail, v, frozen, c) for v, c in zip(rows, compare_rows(uow, detail, rows), strict=True)]
        return RecordResponse(master=master, details=details)

    # ---------------------------------------------------------------- 共用

    @staticmethod
    def _own_key(source: Source, values: Mapping[str, Value]) -> str:
        return key_text(values[source.entity.primary_key])

    def _frozen(self, uow: UnitOfWork, table: str, keys: Sequence[str]) -> dict[str, FrozenMark]:
        """QE-05：经 approval 的 FreezeReader 读冻结记录，按根表主键。"""
        if self._freeze is None or not keys:
            return {}
        entries = self._freeze.find(uow, table, list(dict.fromkeys(keys)))
        return {key: FrozenMark(approval_id=entry.approval_id) for key, entry in entries.items()}

    def _rows(self, uow: UnitOfWork, source: Source, values: Sequence[Mapping[str, Value]], root_table: str,
              roots: Sequence[str]) -> list[DataRow]:
        frozen = self._frozen(uow, root_table, roots)
        compares = compare_rows(uow, source, values)
        return [to_data_row(source, v, frozen.get(root), c) for v, root, c in zip(values, roots, compares, strict=True)]
