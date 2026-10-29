"""realtime 测试共用的环境（模拟验证）。

- 会话用 contracts 的 `FakeAuthenticator`，时间用 `FakeClock`；频道用 `MemoryChannel`（代替 Redis 频道）。
- 一个"进程"是一套 `Realtime` 加挂载它的 FastAPI 应用，和 assembly 的接法相同：`include_router(realtime.router)`，
  在 lifespan 中 `start()`、`stop()` 订阅任务。几个进程共用同一个 `MemoryChannel`，相当于共用一个 Redis。
- WebSocket 用 FastAPI 的 TestClient；必须在 `with TestClient(app)` 里使用，lifespan 才会启动订阅任务，
  连接和订阅任务也才在同一个事件循环中。
- TestClient 的 `receive` 没有超时，事件没到时会一直等。`recv` 加了 5 秒上限，用到了 TestClient 的内部属性
  `_send_rx`、`_raise_on_close`。
- 断言"某个连接没有收到事件"时，不等待超时：随后再发一条这个连接应当收到的事件，它收到的第一条就是这条。
  频道按发布顺序传递，订阅任务按顺序分发，所以前一条如果推给了它，会先到。
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import anyio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from cost_platform.contracts.fakes import FakeAuthenticator, FakeClock
from cost_platform.contracts.types import (
    ConfigChangedEvent,
    ConfigChangedPayload,
    Identity,
    NotificationEvent,
    NotificationPayload,
    PagesAudience,
    SessionRevokedEvent,
    SessionRevokedPayload,
    SessionsAudience,
    UsersAudience,
)
from cost_platform.realtime import EventChannel, MemoryChannel, Realtime

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "http://localhost:9527"          # .env.example 的 PLATFORM_ALLOWED_ORIGINS
NOW = datetime(2026, 10, 24, 10, 0, 0)
COST_PINGGU = "COST_PINGGU"               # 成本核算页
COST_MATERIAL = "COST_MATERIAL"           # 物料清单页

ADMIN = Identity(user_id="1", username="admin", display_name="系统管理员", department_id=None, role_code="ADMIN",
                 session_id="1.a")
CHENG = Identity(user_id="112", username="HY260404", display_name="程苏慧", department_id="581",
                 role_code="COST_ACCOUNTANT", session_id="112.b")


def event_id(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012x}"


def config_changed(n: int, pages: list[str], version: int) -> ConfigChangedEvent:
    """config 保存配置后发布的事件（C10 第 1 节）。"""
    return ConfigChangedEvent(event_id=event_id(n), topic="config.changed", audience=PagesAudience(pages=pages),
                              payload=ConfigChangedPayload(pages=pages, version=version))


def notification(n: int, users: list[str], title: str, link: str | None = "/approval/203") -> NotificationEvent:
    """delivery 发送通知后发布的事件（C10 第 1 节）。"""
    return NotificationEvent(event_id=event_id(n), topic="notification", audience=UsersAudience(users=users),
                             payload=NotificationPayload(delivery_id=event_id(1000 + n), title=title, body="", link=link))


def revoked_users(n: int, users: list[str], reason: str) -> SessionRevokedEvent:
    """identity 停用账号、撤销角色后发布的事件。"""
    return SessionRevokedEvent(event_id=event_id(n), topic="session.revoked", audience=UsersAudience(users=users),
                               payload=SessionRevokedPayload(reason=reason))  # type: ignore[arg-type]


def revoked_sessions(n: int, sessions: list[str]) -> SessionRevokedEvent:
    """identity 注销后发布的事件。"""
    return SessionRevokedEvent(event_id=event_id(n), topic="session.revoked",
                               audience=SessionsAudience(sessions=sessions),
                               payload=SessionRevokedPayload(reason="loggedOut"))


def app_for(realtime: Realtime) -> FastAPI:
    """像 assembly 那样挂载 `/ws`，在启动和关闭时开、停订阅任务。"""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await realtime.start()
        try:
            yield
        finally:
            await realtime.stop()

    app = FastAPI(lifespan=lifespan)
    app.include_router(realtime.router)
    return app


@dataclass
class Env:
    clock: FakeClock = field(default_factory=lambda: FakeClock(NOW))
    channel: EventChannel = field(default_factory=MemoryChannel)

    def __post_init__(self) -> None:
        self.auth = FakeAuthenticator(self.clock)

    def login(self, who: Identity, session_id: str | None = None) -> Identity:
        """登录并选定角色，返回这个会话的身份。"""
        identity = replace(who, session_id=session_id or who.session_id)
        self.auth.open_session(identity, csrf_token=f"csrf-{identity.session_id}")
        return identity

    def realtime(self) -> Realtime:
        """一个后端进程中的 realtime。"""
        return Realtime(self.auth, self.channel, frozenset({ORIGIN}))

    @contextmanager
    def process(self) -> Iterator[tuple[Realtime, TestClient]]:
        """启动一个后端进程（应用和订阅任务），结束时关闭。"""
        realtime = self.realtime()
        with TestClient(app_for(realtime)) as client:
            yield realtime, client


def connect(client: TestClient, session_id: str | None, origin: str | None = ORIGIN) -> WebSocketTestSession:
    """浏览器打开 `/ws`：带会话 Cookie 和 Origin。"""
    headers: dict[str, str] = {}
    if origin is not None:
        headers["origin"] = origin
    if session_id is not None:
        headers["cookie"] = f"cp_session={session_id}"
    return client.websocket_connect("/ws", headers=headers)


def recv(ws: WebSocketTestSession, timeout: float = 5.0) -> dict[str, Any]:
    """收下一条 ASGI 消息，最多等 `timeout` 秒。"""

    async def get() -> dict[str, Any]:
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()  # type: ignore[no-any-return]

    return ws.portal.call(get)


def recv_json(ws: WebSocketTestSession) -> Any:
    message = recv(ws)
    ws._raise_on_close(message)
    return json.loads(message["text"])


def recv_close(ws: WebSocketTestSession) -> int:
    """下一条消息是服务端关闭连接，返回关闭码。"""
    message = recv(ws)
    assert message["type"] == "websocket.close", message
    return int(message.get("code", 1000))


def subscribe(ws: WebSocketTestSession, *pages: str) -> None:
    """订阅页面，并用一次心跳确认服务端已经处理（服务端按顺序处理同一连接的消息）。"""
    ws.send_json({"type": "subscribe", "pages": list(pages)})
    ping(ws)


def ping(ws: WebSocketTestSession) -> None:
    ws.send_json({"type": "ping"})
    assert recv_json(ws) == {"type": "pong"}


def read_env(*names: str) -> dict[str, str]:
    """读取根目录 `.env` 中的这些变量（进程环境变量优先），只供 redis 测试连接用，不输出。"""
    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip() in names:
                    values[key.strip()] = value.strip().strip('"').strip("'")
    values.update({n: os.environ[n] for n in names if n in os.environ})
    return values
