"""契约层的公共类型。

只描述数据形状，不含业务判断。对外 JSON 一律用 camelCase；精确数值一律用十进制文本，
不经过浮点（JSON 里的小数会被拒绝，见 Scalar）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Annotated, Any, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    JsonValue,
    PlainSerializer,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
)
from pydantic.alias_generators import to_camel


class Contract(BaseModel):
    """所有对外契约模型的基类：不可变、拒绝未知字段、JSON 用 camelCase。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
        validate_default=True,
    )


Identifier = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=200, pattern=r"^\S(?:.*\S)?$")
]
"""非空、首尾无空白的标识（主键文本、临时行号等）。"""

Code = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_.:\-]*$")
]
"""配置编码：实体、字段、页面、操作、规则等。"""

DECIMAL_TEXT_PATTERN = r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"
DecimalText = Annotated[str, StringConstraints(strict=True, max_length=80, pattern=DECIMAL_TEXT_PATTERN)]
"""十进制数值的文本形式，例如 "12.50"、"-3"。"""

Scalar = StrictStr | StrictInt | StrictBool | None
"""Patch 中允许的字段值。小数必须以字符串传入，JSON 浮点数会被拒绝。"""

_DECIMAL_TEXT = re.compile(DECIMAL_TEXT_PATTERN)


def is_decimal_text(value: object) -> bool:
    return isinstance(value, str) and bool(_DECIMAL_TEXT.fullmatch(value))


def freeze(value: Any) -> Any:
    """把已校验的 JSON 结构复制成只读容器（Mapping → MappingProxyType，list → tuple）。"""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """freeze 的逆过程，供序列化使用。"""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


K = TypeVar("K")
V = TypeVar("V")

FrozenMapping = Annotated[Mapping[K, V], AfterValidator(freeze), PlainSerializer(thaw, return_type=dict)]
FieldValues = Annotated[
    Mapping[Identifier, Scalar],
    AfterValidator(freeze),
    PlainSerializer(thaw, return_type=dict[str, Scalar]),
]
Parameters = Annotated[
    Mapping[Identifier, JsonValue],
    AfterValidator(freeze),
    PlainSerializer(thaw, return_type=dict[str, JsonValue]),
]


def to_json_value(value: Any) -> Any:
    """把领域值转成 JSON 值：Decimal → 十进制文本，日期 → ISO 文本。不产生浮点数。"""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("非有限的十进制数不能输出")
        text = format(value, "f")
        return text
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds") if value.microsecond == 0 else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        raise TypeError("领域值中不允许出现浮点数")
    if isinstance(value, Mapping):
        return {key: to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """规范化 JSON：键排序、无多余空白、保留中文。用于计算内容摘要。"""
    return json.dumps(to_json_value(thaw(value)), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
