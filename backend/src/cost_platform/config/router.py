"""C09 第 3 节的 HTTP 接口，由 assembly 挂载（`app.include_router(create_router(...))`）。

执行上下文由 assembly 的中间件生成（C04）：`context(request, is_write)` 校验会话、CSRF 和来源，读取配置快照。
`/api/config/*` 只对管理员角色开放，其他角色返回 403 PERMISSION_DENIED（C09 第 1 节）。错误抛 `PlatformError`，
由 assembly 按 C03 转成响应。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import ValidationError

from cost_platform.contracts.types import (
    ConfigDraft,
    ConfigItem,
    ConfigItemList,
    ConfigSaveRequest,
    ConfigSaveResponse,
    ConfigValidateRequest,
    ConfigValidateResponse,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    PageView,
    PlatformError,
    SchemaColumnsRequest,
    SchemaColumnsResponse,
    WizardColumnsRequest,
    WizardColumnsResponse,
    WizardGenerateRequest,
    dump_wire,
    parse_wire,
)

from .records import BASE_TYPES
from .service import ConfigService

ContextFactory = Callable[[Request, bool], ExecutionContext]


async def _body(request: Request, tp: Any) -> Any:
    try:
        return parse_wire(tp, json.loads(await request.body()))
    except (ValueError, ValidationError) as exc:
        details = ([ErrorDetail(message=e["msg"], path=".".join(str(p) for p in e["loc"])) for e in exc.errors()]
                   if isinstance(exc, ValidationError) else [])
        raise PlatformError(ErrorCode.INVALID_REQUEST, "请求内容不符合接口约定", details) from None


def _admin(ctx: ExecutionContext) -> None:
    if not ctx.config.role().admin:
        raise PlatformError(ErrorCode.PERMISSION_DENIED, "只有管理员角色可以使用配置功能")


def _config_type(config_type: str) -> str:
    if config_type not in BASE_TYPES:
        raise PlatformError(ErrorCode.NOT_FOUND, f"配置类型 {config_type} 不存在")
    return config_type


def create_router(service: ConfigService, context: ContextFactory) -> APIRouter:
    router = APIRouter()

    @router.get("/api/pages/{page_code}/view")
    def page_view(page_code: str, request: Request) -> Any:
        ctx = context(request, False)
        return dump_wire(PageView, ctx.config.page_view(page_code))

    @router.get("/api/rules-packs/{pack_id}/{version}")
    def rules_pack(pack_id: str, version: int, request: Request) -> Any:
        context(request, False)
        return service.get_pack(pack_id, version)

    @router.get("/api/config/items")
    def list_items(request: Request, type: str | None = None) -> Any:  # noqa: A002 - 查询参数名为 type（C09）
        _admin(context(request, False))
        return dump_wire(ConfigItemList, ConfigItemList(items=service.list_items(_config_type(type) if type else None)))

    @router.get("/api/config/items/{config_type}/{key}")
    def get_item(config_type: str, key: str, request: Request) -> Any:
        _admin(context(request, False))
        return dump_wire(ConfigItem, service.get_item(_config_type(config_type), key))

    @router.put("/api/config/items/{config_type}/{key}")
    async def save_item(config_type: str, key: str, request: Request) -> Any:
        ctx = context(request, True)
        _admin(ctx)
        body: ConfigSaveRequest = await _body(request, ConfigSaveRequest)
        draft = ConfigDraft(type=_config_type(config_type), key=key, name=body.name, content=body.content)
        result = service.save([draft], ctx.identity.user_id)
        return dump_wire(ConfigSaveResponse, ConfigSaveResponse(type=draft.type, key=key,
                                                                version=result.versions[(draft.type, key)]))

    @router.delete("/api/config/items/{config_type}/{key}")
    def delete_item(config_type: str, key: str, request: Request) -> Response:
        ctx = context(request, True)
        _admin(ctx)
        service.delete(_config_type(config_type), key, ctx.identity.user_id)
        return Response(status_code=204)

    @router.post("/api/config/validate")
    async def validate(request: Request) -> Any:
        _admin(context(request, True))
        body: ConfigValidateRequest = await _body(request, ConfigValidateRequest)
        errors = service.validate(body.items)
        return dump_wire(ConfigValidateResponse, ConfigValidateResponse(ok=not errors, errors=errors))

    @router.post("/api/config/wizard/columns")
    async def wizard_columns(request: Request) -> Any:
        _admin(context(request, True))
        body: WizardColumnsRequest = await _body(request, WizardColumnsRequest)
        return dump_wire(WizardColumnsResponse, service.wizard_columns(body))

    @router.post("/api/config/schema/columns")
    async def schema_columns(request: Request) -> Any:
        _admin(context(request, True))
        body: SchemaColumnsRequest = await _body(request, SchemaColumnsRequest)
        return dump_wire(SchemaColumnsResponse, service.schema_columns(body.name))

    @router.post("/api/config/wizard/generate")
    async def wizard_generate(request: Request) -> Any:
        ctx = context(request, True)
        _admin(ctx)
        body: WizardGenerateRequest = await _body(request, WizardGenerateRequest)
        result = service.wizard_generate(body, ctx.identity.user_id)
        # C09 没有写这个接口的响应体（见 contract-gaps）：列出写入的配置项和新版本号
        return {"items": [dump_wire(ConfigSaveResponse, ConfigSaveResponse(type=t, key=k, version=v))
                          for (t, k), v in result.versions.items()]}

    return router
