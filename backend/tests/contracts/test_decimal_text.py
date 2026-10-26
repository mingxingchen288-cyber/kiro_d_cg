"""T-CT-2：十进制文本的解析、格式化和数值一致判定（C01 第 2、3 节）。

样例直接从 docs/契约/C01-数据格式.md 读取；前端 frontend/tests/contracts/decimal-text.test.ts 读取同一批样例。
"""

from __future__ import annotations

import re
from decimal import ROUND_DOWN, Context, Decimal
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cost_platform.contracts.decimal_text import (
    format_decimal,
    is_decimal_text,
    numbers_consistent,
    parse_decimal,
)

C01 = Path(__file__).resolve().parents[3] / "docs" / "契约" / "C01-数据格式.md"


def _quoted(text: str) -> list[str]:
    return re.findall(r"`([^`]*)`", text)


def _c01() -> tuple[list[str], list[str], list[tuple[str, str, bool]]]:
    text = C01.read_text(encoding="utf-8")
    valid = _quoted(re.search(r"^\s*- 合法：(.*)$", text, flags=re.M).group(1))
    invalid = _quoted(re.search(r"^\s*- 不合法：(.*)$", text, flags=re.M).group(1))
    section = text.split("## 3.", 1)[1].split("## 4.", 1)[0]
    table: list[tuple[str, str, bool]] = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[2] in ("一致", "不一致"):
            table += [(a, b, cells[2] == "一致") for a in _quoted(cells[0]) for b in _quoted(cells[1])]
    return valid, invalid, table


VALID, INVALID, TABLE = _c01()


def test_c01_samples_found() -> None:
    assert len(VALID) == 3
    assert len(INVALID) == 6
    assert len(TABLE) == 9


@pytest.mark.parametrize("text", VALID)
def test_valid_text_parses(text: str) -> None:
    assert is_decimal_text(text)
    assert parse_decimal(text) == Decimal(text)


@pytest.mark.parametrize("text", INVALID)
def test_invalid_text_rejected(text: str) -> None:
    assert not is_decimal_text(text)
    with pytest.raises(ValueError):
        parse_decimal(text)


@pytest.mark.parametrize("value", [1, 1.5, None, True, b"1"])
def test_non_text_rejected(value: object) -> None:
    assert not is_decimal_text(value)
    with pytest.raises(ValueError):
        parse_decimal(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(("a", "b", "expected"), TABLE, ids=[f"{a}|{b}" for a, b, _ in TABLE])
def test_c01_consistency_table(a: str, b: str, expected: bool) -> None:
    assert numbers_consistent(a, b) is expected
    assert numbers_consistent(b, a) is expected


def test_null_rules() -> None:
    assert numbers_consistent(None, None)
    assert not numbers_consistent(None, "0")
    assert not numbers_consistent("0", None)


def test_consistency_rejects_invalid_text() -> None:
    with pytest.raises(ValueError):
        numbers_consistent("1e5", "100000")


@pytest.mark.parametrize(
    ("value", "text"),
    [(Decimal("1.50"), "1.50"), (Decimal("1E+5"), "100000"), (Decimal("1E-7"), "0.0000001"),
     (Decimal("-0.00"), "0.00"), (Decimal("-12.30"), "-12.30"), (Decimal("0"), "0")],
)
def test_format_examples(value: Decimal, text: str) -> None:
    assert format_decimal(value) == text


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_format_rejects_non_finite(value: Decimal) -> None:
    with pytest.raises(ValueError):
        format_decimal(value)


# ---------------------------------------------------------------- 基于属性的测试

TEXTS = st.from_regex(r"-?[0-9]{1,40}(\.[0-9]{1,40})?", fullmatch=True)
DECIMALS = st.builds(
    lambda sign, digits, exp: Decimal((sign, tuple(int(c) for c in digits), exp)),
    st.integers(0, 1),
    st.from_regex(r"[0-9]{1,40}", fullmatch=True),
    st.integers(-40, 40),
)


@given(TEXTS)
def test_text_format_then_parse_keeps_value(text: str) -> None:
    value = parse_decimal(text)
    formatted = format_decimal(value)
    assert is_decimal_text(formatted)
    assert parse_decimal(formatted) == value


@given(DECIMALS)
def test_any_decimal_format_then_parse_keeps_value(value: Decimal) -> None:
    formatted = format_decimal(value)
    assert is_decimal_text(formatted)
    assert parse_decimal(formatted) == value


def _oracle_key(text: str) -> Decimal:
    """独立的参考实现：用足够的精度向零截断到 15 位小数。Decimal 比较相等时 -0 与 0 相等。"""
    return Decimal(text).quantize(Decimal("1E-15"), rounding=ROUND_DOWN, context=Context(prec=200))


@given(TEXTS, TEXTS)
def test_consistency_matches_truncation_oracle(a: str, b: str) -> None:
    assert numbers_consistent(a, b) is (_oracle_key(a) == _oracle_key(b))


@st.composite
def _near_pairs(draw: st.DrawFn) -> tuple[str, str]:
    """只在小数第 10–20 位中的某一位不同的两个数，覆盖第 15、16 位的边界。"""
    a = draw(st.from_regex(r"-?[0-9]{1,20}\.[0-9]{20}", fullmatch=True))
    pos = a.index(".") + draw(st.integers(10, 20))
    digit = str((int(a[pos]) + draw(st.integers(1, 9))) % 10)
    return a, a[:pos] + digit + a[pos + 1:]


@given(_near_pairs())
def test_near_pairs_match_truncation_oracle(pair: tuple[str, str]) -> None:
    a, b = pair
    assert numbers_consistent(a, b) is (_oracle_key(a) == _oracle_key(b))


@given(TEXTS)
def test_consistency_reflexive(a: str) -> None:
    assert numbers_consistent(a, a)


@given(TEXTS, TEXTS)
def test_consistency_symmetric(a: str, b: str) -> None:
    assert numbers_consistent(a, b) is numbers_consistent(b, a)


def _same_class(head: str, tails: tuple[str, str, str], signs: tuple[bool, bool, bool], zero: bool) -> list[str]:
    """前 15 位小数相同、只在第 16 位以后不同的三个数；整数部分和前 15 位都为零时正负号可以不同。"""
    if zero:
        return [("-" if negative else "") + "0." + "0" * 15 + tail for tail, negative in zip(tails, signs, strict=True)]
    return [head + tail for tail in tails]


CLASS_HEADS = st.from_regex(r"-?[0-9]{1,20}\.[0-9]{15}", fullmatch=True)
TAILS = st.from_regex(r"[0-9]{0,10}", fullmatch=True)


@given(CLASS_HEADS, st.tuples(TAILS, TAILS, TAILS), st.tuples(st.booleans(), st.booleans(), st.booleans()),
       st.booleans(), TEXTS)
def test_consistency_transitive(head: str, tails: tuple[str, str, str], signs: tuple[bool, bool, bool],
                                zero: bool, other: str) -> None:
    x, y, z = _same_class(head, tails, signs, zero)
    assert numbers_consistent(x, y) and numbers_consistent(y, z) and numbers_consistent(x, z)
    for a, b, c in ((x, y, other), (other, x, y), (x, other, y)):
        if numbers_consistent(a, b) and numbers_consistent(b, c):
            assert numbers_consistent(a, c)
