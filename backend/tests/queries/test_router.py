"""C09 第 4 节的接口：路径、方法、请求和响应字段与契约一致（APIRouter 挂在测试用的 FastAPI 应用上，执行上下文
由测试给出，代替 assembly 的会话校验）。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import cost_platform.queries.migrations.qe_0001_pf_personal_config as migration
from cost_platform.contracts.fakes import FakePermissionChecker
from cost_platform.contracts.types import DictConfig, ErrorResponse, ExecutionContext, LookupConfig, PlatformError, dump_wire
from cost_platform.queries.catalog import ItemsCatalog
from cost_platform.queries.exports import XLSX, Exports
from cost_platform.queries.lists import PageQueries
from cost_platform.queries.lookups import DictQueries, LookupQueries
from cost_platform.queries.personal import PersonalConfigs, PersonalConfigStore
from cost_platform.queries.router import QueryServices, build_router

from . import xlsx_reader
from .support import MATERIAL, PAGE, context, database, threaded_factory
from .test_exports import export_config


@pytest.fixture
def client() -> Iterator[tuple[TestClient, list[bool]]]:
    factory = database(threaded_factory())
    with factory.engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    permission = FakePermissionChecker()
    catalog = ItemsCatalog(
        lookups={"GOODS": LookupConfig(table="T_COST_GOODS", columns=["GOODSID", "GOODSNAME"], keyword_columns=["GOODSNAME"],
                                       order_by="GOODSID")},
        dicts={"STATUS": DictConfig(items=[{"value": "1", "label": "启用", "order": 1}])},
        exports={"cost-pinggu-export": export_config()}, sums={(PAGE, "master"): ["TOTAL_COST"]})
    services = QueryServices(
        lists=PageQueries(factory, permission, catalog=lambda ctx: catalog),
        lookups=LookupQueries(factory, lambda ctx: catalog), dicts=DictQueries(lambda ctx: catalog),
        personal=PersonalConfigs(PersonalConfigStore(factory)), exports=Exports(factory, permission, lambda ctx: catalog))
    writes: list[bool] = []

    def ctx(_request: Request, is_write: bool) -> ExecutionContext:
        writes.append(is_write)
        return context()

    app = FastAPI()
    app.include_router(build_router(services, ctx))

    @app.exception_handler(PlatformError)
    async def platform_error(_request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(dump_wire(ErrorResponse, exc.to_response()), status_code=exc.http_status)

    with TestClient(app) as c:
        yield c, writes


def test_rows(client: tuple[TestClient, list[bool]]) -> None:
    c, writes = client
    body = {"startRow": 0, "endRow": 2, "sortModel": [{"colId": "DOCID", "sort": "desc"}],
            "filterModel": {"GOODSNAME": {"filterType": "text", "type": "contains", "filter": "胶囊"}}}
    response = c.post(f"/api/pages/{PAGE}/rows", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert set(data) == {"rows", "total", "aggregates"} and data["total"] == 3
    assert [r["rowKey"] for r in data["rows"]] == ["1005", "1003"]
    assert set(data["rows"][0]) == {"rowKey", "values", "frozen"} and data["rows"][0]["frozen"] is None
    assert float(data["aggregates"]["TOTAL_COST"]) == 21
    assert writes == [True]  # POST 带 CSRF（C09 第 1 节）


def test_rows_by_keys_and_record(client: tuple[TestClient, list[bool]]) -> None:
    c, writes = client
    found = c.post(f"/api/pages/{PAGE}/rows/by-keys", json={"entity": "COST_PINGGU", "rowKeys": ["1002", "9999"]})
    assert found.status_code == 200 and [r["rowKey"] for r in found.json()["rows"]] == ["1002"]
    record = c.get(f"/api/pages/{PAGE}/records/1002")
    assert record.status_code == 200
    data = record.json()
    assert data["master"]["rowKey"] == "1002" and [r["rowKey"] for r in data["details"][MATERIAL]] == ["5002", "5003"]
    missing = c.get(f"/api/pages/{PAGE}/records/9999")
    assert missing.status_code == 404 and missing.json()["code"] == "NOT_FOUND"
    assert writes == [True, False, False]


def test_invisible_field_is_422(client: tuple[TestClient, list[bool]]) -> None:
    c, _ = client
    response = c.post(f"/api/pages/{PAGE}/rows", json={"startRow": 0, "endRow": 10, "sortModel": [{"colId": "CREATE_BY", "sort": "asc"}]})
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_FAILED"


def test_request_not_matching_the_contract_is_400(client: tuple[TestClient, list[bool]]) -> None:
    c, _ = client
    response = c.post(f"/api/pages/{PAGE}/rows", json={"start_row": 0, "end_row": 10})
    assert response.status_code == 400 and response.json()["code"] == "INVALID_REQUEST"


def test_lookup_and_dict(client: tuple[TestClient, list[bool]]) -> None:
    c, _ = client
    found = c.post("/api/lookups/GOODS/search", json={"keyword": "胶", "startRow": 0, "endRow": 50})
    assert found.status_code == 200
    assert found.json() == {"rows": [{"values": {"GOODSID": "116", "GOODSNAME": "胶囊壳"}},
                                     {"values": {"GOODSID": "118", "GOODSNAME": "空心胶囊"}},
                                     {"values": {"GOODSID": "119", "GOODSNAME": "胶体二氧化硅"}}],
                            "total": 3, "keywordSearch": True}
    assert c.get("/api/dicts/STATUS").json() == {"items": [{"value": "1", "label": "启用"}]}
    assert c.get("/api/dicts/NOPE").json() == {"items": []}


def test_personal_config(client: tuple[TestClient, list[bool]]) -> None:
    c, writes = client
    assert c.get(f"/api/pages/{PAGE}/personal").json() == {}
    grid = {"columns": [{"field": "DOCID", "width": 120, "pinned": "left", "hide": False}]}
    saved = c.put(f"/api/pages/{PAGE}/personal", json={"grids": {"master": grid}})
    assert saved.status_code == 200 and saved.json() == {"grids": {"master": grid}}
    again = c.put(f"/api/pages/{PAGE}/personal", json={"detailMode": "stack"})
    assert again.json() == {"grids": {"master": grid}, "detailMode": "stack"}
    assert writes == [False, True, True]


def test_exports(client: tuple[TestClient, list[bool]]) -> None:
    c, _ = client
    assert c.get(f"/api/pages/{PAGE}/exports").json() == {"items": [{"exportCode": "cost-pinggu-export", "name": "物料成本核算表导出"}]}
    request: dict[str, Any] = {"startRow": 0, "endRow": 100}
    page = c.post(f"/api/pages/{PAGE}/export", json={"mode": "page", "request": request, "columns": ["DOCID", "GOODSNAME"]})
    assert page.status_code == 200 and page.headers["content-type"] == XLSX
    assert page.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
    assert xlsx_reader.read(page.content).sheet("成本核算").row(2) == ["1001", "胶囊A"]
    config = c.post(f"/api/pages/{PAGE}/export", json={"mode": "config", "exportCode": "cost-pinggu-export", "scope": "all",
                                                       "request": request})
    assert config.status_code == 200
    assert config.headers["content-disposition"] == ("attachment; filename*=UTF-8''"
                                                     "%E7%89%A9%E6%96%99%E6%88%90%E6%9C%AC%E6%A0%B8%E7%AE%97%E8%A1%A8.xlsx")
    assert xlsx_reader.read(config.content).sheets[0].name == "物料成本核算"
