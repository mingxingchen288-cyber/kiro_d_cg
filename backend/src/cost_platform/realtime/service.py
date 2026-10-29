"""一个后端进程中的 realtime：把频道、连接表、分发、订阅任务、`/ws` 和 `RealtimePublisher` 组合在一起。

接线见 `plugin.py`（`realtime.publisher`、`realtime` 两个插件）；单独使用时的接法：

```python
channel = RedisChannel.from_url(settings.redis_url, settings.redis_namespace)   # 或 MemoryChannel()
realtime = Realtime(identity_authenticator, channel, settings.allowed_origins)
app.include_router(realtime.router)                  # 挂载 /ws
# 应用启动时 await realtime.start()，关闭时 await realtime.stop()（FastAPI lifespan）
# realtime.publisher 交给 config、delivery、identity
```
"""

from __future__ import annotations

from collections.abc import Collection

from cost_platform.contracts.ports import Authenticator

from .channel import EventChannel
from .connections import ConnectionRegistry
from .dispatch import Dispatcher, Subscriber
from .publisher import ChannelPublisher
from .router import realtime_router


class Realtime:
    def __init__(self, authenticator: Authenticator, channel: EventChannel, allowed_origins: Collection[str]) -> None:
        self.registry = ConnectionRegistry()
        self.publisher = ChannelPublisher(channel)
        self.dispatcher = Dispatcher(self.registry)
        self.subscriber = Subscriber(channel, self.dispatcher)
        self.router = realtime_router(authenticator, self.registry, allowed_origins)

    async def start(self) -> None:
        """启动订阅任务；订阅成功后返回。"""
        await self.subscriber.start()

    async def stop(self) -> None:
        await self.subscriber.stop()
