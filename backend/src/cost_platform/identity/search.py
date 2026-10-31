"""人员、部门列表的高级查询条件（ID-12；C09 v15 第 2 节 `advanced`）。

同旧系统人员管理、部门管理两个通用页的"高级查询"（cmx `T_COST_PAGE_COMPONENT` user-manage、dept-manage 的
`advancedSearch` 按钮，列的"查询"标记 `T_COST_COLUMN_METADATA.SEARCHABLE`）。条件的格式同 C09 第 4 节的
`AdvancedQuery`，只有一张表，不写 `entity`。运算符和取值同页面列表（queries 的 `Conditions`）：

- 文本不分大小写；"包含""不包含"按字面匹配（`%`、`_` 不当通配符）。
- 等于、不等于的值为 null 时为"为空""不为空"；其余运算符没有值时这条条件不起作用（同旧系统）。
- 数值按十进制比较；"包含"按数值的文本匹配（例如 ID 包含 24）。

可查的字段是新表格上有、旧页面勾了"查询"的列；旧页面的邮箱、电话、部门编码新平台没有。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.sql.elements import ColumnElement

from cost_platform.contracts.types import AdvancedCondition, AdvancedQuery, ErrorCode, ErrorDetail, PlatformError, parse_wire

from .tables import pf_department, pf_user

Kind = Literal["number", "text", "key", "boolean"]


@dataclass(frozen=True)
class SearchField:
    """可查的字段：`column` 为表的列；`kind` 决定取值和比较方式（key 为编号，按原样比较）。"""

    column: Any
    kind: Kind


ACCOUNT_FIELDS: Mapping[str, SearchField] = {
    "userId": SearchField(pf_user.c.user_id, "number"),
    "username": SearchField(pf_user.c.username, "text"),
    "displayName": SearchField(pf_user.c.display_name, "text"),
    "departmentId": SearchField(pf_user.c.department_id, "key"),
    "enabled": SearchField(pf_user.c.enabled, "boolean"),
}
"""人员管理：ID、用户名、姓名、部门、状态（旧 CostUser 的 ID、USERNAME、REAL_NAME、DEPARTMENT_ID/DEPT_NAME、STATUS）。"""

DEPARTMENT_FIELDS: Mapping[str, SearchField] = {
    # 部门编号存为文本（PF_DEPARTMENT.DEPARTMENT_ID），取自序列和旧系统的数值 ID，按数值比较同旧页面
    "departmentId": SearchField(sa.cast(pf_department.c.department_id, sa.Numeric), "number"),
    "name": SearchField(pf_department.c.name, "text"),
}
"""部门管理：ID、部门名称（旧 CostDepartment 的 ID、DEPT_NAME）。"""

_SYMBOLS = {"=": "eq", "==": "eq", "<>": "ne", "!=": "ne", ">": "gt", ">=": "ge", "<": "lt", "<=": "le"}
_TRUE_TEXT = {"1", "true", "y", "yes", "是", "启用"}


def _invalid(message: str, field: str | None = None) -> PlatformError:
    return PlatformError(ErrorCode.VALIDATION_FAILED, message, [ErrorDetail(message=message, field=field)])


def parse_advanced(text: str | None) -> AdvancedQuery | None:
    """查询参数 `advanced` 的 JSON 文本；为空时没有高级查询条件，格式不对时 422 VALIDATION_FAILED。"""
    if not text or not text.strip():
        return None
    try:
        return parse_wire(AdvancedQuery, json.loads(text))  # type: ignore[no-any-return]
    except (ValueError, ValidationError):
        raise _invalid("高级查询条件不符合接口约定", "advanced") from None


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _value(field: SearchField, name: str, raw: Any) -> Any:
    if field.kind == "number":
        try:
            if isinstance(raw, bool):
                raise ValueError(raw)
            return Decimal(str(raw).strip())
        except (ValueError, InvalidOperation):
            raise _invalid(f"{name} 的值 {raw!r} 不是数值", name) from None
    if field.kind == "boolean":
        if isinstance(raw, bool):
            return 1 if raw else 0
        return 1 if str(raw).strip().lower() in _TRUE_TEXT else 0
    text = str(raw).strip()
    return text.upper() if field.kind == "text" else text


def _condition(fields: Mapping[str, SearchField], condition: AdvancedCondition) -> ColumnElement[bool] | None:
    if condition.entity:
        raise _invalid(f"列表只有一张表，条件不能写 entity（{condition.entity}）", condition.field)
    field = fields.get(condition.field)
    if field is None:
        raise _invalid(f"不能按 {condition.field} 查询", condition.field)
    op = _SYMBOLS.get(condition.operator, condition.operator)
    column = field.column
    compared = sa.func.upper(column) if field.kind == "text" else column
    value = condition.value
    if op == "isNull":
        return column.is_(None)
    if op == "isNotNull":
        return column.is_not(None)
    if op in ("eq", "ne"):
        if value is None:
            return column.is_(None) if op == "eq" else column.is_not(None)
        bound = _value(field, condition.field, value)
        return compared == bound if op == "eq" else compared != bound
    if value is None or value == "" or value == []:
        return None
    if op in ("gt", "ge", "lt", "le"):
        bound = _value(field, condition.field, value)
        return {"gt": column > bound, "ge": column >= bound, "lt": column < bound, "le": column <= bound}[op]
    if op in ("like", "notLike"):
        text = str(value).strip()
        target = compared if field.kind == "text" else sa.cast(column, sa.String(64))
        pattern = f"%{_escape(text.upper() if field.kind == 'text' else text)}%"
        return target.not_like(pattern, escape="\\") if op == "notLike" else target.like(pattern, escape="\\")
    if op in ("between", "notBetween"):
        if not isinstance(value, list) or len(value) != 2 or any(v is None or v == "" for v in value):
            return None
        low, high = (_value(field, condition.field, v) for v in value)
        inside = column.between(low, high)
        return sa.not_(inside) if op == "notBetween" else inside
    if op in ("in", "notIn"):
        items = [v for v in (value if isinstance(value, list) else [value]) if v is not None and v != ""]
        if not items:
            return None
        bound = [_value(field, condition.field, v) for v in items]
        return compared.not_in(bound) if op == "notIn" else compared.in_(bound)
    raise _invalid(f"不支持的运算符 {condition.operator}", condition.field)


def conditions_of(fields: Mapping[str, SearchField], query: AdvancedQuery | None) -> list[ColumnElement[bool]]:
    """高级查询条件转成 SQLAlchemy 条件（列表的 WHERE 再加上它）；没有起作用的条件时为空列表。"""
    if query is None:
        return []
    parts = [c for c in (_condition(fields, item) for item in query.conditions) if c is not None]
    if not parts:
        return []
    return [sa.and_(*parts) if query.op == "and" else sa.or_(*parts)]
