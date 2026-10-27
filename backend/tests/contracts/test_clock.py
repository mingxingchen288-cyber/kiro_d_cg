"""`Clock` 的契约测试（C08 第 12 节）。真实实现（assembly）的测试继承 `ClockContract`，提供 `harness` fixture。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeClock
from cost_platform.contracts.ports import Clock


class ClockHarness(Protocol):
    clock: Clock


class ClockContract:
    @pytest.fixture
    def harness(self) -> ClockHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_now_is_naive_datetime(self, harness: ClockHarness) -> None:
        """时间按服务器时区，不带时区（C01 第 4 节），直接用于执行上下文的 now 和日期时间字段。"""
        now = harness.clock.now()
        assert isinstance(now, datetime)
        assert now.tzinfo is None


class FakeClockHarness:
    def __init__(self) -> None:
        self.clock = FakeClock()


class TestFakeClock(ClockContract):
    @pytest.fixture
    def harness(self) -> FakeClockHarness:
        return FakeClockHarness()


def test_fake_clock_moves_only_when_told() -> None:
    clock = FakeClock(datetime(2026, 10, 24, 10, 0, 0))
    assert clock.now() == clock.now() == datetime(2026, 10, 24, 10, 0, 0)
    clock.advance(timedelta(minutes=5))
    assert clock.now() == datetime(2026, 10, 24, 10, 5, 0)
    clock.set(datetime(2027, 1, 1))
    assert clock.now() == datetime(2027, 1, 1)
    from datetime import UTC

    with pytest.raises(ValueError):
        clock.set(datetime(2027, 1, 1, tzinfo=UTC))
