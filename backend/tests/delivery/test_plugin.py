"""delivery 插件（plugin-spec 第 2、5 节）。

- setup：用 contracts 的替代实现提供 requires 的端口，确认 provides 都注册了，`DispatchStage` 没有注册；
- start/stop：后台重试线程补发 E23 中提交后没能立即发送的通知（DL-01、DL-03），stop 后线程退出。
"""

from __future__ import annotations

import asyncio
import threading
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request

from cost_platform.contracts.fakes import FakeRealtimePublisher
from cost_platform.contracts.ports import (
    Clock,
    ContextProvider,
    DeliveryDispatcher,
    IdGenerator,
    PipelineStage,
    RealtimePublisher,
    UnitOfWorkFactory,
)
from cost_platform.contracts.registry import MULTI_PORTS, PluginView, Registry
from cost_platform.contracts.types import ExecutionContext, RealtimeEvent
from cost_platform.delivery import DeliveryService, RegisterNotificationsStage
from cost_platform.delivery.plugin import MIGRATIONS, DeliveryPlugin

from .support import ADMIN, T0, YANG_NA, World, commit_registration, context, passed, state, world

PORTS = (DeliveryDispatcher, PipelineStage, APIRouter)


class Contexts:
    """`ContextProvider` 的最小替代：contracts 没有它的替代实现；这里每个请求都当作系统管理员。"""

    def context(self, request: Request, is_write: bool) -> ExecutionContext:
        return context(ADMIN)


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
    requires = PORTS

    def __init__(self) -> None:
        self.got: dict[type, Any] = {}

    def setup(self, reg: PluginView) -> None:
        self.got = {port: reg.all(port) if port in MULTI_PORTS else reg.get(port) for port in self.requires}


class PushSignal:
    """`RealtimePublisher`：转给 `FakeRealtimePublisher`，推送时置位 `pushed`。

    后台线程提交发送之后才推送，`pushed` 置位时这条投递已经提交。测试等它，不在后台线程运行时轮询数据库：
    替代事务的所有线程共用一个 SQLite 连接（support.py 的 `database()`），主线程读完库时的回滚会撤掉后台线程
    还没提交的写入，投递就停在 pending、站内通知没有写入。
    """

    def __init__(self, target: FakeRealtimePublisher) -> None:
        self._target = target
        self.pushed = threading.Event()

    def publish(self, event: RealtimeEvent) -> None:
        self._target.publish(event)
        self.pushed.set()


def _boot(w: World, publisher: RealtimePublisher | None = None) -> tuple[DeliveryPlugin, Probe]:
    """`publisher` 不给时用 `w.publisher`。"""
    plugin, probe = DeliveryPlugin(), Probe()
    fakes = Provider({UnitOfWorkFactory: w.factory, RealtimePublisher: publisher or w.publisher, Clock: w.clock,
                      IdGenerator: w.ids, ContextProvider: Contexts()})
    ordered = Registry().boot([probe, plugin, fakes])
    assert [p.name for p in ordered] == ["fakes", "delivery", "probe"]
    return plugin, probe


def test_setup_registers_ports() -> None:
    _, probe = _boot(world())
    assert isinstance(probe.got[DeliveryDispatcher], DeliveryService)
    [stage] = probe.got[PipelineStage]   # 只有"登记通知"；"投递"不是管道位置
    assert isinstance(stage, RegisterNotificationsStage) and stage.name == "登记通知"
    [router] = probe.got[APIRouter]
    assert {"/api/inbox", "/api/admin/deliveries"} <= {r.path for r in router.routes}  # type: ignore[attr-defined]
    assert (MIGRATIONS / "dl_0001_pf_delivery.py").is_file()


def test_retry_thread_sends_due_delivery_and_stops() -> None:
    """E23 最终批准后给杨娜的"已通过"通知已登记、提交，但提交后没能立即发送；1 分钟后插件启动的后台线程补发。"""
    w = world()
    [delivery_id] = commit_registration(w, state(passed()), context(YANG_NA))
    signal = PushSignal(w.publisher)
    plugin, _ = _boot(w, signal)
    w.clock.set(T0 + timedelta(minutes=1))

    asyncio.run(plugin.start())
    pushed = signal.pushed.wait(timeout=5)    # 上限只防后台线程没有推送时一直等；下一轮在 60 秒后
    asyncio.run(plugin.stop())                # 线程退出后再读库

    assert pushed, "后台线程启动后的第一轮没有补发"
    assert w.delivery(delivery_id)["status"] == "sent"
    assert [r["user_id"] for r in w.inbox_rows()] == [YANG_NA]
    assert [e.payload.delivery_id for e in w.publisher.events] == [delivery_id]
    assert not plugin._thread.is_alive()
