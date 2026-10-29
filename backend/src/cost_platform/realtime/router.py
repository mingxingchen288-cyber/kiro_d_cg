"""WebSocket 端点 `/ws`（C09 第 8 节、C10 第 2 节），FastAPI `APIRouter`，由 assembly 挂载。

握手（RT-01）：
- Origin 不在 `PLATFORM_ALLOWED_ORIGINS` 中：拒绝，403 ORIGIN_REJECTED；
- 会话取自 Cookie `cp_session`（C09 第 1 节），以 `touch=False` 调用 `Authenticator`：失败时按它抛出的错误拒绝
  （401 SESSION_REQUIRED、401 SESSION_ROLE_REVOKED、403 ROLE_SELECTION_REQUIRED）；
- 拒绝时用 WebSocket 的拒绝响应返回 C03 的错误体（ASGI 扩展 `websocket.http.response`，uvicorn 支持）。

连接建立后：
- 先登记连接（用户、会话），再接受握手：浏览器看到连接成功时，发给这个用户、会话的事件已经能推到；
- 浏览器发 `subscribe`、`unsubscribe` 改变订阅的页面；发 `ping` 时以 `touch=False` 检查会话，有效回 `pong`，
  失效（过期、注销、停用、撤销角色）时关闭连接（关闭码 4401）；
- 不符合 C10 的消息不处理（旧系统同样忽略不认识的消息）；
- 推送和 `pong` 都放进连接的发送队列，由这个连接的发送任务按顺序发出；读和发是两个任务，任一个结束时连接结束。

认证是同步的 Redis 调用，放进线程池执行，不阻塞事件循环。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Collection

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from cost_platform.contracts.ports import Authenticator
from cost_platform.contracts.types import (
    ErrorCode,
    ErrorResponse,
    PingMessage,
    PlatformError,
    SubscribeMessage,
    UnsubscribeMessage,
    dump_wire,
)

from .connections import Connection, ConnectionRegistry, End
from .messages import PONG, decode_client

SESSION_COOKIE = "cp_session"

logger = logging.getLogger("cost_platform.realtime")

SessionCheck = Callable[[str], Awaitable[None]]
"""心跳时检查会话（touch=False）；会话失效时抛 PlatformError。"""


def realtime_router(authenticator: Authenticator, registry: ConnectionRegistry,
                    allowed_origins: Collection[str]) -> APIRouter:
    """`allowed_origins` 取 `.env` 的 `PLATFORM_ALLOWED_ORIGINS`（assembly 的 `Settings.allowed_origins`）。"""
    router = APIRouter()

    async def check_session(session_id: str) -> None:
        await run_in_threadpool(authenticator.authenticate, session_id, None, False, touch=False)

    @router.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        if websocket.headers.get("origin") not in allowed_origins:
            await _deny(websocket, PlatformError(ErrorCode.ORIGIN_REJECTED, "请求来源不被允许"))
            return
        try:
            identity = await run_in_threadpool(authenticator.authenticate, websocket.cookies.get(SESSION_COOKIE),
                                               None, False, touch=False)
        except PlatformError as exc:
            await _deny(websocket, exc)
            return
        conn = registry.add(identity)
        try:
            await websocket.accept()
            await _serve(websocket, conn, registry, check_session)
        finally:
            registry.remove(conn)

    return router


async def _deny(websocket: WebSocket, error: PlatformError) -> None:
    body = dump_wire(ErrorResponse, error.to_response())
    await websocket.send_denial_response(JSONResponse(body, status_code=error.http_status))


async def _serve(websocket: WebSocket, conn: Connection, registry: ConnectionRegistry,
                 check_session: SessionCheck) -> None:
    """读、发两个任务放在一个 anyio 任务组里：任一个结束时取消另一个，两个都结束后返回。

    读写中意外的错误由任务组包成异常组抛出，由 Starlette 记录并关闭连接。

    外面取消这个连接时（例如 Starlette 的 TestClient 关闭 WebSocket 时用 anyio 的取消范围取消应用），任务组把这次
    取消原样传出去，发起取消的取消范围认得出，取消到它为止。不用 `asyncio.gather` 等两个任务：gather 本身被取消时，
    抛出的是子任务被取消时产生的 CancelledError，外面的取消范围认不出，取消会漏出范围
    （测试中表现为 TestClient 退出 WebSocket 时偶发 concurrent.futures.CancelledError）。
    """
    async with anyio.create_task_group() as tasks:

        async def read() -> None:
            await _read(websocket, conn, registry, check_session)
            tasks.cancel_scope.cancel()

        async def write() -> None:
            await _write(websocket, conn)
            tasks.cancel_scope.cancel()

        tasks.start_soon(read)
        tasks.start_soon(write)


async def _read(websocket: WebSocket, conn: Connection, registry: ConnectionRegistry,
                check_session: SessionCheck) -> None:
    """处理浏览器发来的消息，直到浏览器断开。会话失效时只安排关闭，由发送任务关闭连接。"""
    try:
        while True:
            text = await websocket.receive_text()
            try:
                message = decode_client(text)
            except (ValidationError, ValueError):
                logger.debug("忽略不符合 C10 的消息：%.200s", text)
                continue
            if isinstance(message, SubscribeMessage):
                registry.subscribe(conn, message.pages)
            elif isinstance(message, UnsubscribeMessage):
                registry.unsubscribe(conn, message.pages)
            elif isinstance(message, PingMessage):
                try:
                    await check_session(conn.session_id)
                except PlatformError:
                    registry.remove(conn)
                    conn.end()
                else:
                    conn.send(PONG)
    except WebSocketDisconnect:
        return


async def _write(websocket: WebSocket, conn: Connection) -> None:
    """按顺序发出发送队列中的消息；遇到关闭指令时关闭连接。"""
    try:
        while True:
            item = await conn.next_outgoing()
            if isinstance(item, End):
                await websocket.close(code=item.code, reason=item.reason)
                return
            await websocket.send_text(item)
    except WebSocketDisconnect:
        return
