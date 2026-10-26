"""单据聚合与行状态：加锁后读到的当前数据，在领域层内部以 Python 值表示。

行值的键是字段编码（不是物理列名）；数值用 Decimal，日期用 date/datetime，不出现 float。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


def _readonly(values: Mapping[str, Any]) -> Mapping[str, Any]:
    return values if isinstance(values, MappingProxyType) else MappingProxyType(dict(values))


@dataclass(frozen=True, slots=True)
class TableBinding:
    """一个实体落在哪张物理表上。由元数据生成，写入适配器据此构造 SQL。"""

    entity: str
    table: str
    key_field: str
    columns: Mapping[str, str]
    """可读写字段：字段编码 → 物理列名（含主键字段和上级字段）。"""
    schema: str | None = None
    parent_field: str | None = None
    """明细中指向上级主键的字段编码。"""
    key_sequence: str | None = None
    """新增行取主键用的序列；为空表示由调用方给出主键。"""
    read_view: str | None = None
    """列表查询使用的视图（可含展示用的派生字段）。"""

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", _readonly(self.columns))
        if self.key_field not in self.columns:
            raise ValueError(f"{self.entity}: 主键字段 {self.key_field} 必须在 columns 中")
        if self.parent_field is not None and self.parent_field not in self.columns:
            raise ValueError(f"{self.entity}: 上级字段 {self.parent_field} 必须在 columns 中")


@dataclass(frozen=True, slots=True)
class RowState:
    entity: str
    key: str
    values: Mapping[str, Any]
    parent_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _readonly(self.values))


@dataclass(frozen=True, slots=True)
class DocumentState:
    """一张单据（主表一行 + 各明细）在加锁后的当前值。"""

    entity: str
    master: RowState | None
    details: Mapping[str, tuple[RowState, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _readonly(self.details))
