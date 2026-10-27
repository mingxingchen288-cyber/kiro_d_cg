"""delivery 的 `DeliveryDispatcher` 替代实现（C08 第 10 节）。"""

from __future__ import annotations

from typing import Literal

from ._script import Scripted

DeliveryStatus = Literal["pending", "sent", "failed", "abandoned"]


class FakeDeliveryDispatcher(Scripted):
    """`DeliveryDispatcher`：投递记录由 `register` 预设，状态取 C09 投递记录的取值。

    `dispatch_now` 把能发送的记录标为 `sent`；`register(..., fails=True)` 的记录发送失败，标为 `failed`，
    不抛出错误（发送失败只记录）。没有登记的编号忽略。`dispatched` 按顺序记录每次收到的编号。
    """

    scriptable = ('dispatch_now',)

    def __init__(self) -> None:
        super().__init__()
        self.status: dict[str, DeliveryStatus] = {}
        self._fails: set[str] = set()
        self.dispatched: list[list[str]] = []

    def register(self, delivery_id: str, *, fails: bool = False) -> None:
        self.status[delivery_id] = "pending"
        if fails:
            self._fails.add(delivery_id)
        else:
            self._fails.discard(delivery_id)

    def dispatch_now(self, delivery_ids: list[str]) -> None:
        self._record("dispatch_now", delivery_ids)
        self.dispatched.append(list(delivery_ids))
        for delivery_id in delivery_ids:
            if delivery_id in self.status:
                self.status[delivery_id] = "failed" if delivery_id in self._fails else "sent"
