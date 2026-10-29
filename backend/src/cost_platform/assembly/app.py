"""HTTP 应用（AS-02）：按插件清单启动注册表，挂载各模块注册的路由（含 realtime 的 /ws）和 `POST /api/commands`。

- 启动（lifespan）：按注册表 setup 的先后调用各插件的 `start`，关闭时按相反顺序调用 `stop`。
- 每个响应带 `X-Config-Version`（当前配置代号）；`PlatformError` 按 C03 转成错误响应。

启动：`uv run --with <rules-core wheel> uvicorn cost_platform.assembly.app:create_app --factory --port 8080`。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from cost_platform.contracts.registry import Plugin, Registry
from cost_platform.contracts.types import (
    Command,
    CommandResult,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    PlatformError,
    dump_wire,
    parse_wire,
)

from .plugins import AppPlugin, oracle_plugins
from .settings import Settings

_log = logging.getLogger("cost_platform.assembly")


def _show_platform_logs() -> None:
    """uvicorn 只配置它自己的日志；平台的 INFO 日志（含启动时的"端口 → 插件 → 实现类"）另输出到控制台。"""
    logger = logging.getLogger("cost_platform")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def create_app(settings: Settings | None = None) -> FastAPI:
    _show_platform_logs()
    app_plugin = AppPlugin()
    ordered = Registry().boot([*oracle_plugins(settings or Settings.load()), app_plugin])
    _log.info("插件 setup 顺序：%s", " → ".join(p.name for p in ordered))
    return _build(app_plugin, ordered)


def _lifespan(ordered: Sequence[Plugin]) -> Any:
    starting = [p for p in ordered if hasattr(p, "start")]
    stopping = [p for p in reversed(ordered) if hasattr(p, "stop")]

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        for plugin in starting:
            await plugin.start()  # type: ignore[attr-defined]
        try:
            yield
        finally:
            for plugin in stopping:
                await plugin.stop()  # type: ignore[attr-defined]

    return lifespan


def _build(wired: AppPlugin, ordered: Sequence[Plugin]) -> FastAPI:
    app = FastAPI(title="cost-platform", openapi_url=None, lifespan=_lifespan(ordered))

    @app.middleware("http")
    async def config_version(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Config-Version"] = str(await run_in_threadpool(wired.config.current_version))
        return response

    @app.exception_handler(PlatformError)
    async def platform_error(_request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(dump_wire(ErrorResponse, exc.to_response()), status_code=exc.http_status)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "configVersion": wired.config.current_version()}

    @app.post("/api/commands")
    async def commands(request: Request) -> Any:
        raw = await request.body()

        def run() -> Any:
            ctx = wired.contexts.context(request, True)
            try:
                command: Command = parse_wire(Command, json.loads(raw))
            except (ValueError, ValidationError) as exc:
                details = [ErrorDetail(message=e["msg"], path=".".join(str(p) for p in e["loc"]))
                           for e in exc.errors()] if isinstance(exc, ValidationError) else []
                raise PlatformError(ErrorCode.VALIDATION_FAILED, "请求内容不符合接口约定", details) from None
            return dump_wire(CommandResult, wired.executor.execute(command, ctx))
        return await run_in_threadpool(run)

    for router in wired.routers:
        app.include_router(router)
    return app
