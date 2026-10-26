"""变更计划与审计差异：增量合并的输出，写入适配器只按它执行。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class ChangeKind(StrEnum):
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class RowChange:
    entity: str
    kind: ChangeKind
    values: Mapping[str, Any] = field(default_factory=dict)
    """UPDATE：只含有变化的列；INSERT：全部要写入的列；DELETE：为空。键为字段编码。"""
    before: Mapping[str, Any] = field(default_factory=dict)
    """UPDATE/DELETE：加锁后读到的旧值（只含相关列），用于审计。"""
    key: str | None = None
    client_row_id: str | None = None
    parent_key: str | None = None
    parent_client_row_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(self, "before", MappingProxyType(dict(self.before)))
        if self.kind is ChangeKind.INSERT:
            if self.client_row_id is None or self.key is not None:
                raise ValueError("新增必须带临时编号，且不能带主键")
        elif self.key is None:
            raise ValueError("修改和删除必须带主键")


@dataclass(frozen=True, slots=True)
class ChangePlan:
    """已按外键安全顺序排列：先插入上级再插入下级；先删除下级再删除上级。"""

    changes: tuple[RowChange, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.changes

    def of_kind(self, kind: ChangeKind) -> tuple[RowChange, ...]:
        return tuple(change for change in self.changes if change.kind is kind)


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """一个字段的一次变化。"""

    entity: str
    row_key: str | None
    client_row_id: str | None
    field: str
    before: Any
    after: Any
    kind: ChangeKind
