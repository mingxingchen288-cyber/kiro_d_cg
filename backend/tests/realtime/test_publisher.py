"""`RealtimePublisher` 的真实实现 `ChannelPublisher`（C08 第 11 节、RT-02），频道为 `MemoryChannel`。

- 通过 contracts 的契约测试 `RealtimePublisherContract`；
- 频道中的消息就是 C10 第 1 节的 JSON；
- 频道不可用时只记日志，不抛出（RT-02）。

Redis 频道上的同一套测试见 test_redis.py。
"""

from __future__ import annotations

import json
import logging

import pytest

from cost_platform.contracts.types import ChannelEvent, RealtimeEvent, parse_wire
from cost_platform.realtime import ChannelPublisher, MemoryChannel

from ..contracts.support import doc_json
from ..contracts.test_realtime_publisher import RealtimePublisherContract


class BreakableChannel(MemoryChannel):
    """`MemoryChannel`，`broken` 之后发布时抛出连接错误，相当于 Redis 不可用。"""

    def __init__(self) -> None:
        super().__init__()
        self.broken = False

    def publish(self, message: str) -> None:
        if self.broken:
            raise ConnectionError("频道不可用")
        super().publish(message)


class MemoryPublisherHarness:
    def __init__(self) -> None:
        self.channel = BreakableChannel()
        self.messages: list[str] = []
        self.channel.listen(self.messages.append)
        self.publisher = ChannelPublisher(self.channel)

    def received(self) -> list[RealtimeEvent]:
        return [parse_wire(ChannelEvent, json.loads(m)) for m in self.messages]

    def break_channel(self) -> None:
        self.channel.broken = True


class TestChannelPublisher(RealtimePublisherContract):
    @pytest.fixture
    def harness(self) -> MemoryPublisherHarness:
        return MemoryPublisherHarness()


def test_channel_message_is_c10_json() -> None:
    """频道中的消息与 C10 第 1 节的样例相同。"""
    harness = MemoryPublisherHarness()
    sample = doc_json("C10", 0)
    harness.publisher.publish(parse_wire(ChannelEvent, sample))
    assert [json.loads(m) for m in harness.messages] == [sample]


def test_publish_failure_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    harness = MemoryPublisherHarness()
    harness.break_channel()
    with caplog.at_level(logging.WARNING, logger="cost_platform.realtime"):
        harness.publisher.publish(parse_wire(ChannelEvent, doc_json("C10", 0)))
    assert harness.messages == []
    assert any("6c2f0d6e-1b7a-4b55-9a1e-2f8f3c1d4e5a" in r.getMessage() for r in caplog.records)
