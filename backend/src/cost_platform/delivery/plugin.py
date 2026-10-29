"""delivery 插件（`.reports/modules/plugin-spec.md` 第 2 节）。

- `DeliveryDispatcher`：`DeliveryService`，orchestration 在命令提交后调用 `dispatch_now`（DL-02）；
- 管道阶段"登记通知"（`RegisterNotificationsStage`，命令事务内，DL-01）。"投递"不是管道位置，`DispatchStage` 不注册
  （plugin-spec 第 3 节：提交后由 orchestration 直接调用 `DeliveryDispatcher`）；
- C09 第 7 节的路由（站内通知、投递记录管理），执行上下文由 assembly 的 `ContextProvider` 生成；
- 后台重试（DL-03）：start 时在后台线程中运行 `run_retry_loop`，stop 时通知它结束并等它退出。

平台表迁移目录为 `MIGRATIONS`。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from fastapi import APIRouter

from cost_platform.contracts.ports import (
    Clock,
    ContextProvider,
    DeliveryDispatcher,
    IdGenerator,
    PipelineStage,
    RealtimePublisher,
    UnitOfWorkFactory,
)
from cost_platform.contracts.registry import PluginView

from . import migrations
from .router import delivery_router
from .service import DeliveryService
from .stages import RegisterNotificationsStage
from .worker import run_retry_loop

__all__ = ["MIGRATIONS", "DeliveryPlugin"]

MIGRATIONS = Path(migrations.__file__).parent
"""PF_DELIVERY、PF_INBOX（assembly 的 `platform db` 用）。"""


class DeliveryPlugin:
    name = "delivery"
    provides = (DeliveryDispatcher, PipelineStage, APIRouter)
    requires = (UnitOfWorkFactory, RealtimePublisher, Clock, IdGenerator, ContextProvider)

    def __init__(self) -> None:
        self._service: DeliveryService          # setup 中创建，后台重试用
        self._stop = threading.Event()
        self._thread: threading.Thread          # start 中创建

    def setup(self, reg: PluginView) -> None:
        service = DeliveryService(reg.get(UnitOfWorkFactory), reg.get(RealtimePublisher), reg.get(Clock),
                                  reg.get(IdGenerator))
        reg.provide(DeliveryDispatcher, service)
        reg.add(PipelineStage, RegisterNotificationsStage(service))
        reg.add(APIRouter, delivery_router(service, reg.get(ContextProvider).context))
        self._service = service

    async def start(self) -> None:
        """启动后台重试线程：先执行一轮，之后每分钟一轮（DL-03）。"""
        self._stop.clear()
        self._thread = threading.Thread(target=run_retry_loop, args=(self._service, self._stop),
                                        name="delivery-retry", daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        """通知后台线程结束；正在执行的一轮发完后线程退出。"""
        self._stop.set()
        await asyncio.to_thread(self._thread.join)
