"""一个命令中本模块在各轮动作之间要记住的内容（OP-01）。

C08 第 6 节规定动作执行每个动作一轮，阶段之间只经 `CommandState` 传递数据；`CommandState` 中没有"执行到第几个动作"
"前面 updateRecords 找到了哪些目标""哪些单据到传播边界为止""逃生舱的调用记录"这几项（见
`.reports/modules/operations/contract-gaps.md`）。在契约补上之前，这些内容按 `CommandState` 对象记在本模块中，
命令结束、`CommandState` 被回收时一起丢弃。
"""

from __future__ import annotations

import threading
import weakref
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from cost_platform.contracts.decimal_text import format_decimal
from cost_platform.contracts.types import CommandState, DocumentData, DocumentRef, Row, Value


@dataclass(frozen=True)
class Finding:
    """找到某个目标的一行来源：来源单据（计算后的数据）和这一行（主表行或某个明细行，C06 第 6 节）。"""

    source: DocumentData
    row: Row


@dataclass
class Target:
    """`updateRecords` 找到的一个对象（C08 第 9 节 `TargetObject`，不含 missing 的对象）。

    `document` 为所属单据（明细行为它的主单）；`row_key` 为要写的那一行：单据为主表行的主键，明细为明细主键。
    `found_by` 按来源行的先后记下找到它的每一行。"""

    entity: str
    document: DocumentRef
    row_key: str
    is_detail: bool
    found_by: list[Finding] = field(default_factory=list)


@dataclass(frozen=True)
class EscapeHatchCall:
    """一次逃生舱调用的审计记录（OP-04）：逃生舱、参数、执行人、时间和请求键。

    `target` 为调用的存储过程名、登记的语句或处理函数的名称；`writes` 为配置中登记的会修改的表和列（C06 第 4 节）。"""

    operation: str
    kind: Literal["procedure", "statement", "handler"]
    target: str
    params: dict[str, Value]
    outputs: dict[str, Value]
    writes: dict[str, list[str]]
    user_id: str
    user_name: str
    at: datetime
    request_key: str
    approval_id: str | None

    def to_record(self) -> dict[str, object]:
        """写进命令记录的 JSON（键为 camelCase，值按 C01 写成文本）。"""
        return {
            "operation": self.operation, "kind": self.kind, "target": self.target,
            "params": {k: _text(v) for k, v in self.params.items()},
            "outputs": {k: _text(v) for k, v in self.outputs.items()},
            "writes": {k: list(v) for k, v in self.writes.items()},
            "userId": self.user_id, "userName": self.user_name,
            "at": self.at.strftime("%Y-%m-%dT%H:%M:%S"), "requestKey": self.request_key, "approvalId": self.approval_id,
        }


def _text(value: Value) -> str | bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return format_decimal(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


@dataclass
class CommandMemory:
    cursor: int = 0
    """下一个要执行的动作在 `CommandState.actions` 中的位置。"""
    selection_checked: bool = False
    targets: dict[tuple[str, str, str], Target] = field(default_factory=dict)
    """（实体、单据主键、行主键）→ 目标，按第一次找到的先后。"""
    propagation_ended: list[DocumentRef] = field(default_factory=list)
    escape_hatch_calls: list[EscapeHatchCall] = field(default_factory=list)


class MemoryBook:
    """按 `CommandState` 对象记下 `CommandMemory`；`CommandState` 被回收时删除。"""

    def __init__(self) -> None:
        self._items: dict[int, CommandMemory] = {}
        self._lock = threading.Lock()

    def peek(self, state: CommandState) -> CommandMemory | None:
        return self._items.get(id(state))

    def of(self, state: CommandState) -> CommandMemory:
        key = id(state)
        with self._lock:
            found = self._items.get(key)
            if found is None:
                found = CommandMemory()
                self._items[key] = found
                weakref.finalize(state, self._items.pop, key, None)
            return found
