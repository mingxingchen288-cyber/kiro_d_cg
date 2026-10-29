"""订阅任务和按 audience 分发（RT-03、RT-04）。

每个后端进程一个订阅任务：从频道逐条读取事件，交给 `Dispatcher` 推给本进程中 audience 匹配的连接。
本进程发布的事件也经频道回到这里，和别的进程发布的事件走同一条路。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from .channel import EventChannel, Subscription
from .connections import ConnectionRegistry
from .messages import decode_event, push_text

logger = logging.getLogger("cost_platform.realtime")


class Dispatcher:
    def __init__(self, registry: ConnectionRegistry) -> None:
        self._registry = registry

    def deliver(self, message: str) -> None:
        """把一条频道消息推给 audience 匹配的连接。

        `session.revoked`（RT-04）：推送后关闭连接，并立即从连接表中去掉，之后的事件不再推给它。
        """
        event = decode_event(message)
        text = push_text(event)
        for conn in self._registry.matching(event.audience):
            conn.send(text)
            if event.topic == "session.revoked":
                conn.end()
                self._registry.remove(conn)


class Subscriber:
    """订阅任务。assembly 在应用启动时 `await start()`（订阅成功后返回），关闭时 `await stop()`。

    读取频道出错时（例如 Redis 断开）记日志，等 `retry_seconds` 秒后继续读；redis-py 会重新连接并恢复订阅。
    一条消息不符合 C10 时记日志并跳过，不影响后面的消息。这两种情况都没有测试，上线后按实际情况再补。
    """

    def __init__(self, channel: EventChannel, dispatcher: Dispatcher, retry_seconds: float = 1.0) -> None:
        self._channel = channel
        self._dispatcher = dispatcher
        self._retry = retry_seconds
        self._subscription: Subscription | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._subscription = await self._channel.subscribe()
        self._task = asyncio.create_task(self._run(self._subscription), name="realtime-subscriber")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._subscription is not None:
            await self._subscription.close()
            self._subscription = None

    async def _run(self, subscription: Subscription) -> None:
        while True:
            try:
                message = await subscription.receive()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("读取实时事件频道失败，%s 秒后重试", self._retry, exc_info=True)
                await asyncio.sleep(self._retry)
                continue
            try:
                self._dispatcher.deliver(message)
            except Exception:
                logger.warning("实时事件不符合 C10，已跳过：%.200s", message, exc_info=True)
