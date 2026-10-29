"""C09 第 4 节的接口，写成 FastAPI 的 APIRouter，由 assembly 挂载（`app.include_router(build_router(...))`）。

会话、CSRF 和执行上下文由 assembly 提供的 `context(request, is_write)` 生成（C09 第 1 节：POST、PUT 带 CSRF）；
请求体按契约类型解析（只认 camelCase），不符合时为 400 INVALID_REQUEST（C03）。业务错误抛 PlatformError，
由 assembly 的异常处理转成 C03 的错误响应。数据库访问是同步的，放在线程池中执行。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from cost_platform.contracts.types import (
    ByKeysRequest,
    DictResponse,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    ExportList,
    ExportRequest,
    ListRequest,
    ListResponse,
    LookupSearchRequest,
    LookupSearchResponse,
    PersonalConfig,
    PlatformError,
    RecordResponse,
    RowsResponse,
    dump_wire,
    parse_wire,
)

from .exports import XLSX, Exports
from .lists import PageQueries
from .lookups import DictQueries, LookupQueries
from .personal import PersonalConfigs

ContextProvider = Callable[[Request, bool], ExecutionContext]
"""assembly 的请求处理：校验会话（写请求还校验来源和 CSRF），取配置快照，生成执行上下文。"""


@dataclass(frozen=True)
class QueryServices:
    lists: PageQueries
    lookups: LookupQueries
    dicts: DictQueries
    personal: PersonalConfigs
    exports: Exports


def parse_body(tp: Any, payload: Any) -> Any:
    try:
        return parse_wire(tp, payload)
    except ValidationError as exc:
        details = [ErrorDetail(message=e["msg"], path=".".join(str(p) for p in e["loc"])) for e in exc.errors()]
        raise PlatformError(ErrorCode.INVALID_REQUEST, "请求内容不符合接口约定", details) from None


async def _payload(request: Request) -> Any:
    raw = await request.body()
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        raise PlatformError(ErrorCode.INVALID_REQUEST, "请求体不是 JSON") from None


def build_router(services: QueryServices, context: ContextProvider) -> APIRouter:
    router = APIRouter()

    def reply(tp: Any, value: Any) -> JSONResponse:
        return JSONResponse(dump_wire(tp, value))

    @router.post("/api/pages/{page_code}/rows")
    async def rows(page_code: str, request: Request) -> JSONResponse:
        payload = await _payload(request)

        def run() -> JSONResponse:
            ctx = context(request, True)
            return reply(ListResponse, services.lists.list(ctx, page_code, parse_body(ListRequest, payload)))
        return await run_in_threadpool(run)

    @router.post("/api/pages/{page_code}/rows/by-keys")
    async def rows_by_keys(page_code: str, request: Request) -> JSONResponse:
        payload = await _payload(request)

        def run() -> JSONResponse:
            ctx = context(request, True)
            return reply(RowsResponse, services.lists.by_keys(ctx, page_code, parse_body(ByKeysRequest, payload)))
        return await run_in_threadpool(run)

    @router.get("/api/pages/{page_code}/records/{record_key}")
    async def record(page_code: str, record_key: str, request: Request) -> JSONResponse:
        def run() -> JSONResponse:
            ctx = context(request, False)
            return reply(RecordResponse, services.lists.record(ctx, page_code, record_key))
        return await run_in_threadpool(run)

    @router.post("/api/lookups/{lookup_code}/search")
    async def lookup(lookup_code: str, request: Request) -> JSONResponse:
        payload = await _payload(request)

        def run() -> JSONResponse:
            ctx = context(request, True)
            result = services.lookups.search(ctx, lookup_code, parse_body(LookupSearchRequest, payload))
            return reply(LookupSearchResponse, result)
        return await run_in_threadpool(run)

    @router.get("/api/dicts/{dict_type}")
    async def dicts(dict_type: str, request: Request) -> JSONResponse:
        def run() -> JSONResponse:
            ctx = context(request, False)
            return reply(DictResponse, services.dicts.items(ctx, dict_type))
        return await run_in_threadpool(run)

    @router.get("/api/pages/{page_code}/personal")
    async def personal(page_code: str, request: Request) -> JSONResponse:
        def run() -> JSONResponse:
            ctx = context(request, False)
            return reply(PersonalConfig, services.personal.get(ctx, page_code))
        return await run_in_threadpool(run)

    @router.put("/api/pages/{page_code}/personal")
    async def save_personal(page_code: str, request: Request) -> JSONResponse:
        payload = await _payload(request)

        def run() -> JSONResponse:
            ctx = context(request, True)
            return reply(PersonalConfig, services.personal.save(ctx, page_code, parse_body(PersonalConfig, payload)))
        return await run_in_threadpool(run)

    @router.get("/api/pages/{page_code}/exports")
    async def exports(page_code: str, request: Request) -> JSONResponse:
        def run() -> JSONResponse:
            ctx = context(request, False)
            return reply(ExportList, services.exports.available(ctx, page_code))
        return await run_in_threadpool(run)

    @router.post("/api/pages/{page_code}/export")
    async def export(page_code: str, request: Request) -> Response:
        payload = await _payload(request)

        def run() -> Response:
            ctx = context(request, True)
            file = services.exports.export(ctx, page_code, parse_body(ExportRequest, payload))
            return Response(content=file.content, media_type=XLSX, headers={"Content-Disposition": file.content_disposition})
        return await run_in_threadpool(run)

    return router
