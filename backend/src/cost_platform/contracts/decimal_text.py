"""十进制文本（C01 第 2、3 节）：解析、格式化和数值一致的判定。

精确数值在 JSON 中都是 `^-?[0-9]+(\\.[0-9]+)?$` 格式的字符串，在后端内部为 Decimal，全程不经过二进制浮点。
前端的同名实现在 frontend/src/contracts/decimal-text.ts，Rust 的在 rules-core，三端用 C01 的同一批样例测试。
"""

from __future__ import annotations

import re
from decimal import Decimal

_PATTERN = re.compile(r"(-?)([0-9]+)(?:\.([0-9]+))?")

CONSISTENT_PLACES = 15
"""数值一致判定比较的小数位数（C01 第 3 节）。"""


def is_decimal_text(value: object) -> bool:
    return isinstance(value, str) and _PATTERN.fullmatch(value) is not None


def _match(text: object) -> re.Match[str]:
    match = _PATTERN.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        raise ValueError(f"不是十进制文本：{text!r}")
    return match


def parse_decimal(text: str) -> Decimal:
    """把十进制文本解析为 Decimal；格式不合法时抛 ValueError。"""
    _match(text)
    return Decimal(text)


def format_decimal(value: Decimal) -> str:
    """把 Decimal 格式化为十进制文本：不用指数，保留原有的小数位，零不带负号。"""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"不能格式化为十进制文本：{value!r}")
    sign, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    text = "".join(str(d) for d in digits)
    if exponent >= 0:
        text += "0" * exponent
    else:
        places = -exponent
        text = text.rjust(places + 1, "0")
        text = f"{text[:-places]}.{text[-places:]}"
    if sign and any(digits):
        text = "-" + text
    return text


def _consistency_key(text: str) -> tuple[bool, str, str]:
    """正负号、整数部分、截断（不舍入）到 15 位的小数部分；截断后为零的数不区分正负。"""
    negative, integer, fraction = _match(text).groups()
    integer = integer.lstrip("0") or "0"
    fraction = (fraction or "")[:CONSISTENT_PLACES].ljust(CONSISTENT_PLACES, "0")
    is_zero = integer == "0" and fraction == "0" * CONSISTENT_PLACES
    return (negative == "-" and not is_zero, integer, fraction)


def numbers_consistent(a: str | None, b: str | None) -> bool:
    """C01 第 3 节：两个数值是否一致。都为空时一致，一方为空时不一致；文本格式不合法时抛 ValueError。"""
    if a is None or b is None:
        return a is None and b is None
    return _consistency_key(a) == _consistency_key(b)
