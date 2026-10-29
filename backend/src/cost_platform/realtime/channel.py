"""后端进程之间传递事件的频道（C10 第 1 节）。

频道名为 `{ns}:events`，`{ns}` 取 `.env` 的 `PLATFORM_REDIS_NAMESPACE`。频道里的消息是 C10 第 1 节的 JSON 文本，
编码解码见 messages.py。

- `publish` 是同步调用：发布方（config、delivery、identity）在请求的线程池里调用它。
- `subscribe` 在订阅任务的事件循环里调用，订阅成功后才返回；之后用 `Subscription.receive` 逐条读取。

两种实现：
- `MemoryChannel`：进程内存中的频道，用于模拟验证和本机没有 Redis 的开发环境。把同一个实例交给几套
  `Realtime`，相当于几个后端进程共用一个 Redis；真正的多个操作系统进程之间不能共用。
- `RedisChannel`：上线用的实现，发布用 redis-py 的同步客户端，订阅用 `redis.asyncio`。
  真实验证的测试（tests/realtime/test_redis.py）标了 `redis`，本次没有运行。
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any, Protocol


def channel_name(namespace: str) -> str:
    return f"{namespace}:events"


class Subscription(Protocol):
    async def receive(self) -> str:
        """下一条消息；没有消息时等待。"""
        ...

    async def close(self) -> None: ...


class EventChannel(Protocol):
    def publish(self, message: str) -> None:
        """把一条消息写入频道；频道不可用时抛出错误，由 `ChannelPublisher` 记日志。"""
        ...

    async def subscribe(self) -> Subscription:
        """订阅频道；返回时已经订阅成功，之后发布的消息都能收到。"""
        ...


# ------------------------------------------------------------ 内存频道

class MemoryChannel:
    """进程内存中的频道（模拟验证、本机开发）。

    每个订阅有自己的队列和事件循环；`publish` 可以在任何线程调用，用 `call_soon_threadsafe` 交给订阅所在的事件循环。
    `listen` 登记一个同步回调，发布时在发布的线程里调用，供测试读取频道里的消息。
    """

    def __init__(self) -> None:
        self._listeners: list[Callable[[str], None]] = []
        self._lock = threading.Lock()

    def listen(self, callback: Callable[[str], None]) -> Callable[[], None]:
        """登记回调；返回取消登记的函数。"""
        with self._lock:
            self._listeners.append(callback)

        def cancel() -> None:
            with self._lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)

        return cancel

    def publish(self, message: str) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for callback in listeners:
            callback(message)

    async def subscribe(self) -> Subscription:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue()
        cancel = self.listen(lambda message: loop.call_soon_threadsafe(queue.put_nowait, message))
        return _MemorySubscription(queue, cancel)


class _MemorySubscription:
    def __init__(self, queue: asyncio.Queue[str], cancel: Callable[[], None]) -> None:
        self._queue = queue
        self._cancel = cancel

    async def receive(self) -> str:
        return await self._queue.get()

    async def close(self) -> None:
        self._cancel()


# ------------------------------------------------------------ Redis 频道

class RedisChannel:
    """Redis 发布订阅频道。

    - `client`：redis-py 的同步 `Redis`，`publish` 用它（一条 PUBLISH）。
    - `connect_async`：创建 `redis.asyncio.Redis` 的函数。异步客户端的连接属于创建它的事件循环，
      所以在 `subscribe` 里（订阅任务的事件循环中）才创建。
    """

    def __init__(self, client: Any, namespace: str, connect_async: Callable[[], Any]) -> None:
        self._redis = client
        self._connect_async = connect_async
        self.name = channel_name(namespace)

    @classmethod
    def from_url(cls, url: str, namespace: str) -> RedisChannel:
        """`url` 取 `.env` 的 `PLATFORM_REDIS_URL`。"""
        import redis
        import redis.asyncio

        return cls(redis.Redis.from_url(url), namespace, lambda: redis.asyncio.Redis.from_url(url))

    def publish(self, message: str) -> None:
        self._redis.publish(self.name, message)

    async def subscribe(self) -> Subscription:
        client = self._connect_async()
        pubsub = client.pubsub()
        await pubsub.subscribe(self.name)
        # 读到订阅确认才返回：这时 Redis 已经登记了订阅，之后发布的消息都会送到
        while (confirm := await pubsub.get_message(timeout=None)) is None or confirm["type"] != "subscribe":
            pass
        return _RedisSubscription(client, pubsub)


class _RedisSubscription:
    def __init__(self, client: Any, pubsub: Any) -> None:
        self._client = client
        self._pubsub = pubsub

    async def receive(self) -> str:
        while True:
            message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=None)
            if message is not None and message["type"] == "message":
                data = message["data"]
                return data.decode("utf-8") if isinstance(data, bytes) else str(data)

    async def close(self) -> None:
        await self._pubsub.aclose()
        await self._client.aclose()
