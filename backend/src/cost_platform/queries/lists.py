"""列表（QE-01–QE-04）和单据加载（C09 第 4 节）。

列表一条查行、一条查总数；目前只开放排序和分页，筛选、高级查询、汇总以后接入。
单据加载在一个只读事务中查主表行（带行权限条件），再按主从关联字段查每个明细，明细按主键排序。
"""

from __future__ import annotations

from collections.abc import Sequence

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
    RecordResponse,
)
from cost_platform.contracts.values import from_db, from_wire, to_wire
from sqlalchemy import text


def _columns(entity: EntityConfig) -> tuple[str, dict[str, tuple[EntityField, str]]]:
    """QE-03：有 readView 时从视图读取（列名为字段名），否则读表（列名为 `column`）。"""
    if entity.read_view:
        return entity.read_view, {f.name: (f, f.name) for f in entity.fields}
    return entity.table, {f.name: (f, f.column) for f in entity.fields if f.column}


def _data_row(entity: EntityConfig, fields: list[tuple[EntityField, str]], record: Sequence[object]) -> DataRow:
    values = {field.name: to_wire(field.type, from_db(field.type, raw)) for (field, _), raw in zip(fields, record)}
    return DataRow(row_key=str(values[entity.primary_key]), values=values, frozen=None)


class PageQueries:
    def __init__(self, uow_factory: UnitOfWorkFactory, permission: PermissionChecker) -> None:
        self._uow = uow_factory
        self._permission = permission

    def _row_filter(self, ctx: ExecutionContext, page_code: str, entity_code: str) -> tuple[list[str], dict[str, object]]:
        """QE-01：行权限条件，与其他条件用 AND 组合。"""
        condition = self._permission.row_condition(ctx, page_code, entity_code)
        if condition is None:
            return [], {}
        return [f"({condition.sql})"], dict(condition.binds)

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
        conditions, binds = self._row_filter(ctx, page_code, entity_code)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        fields = list(columns.values())
        select = ", ".join(column for _, column in fields)
        rows_sql = (f"SELECT {select} FROM {source}{where} ORDER BY {', '.join(order)} "
                    "OFFSET :start_row ROWS FETCH NEXT :page_size ROWS ONLY")
        page = {"start_row": request.start_row, "page_size": max(request.end_row - request.start_row, 0)}
        with self._uow.begin() as uow:
            records = uow.connection.execute(text(rows_sql), {**binds, **page}).all()
            total = uow.connection.execute(text(f"SELECT COUNT(*) FROM {source}{where}"), binds).scalar()
        rows = [_data_row(entity, fields, record) for record in records]
        return ListResponse(rows=rows, total=int(total or 0), aggregates={})

    def record(self, ctx: ExecutionContext, page_code: str, record_key: str) -> RecordResponse:
        """单据加载：主表行和每个明细的全部行；主表行不存在或超出行权限时 404。"""
        view = ctx.config.page_view(page_code)
        entity_code = view.master.entity
        entity = ctx.config.entity(entity_code)
        source, columns = _columns(entity)
        pk_field, pk_column = columns[entity.primary_key]
        conditions, binds = self._row_filter(ctx, page_code, entity_code)
        where = " AND ".join([f"{pk_column} = :record_key", *conditions])
        fields = list(columns.values())
        key = from_wire(pk_field.type, record_key)
        details: dict[str, list[DataRow]] = {}
        with self._uow.begin() as uow:
            found = uow.connection.execute(
                text(f"SELECT {', '.join(c for _, c in fields)} FROM {source} WHERE {where}"),
                {**binds, "record_key": key}).first()
            if found is None:
                raise PlatformError(ErrorCode.NOT_FOUND, "单据不存在")
            for area in view.details:
                detail = ctx.config.entity(area.entity)
                detail_source, detail_columns = _columns(detail)
                detail_fields = list(detail_columns.values())
                sql = (f"SELECT {', '.join(c for _, c in detail_fields)} FROM {detail_source} "
                       f"WHERE {detail_columns[area.parent_key][1]} = :record_key "
                       f"ORDER BY {detail_columns[detail.primary_key][1]}")
                records = uow.connection.execute(text(sql), {"record_key": key}).all()
                details[area.entity] = [_data_row(detail, detail_fields, r) for r in records]
        return RecordResponse(master=_data_row(entity, fields, found), details=details)
