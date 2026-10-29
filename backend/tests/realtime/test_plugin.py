"""realtime 的两个插件（plugin-spec 第 2、5 节）。

- setup：用 contracts 的 `FakeAuthenticator` 提供 `Authenticator`，确认 provides 都注册了；
- 真实验证（Redis）：E18，`realtime.publisher` 注册的发布方写入 Redis 频道，`realtime` 的订阅任务（插件 start 启动）
  收到后推给开着成本核算页的连接。两个插件各有自己的 `RedisChannel`，共享的只有 Redis。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from cost_platform.contracts.fakes import FakeAuthenticator, FakeClock
from cost_platform.contracts.ports import Authenticator, RealtimePublisher
from cost_platform.contracts.registry import MULTI_PORTS, PluginView, Registry
from cost_platform.realtime import ChannelPublisher
from cost_platform.realtime.plugin import RealtimePlugin, RealtimePublisherPlugin

from .support import ADMIN, COST_PINGGU, NOW, ORIGIN, config_changed, connect, event_id, read_env, recv_json, subscribe


class Provider:
    """把给定的实现注册为端口（替代实现）。"""

    name = "fakes"
    requires: tuple[type, ...] = ()

    def __init__(self, impls: dict[type, Any]) -> None:
        self.provides = tuple(impls)
        self._impls = impls

    def setup(self, reg: PluginView) -> None:
        for port, impl in self._impls.items():
            reg.provide(port, impl)


class Probe:
    """只声明 requires 的插件：在 setup 中取出被测插件注册的实现（boot 结束后注册表冻结，不能再取）。"""

    name = "probe"
    provides: tuple[type, ...] = ()
    requires = (RealtimePublisher, APIRouter)

    def __init__(self) -> None:
        self.got: dict[type, Any] = {}

    def setup(self, reg: PluginView) -> None:
        self.got = {port: reg.all(port) if port in MULTI_PORTS else reg.get(port) for port in self.requires}


def _boot(url: str, namespace: str, auth: FakeAuthenticator) -> tuple[RealtimePlugin, Probe]:
    plugin, probe = RealtimePlugin(url, namespace, frozenset({ORIGIN})), Probe()
    ordered = Registry().boot([probe, plugin, RealtimePublisherPlugin(url, namespace), Provider({Authenticator: auth})])
    assert [p.name for p in ordered] == ["fakes", "realtime.publisher", "realtime", "probe"]
    return plugin, probe


def test_setup_registers_ports() -> None:
    _, probe = _boot("redis://127.0.0.1:6379/0", "ct-realtime-plugin", FakeAuthenticator(FakeClock(NOW)))
    assert isinstance(probe.got[RealtimePublisher], ChannelPublisher)
    [router] = probe.got[APIRouter]
    assert [r.path for r in router.routes] == ["/ws"]  # type: ignore[attr-defined]


@pytest.mark.redis
def test_published_event_reaches_connection_through_redis() -> None:
    env = read_env("PLATFORM_REDIS_URL", "PLATFORM_REDIS_NAMESPACE")
    url, namespace = env["PLATFORM_REDIS_URL"], f"{env.get('PLATFORM_REDIS_NAMESPACE', 'cp')}:ct-realtime-plugin"
    auth = FakeAuthenticator(FakeClock(NOW))
    auth.open_session(ADMIN, csrf_token="csrf-1")
    plugin, probe = _boot(url, namespace, auth)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:   # assembly 按 boot 的顺序调用 start，反序调用 stop
        await plugin.start()
        try:
            yield
        finally:
            await plugin.stop()

    app = FastAPI(lifespan=lifespan)
    [router] = probe.got[APIRouter]
    app.include_router(router)
    publisher: RealtimePublisher = probe.got[RealtimePublisher]
    event = config_changed(1, [COST_PINGGU], 13)
    with TestClient(app) as client, connect(client, ADMIN.session_id) as ws:
        subscribe(ws, COST_PINGGU)
        publisher.publish(event)
        assert recv_json(ws) == {"topic": "config.changed", "eventId": event_id(1),
                                 "payload": {"pages": [COST_PINGGU], "version": 13}}
