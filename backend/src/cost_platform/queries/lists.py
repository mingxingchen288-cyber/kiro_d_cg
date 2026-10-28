"""列表（QE-01–QE-04）：一条查行、一条查总数。目前只开放排序和分页，筛选、高级查询、汇总以后接入。"""

from __future__ import annotations

from cost_platform.contracts.ports import PermissionChecker, UnitOfWorkFactory
from cost_platform.contracts.types import (
    DataRow,
    EntityConfig,
    EntityField,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    ListRequest,
    ListResponse,
    PlatformError,
)
from cost_platform.contracts.values import from_db, to_wire
from sqlalchemy import text


def _columns(entity: EntityConfig) -> tuple[str, dict[str, tuple[EntityField, str]]]:
    """QE-03：有 readView 时从视图读取（列名为字段名），否则读表（列名为 `column`）。"""
    if entity.read_view:
        return entity.read_view, {f.name: (f, f.name) for f in entity.fields}
    return entity.table, {f.name: (f, f.column) for f in entity.fields if f.column}


class PageQueries:
    def __init__(self, uow_factory: UnitOfWorkFactory, permission: PermissionChecker) -> None:
        self._uow = uow_factory
        self._permission = permission

    def list(self, ctx: ExecutionContext, page_code: str, request: ListRequest) -> ListResponse:
        view = ctx.config.page_view(page_code)
        entity_code = view.master.entity
        entity = ctx.config.entity(entity_code)
        source, columns = _columns(entity)
        visible = {f.name for f in view.master.fields if f.visible}
        order: list[str] = []
        for item in request.sort_model:
            if item.col_id not in visible or item.col_id not in columns:
                raise PlatformError(ErrorCode.VALIDATION_FAILED, f"不能按 {item.col_id} 排序",
                                    [ErrorDetail(entity=entity_code, field=item.col_id)])
            order.append(f"{columns[item.col_id][1]} {item.sort.upper()}")
        pk_column = columns[entity.primary_key][1]
        order.append(pk_column)  # QE-04：排序值相同时按主键，分页稳定
        where, binds = "", {}
        condition = self._permission.row_condition(ctx, page_code, entity_code)
        if condition is not None:
            where, binds = f" WHERE ({condition.sql})", dict(condition.binds)
        fields = list(columns.values())
        select = ", ".join(column for _, column in fields)
        rows_sql = (f"SELECT {select} FROM {source}{where} ORDER BY {', '.join(order)} "
                    "OFFSET :start_row ROWS FETCH NEXT :page_size ROWS ONLY")
        page = {"start_row": request.start_row, "page_size": max(request.end_row - request.start_row, 0)}
        with self._uow.begin() as uow:
            records = uow.connection.execute(text(rows_sql), {**binds, **page}).all()
            total = uow.connection.execute(text(f"SELECT COUNT(*) FROM {source}{where}"), binds).scalar()
        rows = []
        for record in records:
            values = {field.name: to_wire(field.type, from_db(field.type, raw)) for (field, _), raw in zip(fields, record)}
            rows.append(DataRow(row_key=str(values[entity.primary_key]), values=values, frozen=None))
        return ListResponse(rows=rows, total=int(total or 0), aggregates={})
