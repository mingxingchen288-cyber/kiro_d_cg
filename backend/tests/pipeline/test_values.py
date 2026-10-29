"""WP-15 小数位处理（工程约定第 5 节：先写失败的测试）。业务例子 E04。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cost_platform.pipeline.values import ColumnScales, round_decimal, stored_value

from .support import MATERIAL_ENTITY, scales_inspector


@pytest.mark.parametrize(("value", "expected"), [
    ("1.234567885", "1.23456789"),    # E04：第 9 位四舍五入
    ("-1.234567885", "-1.23456789"),  # E04：负数按绝对值四舍五入，与 Oracle 相同
    ("1.234567884", "1.23456788"),
    ("3.80", "3.80"),                 # 不超过 8 位的不变
    ("100000", "100000"),
])
def test_at_most_8_places(value: str, expected: str) -> None:
    assert round_decimal(Decimal(value), None) == Decimal(expected)
    assert str(round_decimal(Decimal(value), None)) == expected


@pytest.mark.parametrize(("value", "scale", "expected"), [
    ("3.805", 2, "3.81"),       # NUMBER(p,2)：按列的小数位四舍五入
    ("-3.805", 2, "-3.81"),
    ("1.23456", 4, "1.2346"),
    ("12.5", 0, "13"),
    ("1.234567885", 10, "1.23456789"),  # 列的小数位大于 8 时仍按 8 位
])
def test_column_scale_below_8(value: str, scale: int, expected: str) -> None:
    assert round_decimal(Decimal(value), scale) == Decimal(expected)


def test_stored_value_by_type() -> None:
    assert stored_value("number", Decimal("1.234567885"), None) == Decimal("1.23456789")
    assert stored_value("text", "", None) is None  # Oracle 把空文本存为空值
    assert stored_value("text", "测试", None) == "测试"
    assert stored_value("number", None, 2) is None


def test_column_scales_come_from_table_columns() -> None:
    inspector = scales_inspector({("T_COST_PINGGU_DTL", "PRICE"): 2})
    scales = ColumnScales(inspector)
    assert scales.scale(MATERIAL_ENTITY.table, "PRICE") == 2
    assert scales.scale(MATERIAL_ENTITY.table, "USAGE") is None
    scales.scale(MATERIAL_ENTITY.table, "USAGE")
    assert len(inspector.calls_to("columns")) == 1  # 同一张表只查一次
