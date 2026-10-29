"""C09 第 6 节的接口，写成 FastAPI 的 APIRouter，由 assembly 挂载（`app.include_router(approval_router(...))`）。

会话、CSRF 和执行上下文由 assembly 提供的 `context(request, is_write)` 生成（C09 第 1 节：POST 带 CSRF）；请求体按契约类型
解析（只认 camelCase），不符合时为 400 INVALID_REQUEST（C03）。业务错误抛 PlatformError，由 assembly 的异常处理转成 C03
的错误响应。数据库访问是同步的，放在线程池中执行。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from cost_platform.contracts.types import (
    ApprovalDetail,
    ApprovalList,
    CommandResult,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    PassRequest,
    PlatformError,
    PreviewRequest,
    PreviewResponse,
    RejectRequest,
    WithdrawRequest,
    dump_wire,
    parse_wire,
)

from .service import ApprovalService

ContextProvider = Callable[[Request, bool], ExecutionContext]
"""assembly 的请求处理：校验会话（写请求还校验来源和 CSRF），取配置快照，生成执行上下文。"""


def _parse(tp: Any, payload: Any) -> Any:
    try:
        return parse_wire(tp, payload)
    except ValidationError as exc:
        details = [ErrorDetail(message=e["msg"], path=".".join(str(p) for p in e["loc"])) for e in exc.errors()]
        raise PlatformError(ErrorCode.INVALID_REQUEST, "请求内容不符合接口约定", details) from None


async def _payload(request: Request) -> Any:
    raw = await request.body()
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        raise PlatformError(ErrorCode.INVALID_REQUEST, "请求体不是 JSON") from None


def approval_router(service: ApprovalService, context: ContextProvider) -> APIRouter:
    router = APIRouter()

    def reply(tp: Any, value: Any) -> JSONResponse:
        return JSONResponse(dump_wire(tp, value))

    @router.get("/api/approvals")
    async def approvals(request: Request, box: str = "todo", start_row: int = Query(0, alias="startRow"),
                        end_row: int = Query(50, alias="endRow")) -> JSONResponse:
        def run() -> JSONResponse:
            ctx = context(request, False)
            return reply(ApprovalList, service.list(ctx, box, start_row, end_row))
        return await run_in_threadpool(run)

    @router.get("/api/approvals/{approval_id}")
    async def detail(approval_id: str, request: Request) -> JSONResponse:
        def run() -> JSONResponse:
            ctx = context(request, False)
            return reply(ApprovalDetail, service.detail(ctx, approval_id))
        return await run_in_threadpool(run)

    @router.post("/api/approvals/{approval_id}/preview")
    async def preview(approval_id: str, request: Request) -> JSONResponse:
        payload = await _payload(request)

        def run() -> JSONResponse:
            ctx = context(request, True)
            return reply(PreviewResponse, service.preview(ctx, approval_id, _parse(PreviewRequest, payload)))
        return await run_in_threadpool(run)

    @router.post("/api/approvals/{approval_id}/pass")
    async def pass_(approval_id: str, request: Request) -> JSONResponse:
        payload = await _payload(request)

        def run() -> JSONResponse:
            ctx = context(request, True)
            return reply(CommandResult, service.pass_(ctx, approval_id, _parse(PassRequest, payload)))
        return await run_in_threadpool(run)

    @router.post("/api/approvals/{approval_id}/reject")
    async def reject(approval_id: str, request: Request) -> JSONResponse:
        payload = await _payload(request)

        def run() -> JSONResponse:
            ctx = context(request, True)
            return reply(CommandResult, service.reject(ctx, approval_id, _parse(RejectRequest, payload)))
        return await run_in_threadpool(run)

    @router.post("/api/approvals/{approval_id}/withdraw")
    async def withdraw(approval_id: str, request: Request) -> JSONResponse:
        payload = await _payload(request)

        def run() -> JSONResponse:
            ctx = context(request, True)
            return reply(CommandResult, service.withdraw(ctx, approval_id, _parse(WithdrawRequest, payload)))
        return await run_in_threadpool(run)

    return router
