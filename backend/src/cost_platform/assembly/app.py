"""HTTP 应用（C09 中链路 0、链路 1 用到的接口）和请求处理（AS-02）。

启动：`uv run uvicorn cost_platform.assembly.app:create_app --factory --port 8080`。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from cost_platform.contracts.types import (
    Command,
    CommandResult,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    ExecutionContext,
    ListRequest,
    ListResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    Origin,
    PageView,
    PlatformError,
    RecordResponse,
    RoleRef,
    dump_wire,
    parse_wire,
)

from .settings import Settings
from .wiring import Container, build

SESSION_COOKIE = "cp_session"


def create_app(settings: Settings | None = None) -> FastAPI:
    c: Container = build(settings or Settings.load())
    c.accounts.ensure_admin()  # ID-06
    app = FastAPI(title="cost-platform", openapi_url=None)

    @app.middleware("http")
    async def config_version(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Config-Version"] = str(c.config.version)
        return response

    @app.exception_handler(PlatformError)
    async def platform_error(_request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(dump_wire(ErrorResponse, exc.to_response()), status_code=exc.http_status)

    async def body(request: Request, tp: Any) -> Any:
        try:
            return parse_wire(tp, json.loads(await request.body()))
        except (ValueError, ValidationError) as exc:
            details = [ErrorDetail(message=e["msg"], path=".".join(str(p) for p in e["loc"]))
                       for e in exc.errors()] if isinstance(exc, ValidationError) else []
            raise PlatformError(ErrorCode.VALIDATION_FAILED, "请求内容不符合接口约定", details) from None

    def check_origin(request: Request) -> None:
        if request.headers.get("origin") not in c.settings.allowed_origins:
            raise PlatformError(ErrorCode.ORIGIN_REJECTED, "请求来源不被允许")

    def context(request: Request, is_write: bool) -> ExecutionContext:
        if is_write:
            check_origin(request)
        identity = c.identity.authenticate(request.cookies.get(SESSION_COOKIE), request.headers.get("x-csrf-token"),
                                           is_write, touch=request.headers.get("x-background-request") != "1")
        snapshot = c.config.read(identity.role_code)
        return ExecutionContext(request_id=c.ids.uuid(), identity=identity, config=snapshot,
                                config_version=snapshot.version, origin=Origin("user", None), now=c.clock.now())

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "configVersion": c.config.version}

    @app.post("/api/auth/login")
    async def login(request: Request) -> JSONResponse:
        check_origin(request)
        req: LoginRequest = await body(request, LoginRequest)
        session_id, result = c.identity.login(req.username, req.password.get_secret_value())
        response = JSONResponse(dump_wire(LoginResponse, result))
        response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="lax", path="/")
        return response

    @app.get("/api/me")
    def me(request: Request) -> Any:
        ctx = context(request, is_write=False)
        user, role_code, csrf = c.identity.session(request.cookies.get(SESSION_COOKIE))
        role = ctx.config.role()
        return dump_wire(MeResponse, MeResponse(
            user=user, role=RoleRef(code=role_code or "", name=role.name, admin=role.admin),
            menus=ctx.config.menus(), config_version=ctx.config_version, csrf_token=csrf))

    @app.get("/api/pages/{page_code}/view")
    def page_view(page_code: str, request: Request) -> Any:
        ctx = context(request, is_write=False)
        return dump_wire(PageView, ctx.config.page_view(page_code))

    @app.post("/api/pages/{page_code}/rows")
    async def rows(page_code: str, request: Request) -> Any:
        # C09 第 1 节按方法区分：POST 都要带 X-CSRF-Token
        ctx = context(request, is_write=True)
        req: ListRequest = await body(request, ListRequest)
        return dump_wire(ListResponse, c.queries.list(ctx, page_code, req))

    @app.get("/api/pages/{page_code}/records/{record_key}")
    def record(page_code: str, record_key: str, request: Request) -> Any:
        ctx = context(request, is_write=False)
        return dump_wire(RecordResponse, c.queries.record(ctx, page_code, record_key))

    @app.post("/api/commands")
    async def commands(request: Request) -> Any:
        ctx = context(request, is_write=True)
        command: Command = await body(request, Command)
        return dump_wire(CommandResult, c.executor.execute(command, ctx))

    return app
