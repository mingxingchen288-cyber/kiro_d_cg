"""Redis 频道上的真实验证（T-RT-1 验收标准"真实验证"）。本次没有运行（本机没有 Redis），由合并后统一运行。

- `ChannelPublisher` + `RedisChannel` 通过 `RealtimePublisher` 的契约测试；
- 两个进程：本测试进程挂着 `/ws` 连接，另一个操作系统进程（publish_event.py）经 Redis 发布事件，连接收到。

连接取根目录 `.env` 的 `PLATFORM_REDIS_URL`、`PLATFORM_REDIS_NAMESPACE`；频道用 `<namespace>:ct-realtime:events`，
不影响正在运行的平台。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from cost_platform.contracts.types import ChannelEvent, RealtimeEvent, dump_wire, parse_wire
from cost_platform.realtime import ChannelPublisher, RedisChannel, channel_name

from ..contracts.test_realtime_publisher import RealtimePublisherContract
from .support import ADMIN, COST_PINGGU, Env, config_changed, connect, event_id, read_env, recv_json, subscribe

pytestmark = pytest.mark.redis

PUBLISH_SCRIPT = Path(__file__).with_name("publish_event.py")


@pytest.fixture
def redis_target() -> tuple[str, str]:
    env = read_env("PLATFORM_REDIS_URL", "PLATFORM_REDIS_NAMESPACE")
    return env["PLATFORM_REDIS_URL"], f"{env.get('PLATFORM_REDIS_NAMESPACE', 'cp')}:ct-realtime"


class SwitchChannel:
    """把发布转给 `target`；`break_channel` 时换成连不上的 Redis（端口 1）。"""

    def __init__(self, target: RedisChannel) -> None:
        self.target = target

    def publish(self, message: str) -> None:
        self.target.publish(message)

    async def subscribe(self) -> Any:
        return await self.target.subscribe()


class RedisPublisherHarness:
    def __init__(self, url: str, namespace: str) -> None:
        import redis

        self._namespace = namespace
        self._client = redis.Redis.from_url(url)
        self._pubsub = self._client.pubsub()
        self._pubsub.subscribe(channel_name(namespace))
        confirm = self._pubsub.get_message(timeout=5)
        assert confirm is not None and confirm["type"] == "subscribe"
        self.channel = SwitchChannel(RedisChannel.from_url(url, namespace))
        self.publisher = ChannelPublisher(self.channel)

    def received(self) -> list[RealtimeEvent]:
        events: list[RealtimeEvent] = []
        while (message := self._pubsub.get_message(timeout=1)) is not None:
            if message["type"] == "message":
                events.append(parse_wire(ChannelEvent, json.loads(message["data"])))
        return events

    def break_channel(self) -> None:
        import redis

        unreachable = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=1)
        self.channel.target = RedisChannel(unreachable, self._namespace, connect_async=lambda: None)

    def close(self) -> None:
        self._pubsub.close()
        self._client.close()


class TestRedisChannelPublisher(RealtimePublisherContract):
    @pytest.fixture
    def harness(self, redis_target: tuple[str, str]) -> Iterator[RedisPublisherHarness]:
        harness = RedisPublisherHarness(*redis_target)
        yield harness
        harness.close()


def test_event_from_another_process_reaches_connection(redis_target: tuple[str, str]) -> None:
    """E18 在两个进程上：另一个进程发布成本核算页的配置变更，连在本进程、开着成本核算页的浏览器收到。"""
    url, namespace = redis_target
    env = Env(channel=RedisChannel.from_url(url, namespace))
    admin = env.login(ADMIN)
    event = config_changed(1, [COST_PINGGU], 13)
    with env.process() as (_rt, client), connect(client, admin.session_id) as ws:
        subscribe(ws, COST_PINGGU)
        subprocess.run([sys.executable, str(PUBLISH_SCRIPT), json.dumps(dump_wire(ChannelEvent, event))],
                       env={**os.environ, "PLATFORM_REDIS_URL": url, "PLATFORM_REDIS_NAMESPACE": namespace},
                       check=True, timeout=30)
        assert recv_json(ws) == {"topic": "config.changed", "eventId": event_id(1),
                                 "payload": {"pages": [COST_PINGGU], "version": 13}}
