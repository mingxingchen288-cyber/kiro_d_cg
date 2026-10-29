"""C09 第 7 节的接口，写成 FastAPI 的 APIRouter，由 assembly 挂载（`app.include_router(delivery_router(...))`）。

- 会话、CSRF 和执行上下文由 assembly 提供的 `context(request, is_write)` 生成（C09 第 1 节：POST 带 CSRF；
  带 `X-Background-Request: 1` 的请求不顺延会话，也由 assembly 处理）。
- `/api/admin/*` 只对管理员角色开放：按配置快照的角色 `admin` 判断，其他角色 403 PERMISSION_DENIED。
- 业务错误抛 PlatformError，由 assembly 的异常处理按 C03 转成响应。数据库访问是同步的，放在线程池中执行。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from cost_platform.contracts.types import (
    DeliveryList,
    ErrorCode,
    ExecutionContext,
    InboxList,
    PlatformError,
    dump_wire,
)

from .service import DeliveryService

ContextProvider = Callable[[Request, bool], ExecutionContext]
"""assembly 的请求处理：校验会话（写请求还校验来源和 CSRF），取配置快照，生成执行上下文。"""


def _reply(tp: Any, value: Any) -> JSONResponse:
    return JSONResponse(dump_wire(tp, value))


def delivery_router(deliveries: DeliveryService, context: ContextProvider) -> APIRouter:
    router = APIRouter()

    def admin(request: Request, is_write: bool) -> ExecutionContext:
        ctx = context(request, is_write)
        if not ctx.config.role().admin:
            raise PlatformError(ErrorCode.PERMISSION_DENIED, "只有管理员可以管理投递记录")
        return ctx

    @router.get("/api/inbox")
    async def inbox(request: Request, unread: bool = False, start_row: int = Query(0, alias="startRow"),
                    end_row: int = Query(20, alias="endRow")) -> JSONResponse:
        """当前用户的站内通知，新的在前；`unread=true` 时只列未读。`unread` 为当前用户的未读数（铃铛角标）。"""
        def run() -> JSONResponse:
            ctx = context(request, False)
            return _reply(InboxList, deliveries.inbox(ctx.identity.user_id, unread, start_row, end_row))
        return await run_in_threadpool(run)

    @router.post("/api/inbox/{delivery_id}/read", status_code=204)
    async def read(delivery_id: str, request: Request) -> Response:
        def run() -> None:
            ctx = context(request, True)
            deliveries.mark_read(ctx.identity.user_id, delivery_id, ctx.now)
        await run_in_threadpool(run)
        return Response(status_code=204)

    @router.get("/api/admin/deliveries")
    async def list_deliveries(request: Request, status: str | None = None, start_row: int = Query(0, alias="startRow"),
                              end_row: int = Query(50, alias="endRow")) -> JSONResponse:
        """投递记录，新登记的在前；不给 `status` 时列出全部状态。"""
        def run() -> JSONResponse:
            admin(request, False)
            return _reply(DeliveryList, deliveries.list_deliveries(status, start_row, end_row))
        return await run_in_threadpool(run)

    @router.post("/api/admin/deliveries/{delivery_id}/requeue", status_code=204)
    async def requeue(delivery_id: str, request: Request) -> Response:
        """把 abandoned 的记录重新排队；不是 abandoned 时 422 VALIDATION_FAILED，记录不存在时 404 NOT_FOUND。"""
        def run() -> None:
            ctx = admin(request, True)
            deliveries.requeue(delivery_id, ctx.now)
        await run_in_threadpool(run)
        return Response(status_code=204)

    return router
