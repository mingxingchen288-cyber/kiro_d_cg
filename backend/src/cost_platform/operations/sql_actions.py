"""按 SQL 的两种按钮动作（C06 第 6 节 v18，OP-09、OP-10）：`replaceDetails`、`updateRows`。

用户 2026-10-29："那两个存储过程是有问题的，它内部又计算了一次，这是不应该的，后续都可以不用存储过程计算了"。成本核算的
"由BOM生成明细"（旧 P_COST_BOM_INSERT）、"同步采购价"（旧 P_PINGGU_COMPUTE_ALL）改用这两个动作：数据照旧系统由 SQL 查出，
计算全部交给写入管道里的规则（write-pipeline 的"计算与规则"）。

- SQL 由配置给出，config 保存时已核对只能是一条查询语句、结果列是实体中本操作可写的字段（C06 第 10 节）。这里在命令事务
  的连接上只读执行，参数用绑定变量；结果的值按字段类型转换（与读取单据相同，数值为 Decimal）。
- 展开只生成 `RowIntent`：删除、新增、修改明细。write-pipeline 对不在 `involved` 中的单据先加锁读取、做冻结检查，再合并、
  检查写权限并计算（WP-18）；被审批冻结的单据整个命令返回 409 FROZEN_BY_APPROVAL。
- 列名与字段名按不区分大小写对应：SQLAlchemy 的 Oracle 方言把不带引号的列名转成小写。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal

from sqlalchemy import text

from cost_platform.contracts.decimal_text import format_decimal
from cost_platform.contracts.types import (
    CommandState,
    DocumentRef,
    EntityConfig,
    EntityField,
    ErrorCode,
    PlatformError,
    ReplaceDetails,
    RowIntent,
    UpdateRows,
    Value,
)
from cost_platform.contracts.values import from_db

from .actions import Round, planned_intents
from .mapping import WritePlan, check_writable, split_ref

_ROW_IDS = uuid.UUID("5d2c7f0e-3b1a-4c8e-9f6d-2a7b8c9d0e1f")
"""新增行 clientRowId 的命名空间：同一请求键、同一动作、同一张单据的第 n 行总是得到同一个编号（C01 第 5 节 `tmp-` 加 UUID）。"""


def _client_row_id(state: CommandState, cursor: int, ref: DocumentRef, n: int) -> str:
    return f"tmp-{uuid.uuid5(_ROW_IDS, f'{state.command.request_key}/{cursor}/{ref.record_key}/{n}')}"


def _key_text(raw: object) -> str | None:
    """主键列的值转成文本：数值为十进制文本（115、Decimal 115 都是 "115"）；为空时为 None。"""
    if raw is None:
        return None
    if isinstance(raw, int | float | Decimal):
        return format_decimal(Decimal(str(raw)))
    return str(raw)


def _value(field: EntityField, raw: object) -> Value:
    """SQL 结果中的值按字段类型转成后端内部的值（C08 第 1 节）。"""
    value = from_db(field.type, raw)
    if field.type == "number" and isinstance(value, float):
        return Decimal(str(value))  # 只在 contracts 的 SQLite 替代事务中出现
    if field.type == "text" and value is not None and not isinstance(value, str):
        return _key_text(value)
    return value


def _position(columns: Sequence[str], name: str) -> int | None:
    folded = name.casefold()
    return next((i for i, c in enumerate(columns) if c.casefold() == folded), None)


def _value_columns(entity_code: str, entity: EntityConfig, columns: Sequence[str],
                   skip: Sequence[str] = ()) -> list[tuple[int, EntityField]]:
    """结果中要写的列（`skip` 中的主键列除外）和它们对应的字段。列不是实体的字段时为配置错误（保存时已校验）。"""
    fields = {f.name.casefold(): f for f in entity.fields}
    skipped = {s.casefold() for s in skip}
    found: list[tuple[int, EntityField]] = []
    for i, column in enumerate(columns):
        if column.casefold() in skipped:
            continue
        field = fields.get(column.casefold())
        if field is None:
            raise PlatformError(ErrorCode.INTERNAL_ERROR, f"SQL 的列 {column} 不是实体 {entity_code} 的字段")
        found.append((i, field))
    return found


def _execute(rnd: Round, sql: str, binds: Mapping[str, object]) -> tuple[list[str], list[Sequence[object]]]:
    result = rnd.uow.connection.execute(text(sql), dict(binds))
    columns = [str(c) for c in result.keys()]
    return columns, [tuple(r) for r in result.all()]


# ---------------------------------------------------------------- replaceDetails

def expand_replace_details(rnd: Round, action: ReplaceDetails, cursor: int) -> list[RowIntent]:
    """每张选中的单据（OP-08）：删除这张单据中 `entity` 的全部行（加锁读到的当前数据），再把 SQL 查出的每一行新增为
    `entity` 的一行（C06 第 6 节）。

    - SQL 的绑定变量取这张单据主表计算后的值（前面动作合并、计算后的候选数据），每张单据执行一次。
    - 新增行的值：SQL 的每一列写到同名字段；没有的字段按新增行的默认值（WP-16）；关联字段取这张单据的主键（write-pipeline）。
      计算字段不在 SQL 里写，由计算规则算出；名称、分类这类只在视图中的字段，求值前由 write-pipeline 按页面的 Lookup 带出。
    - 新增行按 SQL 返回的顺序，`clientRowId` 见 `_client_row_id`。"""
    entity = rnd.entity(action.entity)
    binds = {name: split_ref(ref) for name, ref in action.binds.items()}
    intents: list[RowIntent] = []
    checks: list[tuple[str, str, list[str], None]] = []
    for ref in rnd.sources:
        doc = rnd.data(ref)
        current = rnd.state.current.get(ref)
        if doc is None or current is None:
            continue
        for row in current.details.get(action.entity, []):
            if row.row_key is not None:
                intents.append(RowIntent(document=ref, entity=action.entity, op="delete", row_key=row.row_key,
                                         client_row_id=None, values={}))
        values = {name: doc.master.values.get(field) for name, (_, field) in binds.items()}
        columns, records = _execute(rnd, action.sql, values)
        mapped = _value_columns(action.entity, entity, columns)
        names = [f.name for _, f in mapped]
        for n, record in enumerate(records):
            client = _client_row_id(rnd.state, cursor, ref, n)
            checks.append((action.entity, client, names, None))
            intents.append(RowIntent(document=ref, entity=action.entity, op="add", row_key=None, client_row_id=client,
                                     values={f.name: _value(f, record[i]) for i, f in mapped}))
    check_writable(rnd.operation_code, rnd.operation, {action.entity: entity}, checks)
    return intents


# ---------------------------------------------------------------- updateRows

def expand_update_rows(rnd: Round, action: UpdateRows) -> list[RowIntent]:
    """按 SQL 找到要改的记录和新值（C06 第 6 节）：SQL 执行一次，不看选中行，涉及的单据由结果决定。

    每一行是一条记录：`recordKeyColumn` 为单据主键，`entity` 为明细实体时 `rowKeyColumns` 的一列为明细主键（同 6.1）；
    其余列写到同名字段。主键列为空的行表示记录已不存在，跳过。同一条记录的同一字段被写成不同的值时 422 VALIDATION_FAILED；
    要写的字段不可写时 422 FIELD_NOT_WRITABLE（与 `fieldMapping.to` 相同）。"""
    entity = rnd.entity(action.entity)
    columns, records = _execute(rnd, action.sql, {})
    keys = [action.record_key_column, *action.row_key_columns]
    positions = [_position(columns, k) for k in keys]
    if any(p is None for p in positions):
        missing = [k for k, p in zip(keys, positions, strict=True) if p is None]
        raise PlatformError(ErrorCode.INTERNAL_ERROR, f"SQL 的结果缺少 {', '.join(missing)}")
    mapped = _value_columns(action.entity, entity, columns, skip=keys)
    detail = bool(action.row_key_columns)
    document_entity = rnd.master_of(action.entity) if detail else action.entity
    plan = WritePlan()
    for record in records:
        record_key = _key_text(record[positions[0]])  # type: ignore[index]
        row_key = _key_text(record[positions[1]]) if detail else record_key  # type: ignore[index]
        if record_key is None or row_key is None:
            continue
        planned = plan.row(document_entity, record_key, action.entity, row_key)
        for i, field in mapped:
            plan.put(planned, field.name, _value(field, record[i]))
    return planned_intents(rnd, plan)
