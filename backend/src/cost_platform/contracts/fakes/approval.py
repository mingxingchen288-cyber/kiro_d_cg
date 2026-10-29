"""approval 的 `FreezeReader` 替代实现（C08 第 13 节）。"""

from __future__ import annotations

from ..ports import UnitOfWork
from ..types import FreezeEntry
from ._script import Scripted


class FakeFreezeReader(Scripted):
    """`FreezeReader`：冻结记录由 `freeze` 预设，按（根表、主键）登记；同一份数据同一时间只能属于一个审批（approval AP-06）。"""

    scriptable = ('find',)

    def __init__(self) -> None:
        super().__init__()
        self._entries: dict[tuple[str, str], FreezeEntry] = {}

    def freeze(self, entry: FreezeEntry) -> None:
        key = (entry.table, entry.record_key)
        if key in self._entries and self._entries[key].approval_id != entry.approval_id:
            raise ValueError(f"{entry.table}/{entry.record_key} 已被审批 {self._entries[key].approval_id} 冻结")
        self._entries[key] = entry

    def release(self, approval_id: str) -> None:
        """解除一个审批的全部冻结。"""
        for key in [k for k, e in self._entries.items() if e.approval_id == approval_id]:
            del self._entries[key]

    def find(self, uow: UnitOfWork, table: str, record_keys: list[str]) -> dict[str, FreezeEntry]:
        self._record("find", uow, table, record_keys)
        return {key: self._entries[(table, key)] for key in record_keys if (table, key) in self._entries}
