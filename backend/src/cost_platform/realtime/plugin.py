"""realtime 的两个插件（`.reports/modules/plugin-spec.md` 第 2 节）。

- `realtime.publisher`：`RealtimePublisher`，把事件写入 Redis 频道 `{ns}:events`（RT-02）。identity、config、delivery 用它；
  它和 `realtime` 分开，是因为 `realtime` 要用 identity 的 `Authenticator`，放在一起会成环。
- `realtime`：`/ws`（RT-01），订阅任务按 audience 推给本进程的连接（RT-03、RT-04）；start 时订阅频道，stop 时停止。

两个插件各自创建自己的 `RedisChannel`，共享的只有 Redis：发布方写入频道，订阅任务从频道读出，本进程发布的事件也经
频道回到本进程的连接。Redis 客户端在第一次发布或订阅时才连接，setup 不连 Redis。
"""

from __future__ import annotations

from collections.abc import Collection

from fastapi import APIRouter

from cost_platform.contracts.ports import Authenticator, RealtimePublisher
from cost_platform.contracts.registry import PluginView

from .channel import RedisChannel
from .publisher import ChannelPublisher
from .service import Realtime

__all__ = ["RealtimePlugin", "RealtimePublisherPlugin"]


class RealtimePublisherPlugin:
    """构造参数取 `.env` 的 `PLATFORM_REDIS_URL`、`PLATFORM_REDIS_NAMESPACE`。"""

    name = "realtime.publisher"
    provides = (RealtimePublisher,)
    requires = ()

    def __init__(self, redis_url: str, redis_namespace: str) -> None:
        self._redis_url = redis_url
        self._namespace = redis_namespace

    def setup(self, reg: PluginView) -> None:
        reg.provide(RealtimePublisher, ChannelPublisher(RedisChannel.from_url(self._redis_url, self._namespace)))


class RealtimePlugin:
    """构造参数取 `.env` 的 `PLATFORM_REDIS_URL`、`PLATFORM_REDIS_NAMESPACE`、`PLATFORM_ALLOWED_ORIGINS`。"""

    name = "realtime"
    provides = (APIRouter,)
    requires = (Authenticator,)

    def __init__(self, redis_url: str, redis_namespace: str, allowed_origins: Collection[str]) -> None:
        self._redis_url = redis_url
        self._namespace = redis_namespace
        self._allowed_origins = frozenset(allowed_origins)
        self._realtime: Realtime                 # setup 中创建，start、stop 用

    def setup(self, reg: PluginView) -> None:
        channel = RedisChannel.from_url(self._redis_url, self._namespace)
        realtime = Realtime(reg.get(Authenticator), channel, self._allowed_origins)
        reg.add(APIRouter, realtime.router)
        self._realtime = realtime

    async def start(self) -> None:
        """启动订阅任务；订阅成功后返回。"""
        await self._realtime.start()

    async def stop(self) -> None:
        await self._realtime.stop()
