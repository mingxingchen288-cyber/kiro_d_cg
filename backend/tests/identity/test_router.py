"""C09 第 2 节的 HTTP 接口（模拟验证）：经 FastAPI 的 TestClient 调用 identity 的 `APIRouter`。

测试中的应用只挂 identity 的路由，并按 C03 把 `PlatformError` 转成响应（上线时由 assembly 做）。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from cost_platform.contracts.types import ErrorResponse, PlatformError, dump_wire
from cost_platform.identity.router import identity_router

from .support import ACCOUNTANT, ADMIN_ROLE, BUYER, Env

PASSWORD = "Abc123.."
ORIGIN = "http://localhost:9527"   # .env.example 的 PLATFORM_ALLOWED_ORIGINS


@pytest.fixture
def env() -> Env:
    env = Env()
    env.accounts.ensure_admin()
    return env


def _app(env: Env) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(PlatformError)
    async def platform_error(_request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(dump_wire(ErrorResponse, exc.to_response()), status_code=exc.http_status)

    app.include_router(identity_router(env.identity, env.admin, env.config, allowed_origins=frozenset({ORIGIN})))
    return app


@pytest.fixture
def client(env: Env) -> TestClient:
    """浏览器打开平台前端：每个请求都带前端的 Origin。"""
    return TestClient(_app(env), headers={"Origin": ORIGIN})


def _login(client: TestClient, username: str, password: str = PASSWORD) -> dict[str, Any]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def _admin(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": _login(client, "admin", "admin123..")["csrfToken"]}


def test_login_sets_session_cookie(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123.."})
    assert response.status_code == 200
    body = response.json()
    assert body["selectedRole"] == {"code": ADMIN_ROLE, "name": "系统管理员", "admin": True}
    assert body["user"]["username"] == "admin" and body["user"]["departmentId"] is None
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("cp_session=") and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert response.cookies["cp_session"] not in response.text  # 会话编号不出现在响应体中（C09 第 1 节）


def test_write_from_other_origin_is_rejected(env: Env) -> None:
    """AS-02：不是从平台前端发起的写请求（含登录）为 403 ORIGIN_REJECTED；读请求不看 Origin。"""
    other = TestClient(_app(env), headers={"Origin": "http://evil.example"})
    response = other.post("/api/auth/login", json={"username": "admin", "password": "admin123.."})
    assert response.status_code == 403 and response.json()["code"] == "ORIGIN_REJECTED"
    assert other.get("/api/me").json()["code"] == "SESSION_REQUIRED"


def test_login_failed(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-pass"})
    assert response.status_code == 401 and response.json()["code"] == "LOGIN_FAILED"


def test_me_menus_come_from_config_snapshot(client: TestClient, env: Env) -> None:
    """ID-09：/api/me 的菜单取自当前角色的配置快照。"""
    env.add_account("HY090702", PASSWORD, [ACCOUNTANT, BUYER])
    login = _login(client, "HY090702")
    me = client.get("/api/me").json()
    assert me["role"] is None and me["menus"] == [] and me["configVersion"] == 13
    assert me["csrfToken"] == login["csrfToken"]

    chosen = client.post("/api/auth/role", json={"roleCode": ACCOUNTANT}, headers={"X-CSRF-Token": login["csrfToken"]})
    assert chosen.status_code == 200 and chosen.json() == {"selectedRole": {"code": ACCOUNTANT, "name": "成本会计", "admin": False}}
    me = client.get("/api/me").json()
    assert me["role"] == {"code": ACCOUNTANT, "name": "成本会计", "admin": False}
    assert me["menus"][0]["children"][0]["pageCode"] == "COST_PINGGU"


def test_role_not_owned(client: TestClient, env: Env) -> None:
    env.add_account("HY090702", PASSWORD, [ACCOUNTANT, BUYER])
    login = _login(client, "HY090702")
    response = client.post("/api/auth/role", json={"roleCode": ADMIN_ROLE}, headers={"X-CSRF-Token": login["csrfToken"]})
    assert response.status_code == 403 and response.json()["code"] == "PERMISSION_DENIED"


def test_logout(client: TestClient, env: Env) -> None:
    headers = _admin(client)
    response = client.post("/api/auth/logout", headers=headers)
    assert response.status_code == 204
    assert client.get("/api/me").json()["code"] == "SESSION_REQUIRED"
    assert [e.payload.reason for e in env.events.events] == ["loggedOut"]


def test_background_request_does_not_extend_session(client: TestClient, env: Env) -> None:
    """E19 经 HTTP：带 X-Background-Request: 1 的 /api/me 不顺延会话。"""
    from datetime import timedelta

    _login(client, "admin", "admin123..")
    env.clock.advance(timedelta(minutes=100))
    assert client.get("/api/me", headers={"X-Background-Request": "1"}).status_code == 200
    env.clock.advance(timedelta(minutes=20))
    response = client.get("/api/me")
    assert response.status_code == 401 and response.json()["code"] == "SESSION_REQUIRED"


def test_admin_manages_accounts(client: TestClient, env: Env) -> None:
    headers = _admin(client)
    created = client.post("/api/admin/accounts", headers=headers, json={
        "username": "zhangsan", "displayName": "张三", "departmentId": "10", "password": PASSWORD,
        "roleCodes": [ACCOUNTANT]})
    assert created.status_code == 200, created.text
    account = created.json()
    assert {k: account[k] for k in ("username", "displayName", "departmentId", "enabled", "roleCodes")} == \
        {"username": "zhangsan", "displayName": "张三", "departmentId": "10", "enabled": True, "roleCodes": [ACCOUNTANT]}

    duplicate = client.post("/api/admin/accounts", headers=headers, json={
        "username": "zhangsan", "displayName": "张三", "departmentId": None, "password": PASSWORD, "roleCodes": []})
    assert duplicate.status_code == 422 and duplicate.json()["code"] == "VALIDATION_FAILED"

    listed = client.get("/api/admin/accounts", params={"keyword": "zhang", "startRow": 0, "endRow": 50}).json()
    assert listed["total"] == 1 and listed["rows"][0]["userId"] == account["userId"]
    by_role = client.get("/api/admin/accounts", params={"roleCode": ADMIN_ROLE}).json()
    assert [r["username"] for r in by_role["rows"]] == ["admin"]

    updated = client.put(f"/api/admin/accounts/{account['userId']}", headers=headers, json={
        "displayName": "张三", "departmentId": "10", "roleCodes": [ACCOUNTANT, BUYER], "enabled": True})
    assert updated.status_code == 200 and updated.json()["roleCodes"] == [BUYER, ACCOUNTANT]

    password = client.post(f"/api/admin/accounts/{account['userId']}/password", headers=headers,
                           json={"password": "Init123.."})
    assert password.status_code == 204
    env.identity.login("zhangsan", "Init123..")


def test_admin_disables_account(client: TestClient, env: Env) -> None:
    uid = env.add_account("HY260404", PASSWORD, [ACCOUNTANT], display_name="程苏慧")
    user_session, _ = env.identity.login("HY260404", PASSWORD)
    headers = _admin(client)
    response = client.put(f"/api/admin/accounts/{uid}", headers=headers, json={
        "displayName": "程苏慧", "departmentId": "581", "roleCodes": [ACCOUNTANT], "enabled": False})
    assert response.status_code == 200 and response.json()["enabled"] is False
    with pytest.raises(PlatformError) as caught:
        env.identity.authenticate(user_session, None, False)
    assert caught.value.code.value == "SESSION_REQUIRED"
    assert [(e.audience.users, e.payload.reason) for e in env.events.events] == [([uid], "accountDisabled")]  # type: ignore[union-attr]


def test_non_admin_is_denied(client: TestClient, env: Env) -> None:
    env.add_account("HY260404", PASSWORD, [ACCOUNTANT])
    headers = {"X-CSRF-Token": _login(client, "HY260404")["csrfToken"]}
    for response in (client.get("/api/admin/accounts"), client.get("/api/admin/departments"),
                     client.post("/api/admin/accounts", headers=headers, json={
                         "username": "lisi", "displayName": "李四", "departmentId": None, "password": PASSWORD,
                         "roleCodes": []})):
        assert response.status_code == 403 and response.json()["code"] == "PERMISSION_DENIED"


def test_write_without_csrf(client: TestClient) -> None:
    _admin(client)
    response = client.post("/api/admin/departments", json={"name": "市场部", "parentId": None})
    assert response.status_code == 403 and response.json()["code"] == "CSRF_FAILED"


def test_departments(client: TestClient) -> None:
    headers = _admin(client)
    created = client.post("/api/admin/departments", headers=headers, json={"name": "市场部", "parentId": None})
    assert created.status_code == 200
    dept = created.json()
    child = client.post("/api/admin/departments", headers=headers,
                        json={"name": "国内营销中心", "parentId": dept["departmentId"]}).json()
    renamed = client.put(f"/api/admin/departments/{dept['departmentId']}", headers=headers,
                         json={"name": "国际市场部", "parentId": None})
    assert renamed.json() == {"departmentId": dept["departmentId"], "name": "国际市场部", "parentId": None}
    assert client.get("/api/admin/departments").json() == {"items": [renamed.json(), child]}
    assert client.delete(f"/api/admin/departments/{child['departmentId']}", headers=headers).status_code == 204
    assert client.get("/api/admin/departments").json() == {"items": [renamed.json()]}


def test_rename_account_search_and_department_name(client: TestClient, env: Env) -> None:
    """C09 v15 经 HTTP：PUT 带 username 改账号名（重名 422）；列表的 `advanced`；`/api/me` 的 departmentName。"""
    headers = _admin(client)
    dept = client.post("/api/admin/departments", headers=headers, json={"name": "技术中心", "parentId": None}).json()
    uid = env.add_account("HY221020", PASSWORD, [ACCOUNTANT], display_name="韩群", department_id=dept["departmentId"])

    renamed = client.put(f"/api/admin/accounts/{uid}", headers=headers, json={
        "username": "HY221021", "displayName": "韩群", "departmentId": dept["departmentId"], "roleCodes": [ACCOUNTANT],
        "enabled": True})
    assert renamed.status_code == 200 and renamed.json()["username"] == "HY221021"
    taken = client.put(f"/api/admin/accounts/{uid}", headers=headers, json={
        "username": "admin", "displayName": "韩群", "departmentId": None, "roleCodes": [ACCOUNTANT], "enabled": True})
    assert taken.status_code == 422 and taken.json()["details"][0]["field"] == "username"

    advanced = json.dumps({"op": "and", "conditions": [{"field": "displayName", "operator": "like", "value": "韩"},
                                                       {"field": "departmentId", "operator": "eq",
                                                        "value": dept["departmentId"]}]})
    listed = client.get("/api/admin/accounts", params={"startRow": 0, "endRow": 50, "advanced": advanced}).json()
    assert [r["username"] for r in listed["rows"]] == ["HY221021"] and listed["total"] == 1
    by_name = json.dumps({"op": "and", "conditions": [{"field": "name", "operator": "like", "value": "技术"}]})
    assert client.get("/api/admin/departments", params={"advanced": by_name}).json()["items"] == [dept]
    wrong = client.get("/api/admin/departments", params={"advanced": "{"})
    assert wrong.status_code == 422 and wrong.json()["code"] == "VALIDATION_FAILED"

    user = TestClient(_app(env))
    assert user.post("/api/auth/login", headers={"Origin": ORIGIN},
                     json={"username": "HY221021", "password": PASSWORD}).json()["user"]["departmentName"] == "技术中心"
    assert user.get("/api/me").json()["user"] == {"userId": uid, "username": "HY221021", "displayName": "韩群",
                                                  "departmentId": dept["departmentId"], "departmentName": "技术中心"}


def test_change_own_password(client: TestClient, env: Env) -> None:
    env.add_account("HY260404", PASSWORD, [ACCOUNTANT])
    headers = {"X-CSRF-Token": _login(client, "HY260404")["csrfToken"]}
    assert client.post("/api/auth/password", headers=headers, json={"password": "Xyz789.."}).status_code == 204
    _login(client, "HY260404", "Xyz789..")
