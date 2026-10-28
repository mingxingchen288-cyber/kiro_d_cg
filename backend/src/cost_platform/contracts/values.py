"""业务字段值在 JSON 和后端内部之间的转换（C01 第 2、4 节，C08 第 1 节）。

JSON 中精确数值是十进制文本、日期和日期时间是 C01 第 4 节的文本；后端内部数值为 Decimal、日期为 date、
日期时间为 datetime（不带时区）。按实体字段的 `type` 转换。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from .decimal_text import format_decimal, parse_decimal
from .types import BusinessValue, FieldType, Value


def to_wire(field_type: FieldType, value: Value | int | float) -> BusinessValue:
    """后端内部的值转为 JSON 中的值。数据库驱动读出的整数也按十进制文本输出。"""
    if value is None:
        return None
    if field_type == "number":
        if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
            raise ValueError(f"数值字段的值不是 Decimal：{value!r}")
        return format_decimal(Decimal(value))
    if field_type == "boolean":
        return bool(value)
    if field_type == "date":
        if isinstance(value, datetime):
            value = value.date()
        assert isinstance(value, date)
        return value.isoformat()
    if field_type == "datetime":
        assert isinstance(value, datetime)
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    return str(value)


def from_wire(field_type: FieldType, value: BusinessValue) -> Value:
    """JSON 中的值转为后端内部的值；格式不对时抛 ValueError。"""
    if value is None:
        return None
    if field_type == "number":
        if not isinstance(value, str):
            raise ValueError("数值必须是十进制文本")
        return parse_decimal(value)
    if field_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("是非字段必须是 true 或 false")
        return value
    if not isinstance(value, str):
        raise ValueError("值必须是文本")
    if field_type == "date":
        return date.fromisoformat(value)
    if field_type == "datetime":
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    return value


def from_db(field_type: FieldType, value: object) -> Value:
    """数据库驱动读出的值转为后端内部的值：整数转 Decimal（DB-01），日期字段只取日期；
    是非字段在数据库中是 NUMBER(1) 的 0/1（C01），转为 bool。"""
    if value is None:
        return None
    if field_type == "number" and isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if field_type == "boolean":
        return bool(value)
    if field_type == "date" and isinstance(value, datetime):
        return value.date()
    return value  # type: ignore[return-value]


def to_db(field_type: FieldType, value: Value) -> object:
    """后端内部的值转为写入数据库的值：是非字段写 1/0（NUMBER(1)），其余原样。"""
    if field_type == "boolean" and value is not None:
        return 1 if value else 0
    return value


def same_value(field_type: FieldType, a: Value, b: Value) -> bool:
    """合并时判断新值与当前值是否相同：数值按数值相等比较（WP-04），文本空串与空值相同（Oracle 把空串存为空）。"""
    if field_type == "number":
        if a is None or b is None:
            return a is None and b is None
        return Decimal(a) == Decimal(b)  # type: ignore[arg-type]
    if field_type == "text":
        return (a or None) == (b or None)
    return a == b
