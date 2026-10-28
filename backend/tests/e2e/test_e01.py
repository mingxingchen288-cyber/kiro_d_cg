"""T-AS-9 业务例子 E01（真实联调，d_cg）：admin 在成本核算页把单据 200680 主表的 MEMO 改为"测试"并保存，
Oracle 中该行 MEMO 为"测试"、其余列不变；重新打开页面显示"测试"；改回原值再保存，数据库恢复原值。

经 HTTP 接口走完整条后端链路：登录 → 页面视图 → 列表 → 命令 → 回读。前提：已执行 `platform db upgrade` 和
`platform db copy-business-tables`。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from cost_platform.assembly.app import create_app
from cost_platform.assembly.settings import Settings
from cost_platform.db_core.engine import create_oracle_engine

pytestmark = pytest.mark.oracle

ORIGIN = "http://localhost:9527"
PAGE = "COST_PINGGU"
DOCID = "200680"


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(create_app(), base_url="http://localhost:8080") as c:
        yield c


@pytest.fixture(scope="module")
def engine() -> Any:
    s = Settings.load()
    return create_oracle_engine(s.db_user, s.db_password, s.db_dsn)


def db_row(engine: Any) -> dict[str, Any]:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM t_cost_pinggu WHERE docid = :d"), {"d": int(DOCID)})
        return dict(result.mappings().one())


def save_memo(client: TestClient, csrf: str, memo: str | None) -> dict[str, Any]:
    command = {
        "requestKey": str(uuid.uuid4()), "page": PAGE, "operation": "COST_PINGGU.save", "params": {},
        "documents": [{"entity": "COST_PINGGU", "master": {"op": "modify", "rowKey": DOCID, "changes": {"MEMO": memo}},
                       "details": []}],
    }
    response = client.post("/api/commands", json=command, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
    assert response.status_code == 200, response.text
    return response.json()


def find_row(client: TestClient, csrf: str) -> dict[str, Any]:
    body = {"startRow": 0, "endRow": 100, "sortModel": [{"colId": "DOCID", "sort": "desc"}]}
    response = client.post(f"/api/pages/{PAGE}/rows", json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] > 0
    return next(r for r in data["rows"] if r["rowKey"] == DOCID)


def test_e01_admin_changes_memo_and_restores(client: TestClient, engine: Any) -> None:
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123.."}, headers={"Origin": ORIGIN})
    assert login.status_code == 200, login.text
    csrf = login.json()["csrfToken"]
    assert login.json()["selectedRole"]["code"] == "ADMIN"
    assert "cp_session" in client.cookies

    me = client.get("/api/me").json()
    assert me["menus"][0]["children"][0]["pageCode"] == PAGE

    view = client.get(f"/api/pages/{PAGE}/view").json()
    memo_field = next(f for f in view["master"]["fields"] if f["name"] == "MEMO")
    assert memo_field["editable"] is True and memo_field["visible"] is True

    before = db_row(engine)
    original = find_row(client, csrf)["values"]["MEMO"]
    assert original == before["memo"]

    saved = save_memo(client, csrf, "测试")
    assert saved["outcome"] == "saved"
    assert saved["rows"][0]["rowKey"] == DOCID and saved["rows"][0]["values"]["MEMO"] == "测试"

    after = db_row(engine)
    assert after["memo"] == "测试"
    assert {k: v for k, v in after.items() if k != "memo"} == {k: v for k, v in before.items() if k != "memo"}
    assert find_row(client, csrf)["values"]["MEMO"] == "测试"  # 重新打开页面

    restored = save_memo(client, csrf, original)
    assert restored["outcome"] == "saved"
    assert db_row(engine) == before
    assert find_row(client, csrf)["values"]["MEMO"] == original
