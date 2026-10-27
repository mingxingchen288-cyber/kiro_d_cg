"""realtime 的 `RealtimePublisher` 替代实现（C08 第 11 节）。"""

from __future__ import annotations

from ..types import RealtimeEvent
from ._script import Scripted


class FakeRealtimePublisher(Scripted):
    """`RealtimePublisher`：发布的事件写入 `events`，相当于内存中的频道。

    `break_channel` 之后发布失败：事件进入 `failed`，不抛出错误（发布失败只记日志，C08 第 11 节）。
    """

    scriptable = ('publish',)

    def __init__(self) -> None:
        super().__init__()
        self.events: list[RealtimeEvent] = []
        self.failed: list[RealtimeEvent] = []
        self.broken = False

    def break_channel(self) -> None:
        self.broken = True

    def restore_channel(self) -> None:
        self.broken = False

    def publish(self, event: RealtimeEvent) -> None:
        self._record("publish", event)
        (self.failed if self.broken else self.events).append(event)
