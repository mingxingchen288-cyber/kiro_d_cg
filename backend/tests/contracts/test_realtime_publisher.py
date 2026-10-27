"""`RealtimePublisher` 的契约测试（C08 第 11 节；事件格式见 C10，规则见 realtime 的 RT-02）。

真实实现（realtime）的测试继承 `RealtimePublisherContract`，提供 `harness` fixture，实现 `RealtimePublisherHarness`。
"""

from __future__ import annotations

from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeRealtimePublisher
from cost_platform.contracts.ports import RealtimePublisher
from cost_platform.contracts.types import ChannelEvent, RealtimeEvent, parse_wire

from .support import doc_json

EVENT = parse_wire(ChannelEvent, doc_json("C10", 0))


class RealtimePublisherHarness(Protocol):
    publisher: RealtimePublisher

    def received(self) -> list[RealtimeEvent]:
        """频道上收到的事件，按发布顺序。"""
        ...

    def break_channel(self) -> None:
        """让频道不可用。"""
        ...


class RealtimePublisherContract:
    @pytest.fixture
    def harness(self) -> RealtimePublisherHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_event_reaches_channel(self, harness: RealtimePublisherHarness) -> None:
        harness.publisher.publish(EVENT)
        assert harness.received() == [EVENT]

    def test_failure_does_not_raise(self, harness: RealtimePublisherHarness) -> None:
        """发布失败只记日志，不影响调用方已提交的事务。"""
        harness.break_channel()
        harness.publisher.publish(EVENT)


class FakeRealtimePublisherHarness:
    def __init__(self) -> None:
        self.publisher = FakeRealtimePublisher()

    def received(self) -> list[RealtimeEvent]:
        return list(self.publisher.events)

    def break_channel(self) -> None:
        self.publisher.break_channel()


class TestFakeRealtimePublisher(RealtimePublisherContract):
    @pytest.fixture
    def harness(self) -> FakeRealtimePublisherHarness:
        return FakeRealtimePublisherHarness()
