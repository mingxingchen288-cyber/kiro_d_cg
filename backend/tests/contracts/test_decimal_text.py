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
    trailing = re.search(r"^- 末尾零不影响数值是否相等，例如 `([^`]*)` 与 `([^`]*)` 相等", text, flags=re.M)
    section = text.split("## 3.", 1)[1].split("## 4.", 1)[0]
    table: list[tuple[str, str, bool]] = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[2] in ("一致", "不一致"):
            table += [(a, b, cells[2] == "一致") for a in _quoted(cells[0]) for b in _quoted(cells[1])]
    # 第 2 节"末尾零不影响数值是否相等"的样例也按一致处理
    table.append((trailing.group(1), trailing.group(2), True))
    return valid, invalid, table


VALID, INVALID, TABLE = _c01()


def test_c01_samples_found() -> None:
    assert len(VALID) == 3
    assert len(INVALID) == 6
    assert len(TABLE) == 10


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
    with pytest.raises(ValueError):
        numbers_consistent(None, "abc")
    with pytest.raises(ValueError):
        numbers_consistent("abc", None)


# 跨越第 15 位截断边界的数对：差值不到 1E-15，但整数部分或前 15 位小数不同。
BOUNDARY = [
    ("0.9999999999999999", "1", False),
    ("1.0000000000000009", "1.000000000000001", False),
    ("-0.9999999999999999", "-1", False),
    ("123.4567890123456789", "123.456789012345679", False),
    ("0.0000000000000009", "-0.0000000000000009", True),
    ("1.0000000000000001", "1.0000000000000009", True),
]


@pytest.mark.parametrize(("a", "b", "expected"), BOUNDARY, ids=[f"{a}|{b}" for a, b, _ in BOUNDARY])
def test_boundary_pairs(a: str, b: str, expected: bool) -> None:
    assert numbers_consistent(a, b) is expected
    assert numbers_consistent(b, a) is expected


LONG = [
    "12345678901234567890123456789012345.123456789012345678901234567890",
    "-0.00000000000000000000000000000000000001",
    "99999999999999999999999999999999999999999",
]


@pytest.mark.parametrize("text", LONG)
def test_long_text_keeps_every_digit(text: str) -> None:
    assert format_decimal(parse_decimal(text)) == text


@pytest.mark.parametrize(
    ("value", "text"),
    [(Decimal("1.50"), "1.50"), (Decimal("1E+5"), "100000"), (Decimal("1E-7"), "0.0000001"),
     (Decimal("-0.00"), "0.00"), (Decimal("-12.30"), "-12.30"), (Decimal("0"), "0"), (Decimal("0E+3"), "0"),
     (Decimal("-0E+2"), "0")],
)
def test_format_examples(value: Decimal, text: str) -> None:
    assert format_decimal(value) == text


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_format_rejects_non_finite(value: Decimal) -> None:
    with pytest.raises(ValueError):
        format_decimal(value)


# ---------------------------------------------------------------- 基于属性的测试

def _digits(min_size: int, max_size: int) -> st.SearchStrategy[str]:
    """先抽长度再生成数字串，让超过 28 位的长数稳定出现。"""
    return st.integers(min_size, max_size).flatmap(lambda n: st.text("0123456789", min_size=n, max_size=n))


TEXTS = st.builds(
    lambda negative, integer, fraction: ("-" if negative else "") + integer + ("." + fraction if fraction else ""),
    st.booleans(), _digits(1, 45), _digits(0, 45),
)
DECIMALS = st.builds(
    lambda sign, digits, exp: Decimal((sign, tuple(int(c) for c in digits), exp)),
    st.integers(0, 1),
    _digits(1, 45),
    st.integers(-45, 45),
)


def _normalized(text: str) -> str:
    """独立于被测实现的规整写法：去掉整数部分的前导零，保留小数位，零不带负号。"""
    negative, integer, fraction = re.fullmatch(r"(-?)([0-9]+)(?:\.([0-9]+))?", text).groups()
    integer = integer.lstrip("0") or "0"
    body = integer + ("." + fraction if fraction else "")
    is_zero = set(integer + (fraction or "")) == {"0"}
    return ("-" if negative and not is_zero else "") + body


def test_long_numbers_are_generated() -> None:
    from hypothesis import find

    find(TEXTS, lambda s: len(s.replace("-", "").replace(".", "")) > 60)
    find(DECIMALS, lambda d: len(d.as_tuple().digits) > 40)


@given(TEXTS)
def test_text_format_then_parse_keeps_value(text: str) -> None:
    value = parse_decimal(text)
    formatted = format_decimal(value)
    assert is_decimal_text(formatted)
    assert formatted == _normalized(text)
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


def _text_of(units: int) -> str:
    """把以 1E-20 为单位的整数写成十进制文本：只做字符串运算，不经过被测实现和 Decimal 的上下文精度。"""
    digits = str(abs(units)).rjust(21, "0")
    return ("-" if units < 0 else "") + digits[:-20] + "." + digits[-20:]


@st.composite
def _cross_boundary(draw: st.DrawFn) -> tuple[str, str]:
    """取一个 15 位小数的边界 B，在 B 两侧各取一个与 B 相差不到 1E-15 的数。"""
    boundary = draw(st.integers(-10**25, 10**25)) * 10**5
    below = boundary - draw(st.integers(1, 10**5 - 1))
    above = boundary + draw(st.integers(0, 10**5 - 1))
    return _text_of(below), _text_of(above)


@given(_cross_boundary())
def test_cross_boundary_pairs_match_truncation_oracle(pair: tuple[str, str]) -> None:
    a, b = pair
    assert numbers_consistent(a, b) is (_oracle_key(a) == _oracle_key(b))


@given(st.integers(-10**25, 10**25), st.integers(50_000, 99_999), st.integers(50_000, 99_999))
def test_consistency_transitive_across_boundary(boundary: int, left: int, right: int) -> None:
    """B 两侧相邻差值都不到 1E-15、首尾相差超过 1E-15 的三个数：一致只能来自同一截断类，不能沿差值传递。"""
    x, y, z = (_text_of(boundary * 10**5 - left), _text_of(boundary * 10**5), _text_of(boundary * 10**5 + right))
    if numbers_consistent(x, y) and numbers_consistent(y, z):
        assert numbers_consistent(x, z)
    assert numbers_consistent(x, y) is (_oracle_key(x) == _oracle_key(y))
    assert numbers_consistent(y, z) is (_oracle_key(y) == _oracle_key(z))
    assert numbers_consistent(x, z) is (_oracle_key(x) == _oracle_key(z))


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
