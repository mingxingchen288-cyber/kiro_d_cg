"""HTTP 应用（AS-02、AS-04）：按插件清单启动注册表，挂载各模块注册的路由（含 realtime 的 /ws）和 `POST /api/commands`。

- `create_app(settings)` 读取设置，用 `oracle_plugins` 加 `app` 插件调用 `build_app(插件清单)`。运行时只有这一份清单；
  `backend/tests/assembly` 用 `build_app` 组装内存组合做模拟验证（AS-01）。
- 启动（lifespan）：在后台任务中按注册表 setup 的先后依次 await 各插件的 `start`，lifespan 不等它们完成，HTTP 服务立即应答。
  全部 start 完成前平台未就绪：`/health` 返回 503 `{"status": "starting"}`，其他 HTTP 请求返回 503 CONFIG_UNAVAILABLE，
  不进入路由，也不写 `X-Config-Version`（这时读不到配置代号）。某个 start 抛异常时记 ERROR 日志，平台保持未就绪
  （CF-13），`/health` 返回 503 `{"status": "failed"}`。`/ws` 不经过 HTTP 中间件。
- 关闭：先取消还没结束的启动任务，再按相反顺序调用 `stop`。只 stop 已经 start 成功的插件，以及没有 start、只有 stop 的
  插件（例如 db-core 释放连接池）。
- 就绪后每个响应带 `X-Config-Version`（当前配置代号）；`PlatformError` 按 C03 转成错误响应。

启动：`uv run --with <rules-core wheel> uvicorn cost_platform.assembly.app:create_app --factory --port 8080`。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
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
    return build_app([*oracle_plugins(settings or Settings.load()), AppPlugin()])


def build_app(plugins: Sequence[Plugin]) -> FastAPI:
    """按插件清单 boot 注册表，把 `app` 插件（清单中的 `AppPlugin`）取到的东西挂到 FastAPI 上。"""
    ordered = Registry().boot(plugins)
    _log.info("插件 setup 顺序：%s", " → ".join(p.name for p in ordered))
    wired = next(p for p in ordered if isinstance(p, AppPlugin))
    return _build(wired, _Startup(ordered))


class _Startup:
    """后台启动任务：按 setup 的先后依次 await 各插件的 start。

    `status`：starting（还在 start）、ok（全部 start 完成，就绪）、failed（某个 start 抛了异常）。
    `started` 记下 start 已成功的插件，关闭时只 stop 它们和没有 start 的插件。"""

    def __init__(self, ordered: Sequence[Plugin]) -> None:
        self._ordered = list(ordered)
        self.started: list[Plugin] = []
        self.status = "starting"

    @property
    def ready(self) -> bool:
        return self.status == "ok"

    async def run(self) -> None:
        for plugin in self._ordered:
            if not hasattr(plugin, "start"):
                continue
            try:
                await plugin.start()  # type: ignore[attr-defined]
            except Exception:
                _log.exception("插件 %s 启动失败，平台保持未就绪", plugin.name)
                self.status = "failed"
                return
            self.started.append(plugin)
        self.status = "ok"
        _log.info("全部插件已启动，开始接受请求")

    def stopping(self) -> list[Plugin]:
        """关闭时要 stop 的插件，按 setup 的相反顺序。"""
        return [p for p in reversed(self._ordered)
                if hasattr(p, "stop") and (p in self.started or not hasattr(p, "start"))]


def _lifespan(startup: _Startup) -> Any:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(startup.run())
        try:
            yield
        finally:
            task.cancel()  # 已经结束的任务不受影响
            with suppress(asyncio.CancelledError):
                await task
            for plugin in startup.stopping():
                await plugin.stop()  # type: ignore[attr-defined]

    return lifespan


def _error_response(exc: PlatformError) -> JSONResponse:
    """C03 第 1 节的错误响应体。"""
    return JSONResponse(dump_wire(ErrorResponse, exc.to_response()), status_code=exc.http_status)


def _build(wired: AppPlugin, startup: _Startup) -> FastAPI:
    app = FastAPI(title="cost-platform", openapi_url=None, lifespan=_lifespan(startup))

    @app.middleware("http")
    async def config_version(request: Request, call_next: Any) -> Response:
        if not startup.ready:
            if request.url.path == "/health":
                return JSONResponse({"status": startup.status}, status_code=503)
            return _error_response(PlatformError(ErrorCode.CONFIG_UNAVAILABLE, "平台还没有启动完成，读不到配置"))
        response: Response = await call_next(request)
        response.headers["X-Config-Version"] = str(await run_in_threadpool(wired.config.current_version))
        return response

    @app.exception_handler(PlatformError)
    async def platform_error(_request: Request, exc: PlatformError) -> JSONResponse:
        return _error_response(exc)

    @app.get("/health")
    def health() -> dict[str, Any]:
        """C09：`{"status": "ok", "coreVersion": "0.1.0", "configVersion": 13}`。"""
        return {"status": "ok", "coreVersion": wired.rules.core_version(), "configVersion": wired.config.current_version()}

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
