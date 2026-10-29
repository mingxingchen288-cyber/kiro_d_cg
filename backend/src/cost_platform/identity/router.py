"""C09 第 2 节的 HTTP 接口（FastAPI `APIRouter`），由 assembly 挂载。

- 失败时抛 `PlatformError`，由 assembly 的异常处理按 C03 转成响应；请求体不符合 C09 时为 422 VALIDATION_FAILED。
- 会话取自 Cookie `cp_session`；写请求的 CSRF 令牌取自 `X-CSRF-Token`；带 `X-Background-Request: 1` 的请求不顺延会话（ID-10）。
- 请求来源：写请求（GET、HEAD、OPTIONS 以外的方法，含登录）的 Origin 不在 `allowed_origins` 中时 403 ORIGIN_REJECTED
  （assembly AS-02），作为本路由的依赖检查，在读请求体和会话之前。
- `/api/admin/*` 只对管理员角色开放（C09 第 1 节）：按配置快照的角色 `admin` 判断，其他角色 403 PERMISSION_DENIED。
- 账号、会话的读写是同步的数据库和 Redis 调用，放进线程池执行，不阻塞事件循环。

C09 之外的接口（旧系统有、C09 没有，见 `.reports/modules/identity/contract-gaps.md`），在下面标了"C09 之外"。
"""

from __future__ import annotations

import json
from collections.abc import Collection
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from cost_platform.contracts.ports import ConfigSnapshotReader
from cost_platform.contracts.types import (
    Account,
    AccountCreate,
    AccountList,
    AccountUpdate,
    Department,
    DepartmentList,
    ErrorCode,
    ErrorDetail,
    Key,
    LoginRequest,
    LoginResponse,
    MeResponse,
    PasswordChange,
    PlatformError,
    RoleRef,
    SelectRoleRequest,
    SelectRoleResponse,
    Wire,
    dump_wire,
    parse_wire,
)

from .admin import AccountAdmin
from .service import IdentityService

SESSION_COOKIE = "cp_session"
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class DepartmentDraft(Wire):
    """新建、修改部门的请求体（C09 之外）。"""

    name: str
    parent_id: Key | None


async def _body(request: Request, tp: Any) -> Any:
    try:
        return parse_wire(tp, json.loads(await request.body()))
    except ValidationError as exc:
        details = [ErrorDetail(message=e["msg"], path=".".join(str(p) for p in e["loc"])) for e in exc.errors()]
        raise PlatformError(ErrorCode.VALIDATION_FAILED, "请求内容不符合接口约定", details) from None
    except ValueError:
        raise PlatformError(ErrorCode.VALIDATION_FAILED, "请求内容不符合接口约定") from None


def _session_id(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def _csrf(request: Request) -> str | None:
    return request.headers.get("x-csrf-token")


def _touch(request: Request) -> bool:
    return request.headers.get("x-background-request") != "1"


def _json(tp: Any, value: Any) -> JSONResponse:
    return JSONResponse(dump_wire(tp, value))


def identity_router(identity: IdentityService, admin: AccountAdmin, config: ConfigSnapshotReader,
                    allowed_origins: Collection[str]) -> APIRouter:
    """`allowed_origins` 取 `.env` 的 `PLATFORM_ALLOWED_ORIGINS`。还没有选定角色时 `/api/me` 的 `configVersion`
    取 `config.current_version()`（这时没有角色，读不了配置快照）。"""

    def check_origin(request: Request) -> None:
        if request.method not in _READ_METHODS and request.headers.get("origin") not in allowed_origins:
            raise PlatformError(ErrorCode.ORIGIN_REJECTED, "请求来源不被允许")

    router = APIRouter(dependencies=[Depends(check_origin)])

    def check_admin(request: Request, is_write: bool) -> None:
        who = identity.authenticate(_session_id(request), _csrf(request), is_write, _touch(request))
        if not config.read(who.role_code).role().admin:
            raise PlatformError(ErrorCode.PERMISSION_DENIED, "只有管理员可以管理账号")

    async def as_admin(request: Request, is_write: bool) -> None:
        await run_in_threadpool(check_admin, request, is_write)

    # ------------------------------------------------------------ 登录、选角色、注销、当前用户

    @router.post("/api/auth/login")
    async def login(request: Request) -> JSONResponse:
        req: LoginRequest = await _body(request, LoginRequest)
        session_id, result = await run_in_threadpool(identity.login, req.username, req.password.get_secret_value())
        response = _json(LoginResponse, result)
        response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="lax", path="/")
        return response

    @router.post("/api/auth/role")
    async def select_role(request: Request) -> JSONResponse:
        req: SelectRoleRequest = await _body(request, SelectRoleRequest)
        result = await run_in_threadpool(identity.select_role, _session_id(request), _csrf(request), req.role_code)
        return _json(SelectRoleResponse, result)

    @router.post("/api/auth/logout", status_code=204)
    async def logout(request: Request) -> Response:
        await run_in_threadpool(identity.logout, _session_id(request), _csrf(request))
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
        return response

    @router.post("/api/auth/password", status_code=204)
    async def change_own_password(request: Request) -> Response:
        """C09 之外：当前用户改自己的密码（旧系统 `/auth/changePassword`）。"""
        req: PasswordChange = await _body(request, PasswordChange)
        await run_in_threadpool(identity.change_own_password, _session_id(request), _csrf(request),
                                req.password.get_secret_value())
        return Response(status_code=204)

    @router.get("/api/me")
    async def me(request: Request) -> JSONResponse:
        def build() -> MeResponse:
            user, role_code, csrf = identity.session(_session_id(request), touch=_touch(request))
            if role_code is None:
                return MeResponse(user=user, role=None, menus=[], config_version=config.current_version(),
                                  csrf_token=csrf)
            snapshot = config.read(role_code)  # ID-09：菜单取自配置快照，已去掉该角色不能访问的页面
            role = snapshot.role()
            return MeResponse(user=user, role=RoleRef(code=role_code, name=role.name, admin=role.admin),
                              menus=snapshot.menus(), config_version=snapshot.version, csrf_token=csrf)

        return _json(MeResponse, await run_in_threadpool(build))

    # ------------------------------------------------------------ 账号管理（只对管理员）

    @router.get("/api/admin/accounts")
    async def list_accounts(request: Request, keyword: str = "", start_row: int = Query(0, alias="startRow"),
                            end_row: int = Query(50, alias="endRow"),
                            role_code: str | None = Query(None, alias="roleCode")) -> JSONResponse:
        """`roleCode` 为 C09 之外的参数：只列分配了该角色的账号。"""
        await as_admin(request, is_write=False)
        result = await run_in_threadpool(admin.list_accounts, keyword, start_row, end_row, role_code)
        return _json(AccountList, result)

    @router.post("/api/admin/accounts")
    async def create_account(request: Request) -> JSONResponse:
        await as_admin(request, is_write=True)
        req: AccountCreate = await _body(request, AccountCreate)
        return _json(Account, await run_in_threadpool(admin.create_account, req))

    @router.put("/api/admin/accounts/{user_id}")
    async def update_account(user_id: str, request: Request) -> JSONResponse:
        await as_admin(request, is_write=True)
        req: AccountUpdate = await _body(request, AccountUpdate)
        return _json(Account, await run_in_threadpool(admin.update_account, user_id, req))

    @router.post("/api/admin/accounts/{user_id}/password", status_code=204)
    async def set_password(user_id: str, request: Request) -> Response:
        await as_admin(request, is_write=True)
        req: PasswordChange = await _body(request, PasswordChange)
        await run_in_threadpool(admin.set_password, user_id, req.password.get_secret_value())
        return Response(status_code=204)

    # ------------------------------------------------------------ 部门（只对管理员）

    @router.get("/api/admin/departments")
    async def departments(request: Request) -> JSONResponse:
        await as_admin(request, is_write=False)
        return _json(DepartmentList, await run_in_threadpool(admin.departments))

    @router.post("/api/admin/departments")
    async def create_department(request: Request) -> JSONResponse:
        """C09 之外：新建部门（旧系统部门管理页的新增）。"""
        await as_admin(request, is_write=True)
        req: DepartmentDraft = await _body(request, DepartmentDraft)
        return _json(Department, await run_in_threadpool(admin.create_department, req.name, req.parent_id))

    @router.put("/api/admin/departments/{department_id}")
    async def update_department(department_id: str, request: Request) -> JSONResponse:
        """C09 之外：修改部门名称、上级部门。"""
        await as_admin(request, is_write=True)
        req: DepartmentDraft = await _body(request, DepartmentDraft)
        return _json(Department, await run_in_threadpool(admin.update_department, department_id, req.name, req.parent_id))

    @router.delete("/api/admin/departments/{department_id}", status_code=204)
    async def delete_department(department_id: str, request: Request) -> Response:
        """C09 之外：删除部门。"""
        await as_admin(request, is_write=True)
        await run_in_threadpool(admin.delete_department, department_id)
        return Response(status_code=204)

    return router
