"""`Clock`、`IdGenerator` 的替代实现（C08 第 12 节）。"""

from __future__ import annotations

from datetime import datetime, timedelta

from ._script import Scripted


class FakeClock(Scripted):
    """`Clock`：时间只在 `advance`、`set` 时改变。时间不带时区，按服务器时区（C01 第 4 节）。"""

    scriptable = ('now',)

    def __init__(self, now: datetime = datetime(2026, 10, 24, 10, 0, 0)) -> None:
        super().__init__()
        self._now = self._naive(now)

    @staticmethod
    def _naive(value: datetime) -> datetime:
        if value.tzinfo is not None:
            raise ValueError("Clock 的时间不带时区（C01 第 4 节）")
        return value

    def set(self, now: datetime) -> None:
        self._now = self._naive(now)

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    def now(self) -> datetime:
        self._record("now")
        return self._now


class FakeIdGenerator(Scripted):
    """`IdGenerator`：依次给出 `00000000-0000-4000-8000-000000000001`、`…0002` 这样的小写 UUID，便于在测试中预知。"""

    scriptable = ('uuid',)

    def __init__(self, start: int = 1) -> None:
        super().__init__()
        self._next = start

    def uuid(self) -> str:
        self._record("uuid")
        value = f"00000000-0000-4000-8000-{self._next:012x}"
        self._next += 1
        return value
