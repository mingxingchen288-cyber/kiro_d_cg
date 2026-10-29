"""WebSocket 与实时事件（docs/模块/realtime.md，RT-01～RT-04）。

- `Realtime`：一个后端进程中的 realtime，提供 `router`（`/ws`）、`publisher`（`RealtimePublisher`）、`start`、`stop`；
- `MemoryChannel`、`RedisChannel`：后端进程之间的频道 `{ns}:events`（C10 第 1 节）；
- 其余为组成部分，单独使用时见各文件说明。
"""

from .channel import EventChannel, MemoryChannel, RedisChannel, Subscription, channel_name
from .connections import CLOSE_SESSION_ENDED, Connection, ConnectionRegistry
from .dispatch import Dispatcher, Subscriber
from .publisher import ChannelPublisher
from .router import SESSION_COOKIE, realtime_router
from .service import Realtime

__all__ = [
    "CLOSE_SESSION_ENDED",
    "SESSION_COOKIE",
    "ChannelPublisher",
    "Connection",
    "ConnectionRegistry",
    "Dispatcher",
    "EventChannel",
    "MemoryChannel",
    "Realtime",
    "RedisChannel",
    "Subscriber",
    "Subscription",
    "channel_name",
    "realtime_router",
]
