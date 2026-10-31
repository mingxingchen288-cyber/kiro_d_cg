"""C09 第 3 节的接口（APIRouter）。执行上下文按请求头 X-Test-Role 取配置快照，代替 assembly 的中间件。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from cost_platform.config.router import create_router
from cost_platform.contracts.types import ErrorResponse, ExecutionContext, Identity, Origin, PlatformError, dump_wire

from .support import Env, draft, seed_drafts


@pytest.fixture
def env() -> Env:
    env = Env()
    env.save([*seed_drafts(), draft("role", "R", {"name": "成本会计", "admin": False, "pages": {"COST_PINGGU": {}}})])
    return env


@pytest.fixture
def client(env: Env) -> TestClient:
    def context(request: Request, is_write: bool) -> ExecutionContext:
        role = request.headers.get("x-test-role", "ADMIN")
        snapshot = env.reader.read(role)
        who = Identity(user_id="7", username="admin", display_name="管理员", department_id=None, role_code=role, session_id="s")
        return ExecutionContext(request_id="r", identity=who, config=snapshot, config_version=snapshot.version,
                                origin=Origin("user", None), now=datetime(2026, 10, 29, 9, 0, 0))

    app = FastAPI()
    app.include_router(create_router(env.service, context))

    @app.exception_handler(PlatformError)
    async def handler(_request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(dump_wire(ErrorResponse, exc.to_response()), status_code=exc.http_status)

    return TestClient(app)


def _page() -> dict[str, Any]:
    return next(d for d in seed_drafts() if d.type == "page" and d.key == "COST_PINGGU").content


def test_page_view_and_rules_pack(client: TestClient, env: Env) -> None:
    view = client.get("/api/pages/COST_PINGGU/view")
    assert view.status_code == 200 and view.json()["pageCode"] == "COST_PINGGU"
    assert client.get("/api/pages/NO_PAGE/view").status_code == 404
    env.save([draft("role", "R", {"name": "成本会计", "admin": False, "pages": {}})])
    assert client.get("/api/pages/COST_PINGGU/view", headers={"X-Test-Role": "R"}).status_code == 403
    pack = view.json()["rulesPack"]
    found = client.get(f"/api/rules-packs/{pack['packId']}/{pack['version']}")
    assert found.status_code == 200 and found.json()["packId"] == "COST_PINGGU"
    assert client.get(f"/api/rules-packs/COST_PINGGU/{pack['version'] + 100}").status_code == 404


def test_config_items_admin_only(client: TestClient) -> None:
    items = client.get("/api/config/items", params={"type": "page"})
    assert items.status_code == 200
    assert [(i["type"], i["key"], i["version"]) for i in items.json()["items"]] == [
        ("page", "AUDIT_LOG", 1), ("page", "COST_PINGGU", 1), ("page", "GOODS_PRICE_MANAGE", 1)]
    denied = client.get("/api/config/items", headers={"X-Test-Role": "R"})
    assert denied.status_code == 403 and denied.json()["code"] == "PERMISSION_DENIED"
    item = client.get("/api/config/items/page/COST_PINGGU")
    assert item.status_code == 200 and item.json()["content"] == _page()


def test_save_validate_and_delete(client: TestClient, env: Env) -> None:
    saved = client.put("/api/config/items/page/COST_PINGGU", json={"name": "成本核算", "content": {**_page(), "title": "成本"}})
    assert saved.status_code == 200 and saved.json() == {"type": "page", "key": "COST_PINGGU", "version": 2}
    assert client.get("/api/pages/COST_PINGGU/view").json()["title"] == "成本"
    bad = client.put("/api/config/items/page/COST_PINGGU", json={"name": "成本核算", "content": {**_page(), "saveOperation": "X"}})
    assert bad.status_code == 422
    detail = bad.json()["details"][0]
    assert (detail["configType"], detail["configKey"], detail["path"]) == ("page", "COST_PINGGU", "saveOperation")
    missing = client.put("/api/config/items/page/COST_PINGGU", json={"name": "成本核算", "content": {"title": "x"}})
    assert missing.status_code == 422 and missing.json()["details"][0]["message"].startswith("缺少")
    check = client.post("/api/config/validate", json={"items": [
        {"type": "page", "key": "COST_PINGGU", "name": "成本核算", "content": {**_page(), "saveOperation": "X"}}]})
    assert check.status_code == 200 and check.json()["ok"] is False and check.json()["errors"][0]["path"] == "saveOperation"
    assert client.delete("/api/config/items/entity/COST_MATERIAL").status_code == 422
    assert client.delete("/api/config/items/role/R").status_code == 204
    assert client.get("/api/config/items/role/R").status_code == 404


def test_wizard_and_schema_endpoints(client: TestClient, env: Env) -> None:
    columns = client.post("/api/config/wizard/columns", json={"readView": "T_COST_GOODS_PRICE_V", "table": "T_COST_GOODS"})
    assert columns.status_code == 200 and columns.json()["sequence"] == {"name": "T_COST_GOODS_SEQ", "exists": True}
    schema = client.post("/api/config/schema/columns", json={"name": "V_COST_PINGGU_MATERIAL"})
    assert schema.json()["objectType"] == "view" and schema.json()["primaryKey"] is None
    assert client.post("/api/config/schema/columns", json={"name": "T_NO"}).json() == {
        "objectType": None, "primaryKey": None, "columns": []}
    # seed 已有物料清单页 GOODS_PRICE_MANAGE，向导用另外的编码在同一张表上新建一页
    generated = client.post("/api/config/wizard/generate", json={
        "parentMenu": "cost", "pageCode": "GOODS_WIZARD", "title": "物料清单（向导）", "layout": "single",
        "detailMode": "tabs", "audit": True, "details": [],
        "master": {"entity": "COST_GOODS_WIZARD", "table": "T_COST_GOODS", "readView": "T_COST_GOODS_PRICE_V"}})
    assert generated.status_code == 200
    assert {(i["type"], i["key"]) for i in generated.json()["items"]} >= {("page", "GOODS_WIZARD"), ("role", "ADMIN")}
    assert client.get("/api/pages/GOODS_WIZARD/view").status_code == 200
