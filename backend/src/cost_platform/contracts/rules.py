"""规则内核的输入输出形状（与 rules-core 的 JSON 接口一致）。

计算与规则判断只在 rules-core 中实现一次；这里只定义调用双方约定的数据形状。
精确数值一律为十进制文本。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class RuleEffect(StrEnum):
    REJECT = "reject"
    """拒绝：整笔回滚。"""
    SUBMIT_FOR_APPROVAL = "approve"
    """送审。"""
    PROMPT = "prompt"
    """提示：不阻止写入。"""


@dataclass(frozen=True, slots=True)
class RulesPackRef:
    """一个规则包：按（作用对象, 配置版本）生成，前后端加载同一份。"""

    pack_id: str
    version: str
    content: bytes
    """规则包的 JSON 文本（UTF-8）。"""


@dataclass(frozen=True, slots=True)
class EvaluationRequest:
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
