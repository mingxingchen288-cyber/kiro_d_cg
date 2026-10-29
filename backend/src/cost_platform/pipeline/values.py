"""写入前的数值处理（WP-15）和配置中文本值的转换。

数值最多保留 8 位小数，按第 9 位四舍五入；负数按绝对值四舍五入（Decimal 的 ROUND_HALF_UP 即如此），与 Oracle 相同。
列定义了小数位（`NUMBER(p,s)`）且小于 8 时按列的小数位四舍五入，与 Oracle 存储的结果一致。

列的小数位取数据库中表的列（db-core 的 `SchemaInspector`，C08 第 2 节 `ColumnInfo.scale`），不取实体字段的 `scale`：
后者是显示小数位，只用于显示，不改变保存的值（C05）。例如 E02 的 BATCH_QTY 显示 0 位，保存的 5.1 不能变成 5。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from cost_platform.contracts.decimal_text import parse_decimal
from cost_platform.contracts.ports import SchemaInspector
from cost_platform.contracts.types import EntityField, FieldType, Value

MAX_PLACES = 8


def round_decimal(value: Decimal, scale: int | None) -> Decimal:
    """按列的小数位（没有或不小于 8 时按 8 位）四舍五入；位数没有超出的原样返回，保留原有的末尾零。"""
    places = scale if scale is not None and scale < MAX_PLACES else MAX_PLACES
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -places:
        return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return value


def stored_value(field_type: FieldType, value: Value, scale: int | None) -> Value:
    """写入数据库后的值：数值按 WP-15 处理；Oracle 把空文本存为空值。"""
    if isinstance(value, Decimal) and field_type == "number":
        return round_decimal(value, scale)
    if value == "":
        return None
    return value


def config_value(field: EntityField, text: str) -> Value:
    """配置中以文本写出的值（静态默认值、下拉选项、erpRow 的 value 和 localValue）按字段类型转换。"""
    if field.type == "number":
        return parse_decimal(text)
    if field.type == "boolean":
        return text.strip().lower() in ("1", "true", "y", "是")
    if field.type == "date":
        return date.fromisoformat(text)
    if field.type == "datetime":
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
    return text


class ColumnScales:
    """业务表数值列的小数位，按表名经 `SchemaInspector` 读取，每张表在进程内只读一次（表结构变更随部署重启生效）。"""

    def __init__(self, inspector: SchemaInspector) -> None:
        self._inspector = inspector
        self._tables: dict[str, dict[str, int | None]] = {}

    def scale(self, table: str, column: str | None) -> int | None:
        if column is None:
            return None
        key = table.upper()
        if key not in self._tables:
            columns = self._inspector.columns(table) or {}
            self._tables[key] = {name.upper(): info.scale for name, info in columns.items()}
        return self._tables[key].get(column.upper())


class NoScales:
    """不知道列的小数位时：只按最多 8 位处理。"""

    def scale(self, table: str, column: str | None) -> int | None:
        return None
