"""链路 1（真实联调，d_cg）：成本核算主从页的明细。

admin 打开成本核算，选中成本单 2550，在"原料/辅料"页签把第一行（DTLID 206323）的备注改为"测试"并保存：
d_cg 中这一行 MEMO 为"测试"、其余列不变，主表不变；重新加载单据显示"测试"；改回原值保存，数据库恢复。
"客户指定"（CUSTOMER_SPECIFIED，NUMBER(1) 的 0/1，JSON 中为 true/false）勾选后保存为 1，取消后恢复为 0。

200680（E01 的单据）在 cmx 中已经没有明细，改用同为 250mg乙酰唑胺片的 2550（.reports/chain1/findings.md）。
前提：已执行 `platform db copy-business-tables`（含 T_COST_PINGGU_DTL、T_COST_GOODS 和两个明细视图）。
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
DOCID = "2550"
DTLID = "206323"


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(create_app(), base_url="http://localhost:8080") as c:
        yield c


@pytest.fixture(scope="module")
def engine() -> Any:
    s = Settings.load()
    return create_oracle_engine(s.db_user, s.db_password, s.db_dsn)


@pytest.fixture(scope="module")
def csrf(client: TestClient) -> str:
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123.."}, headers={"Origin": ORIGIN})
    assert login.status_code == 200, login.text
    return str(login.json()["csrfToken"])


def db_rows(engine: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """（明细行，主表行）"""
    with engine.connect() as conn:
        detail = conn.execute(text("SELECT * FROM t_cost_pinggu_dtl WHERE dtlid = :d"), {"d": int(DTLID)}).mappings().one()
        master = conn.execute(text("SELECT * FROM t_cost_pinggu WHERE docid = :d"), {"d": int(DOCID)}).mappings().one()
        return dict(detail), dict(master)


def load_record(client: TestClient) -> dict[str, Any]:
    response = client.get(f"/api/pages/{PAGE}/records/{DOCID}")
    assert response.status_code == 200, response.text
    return response.json()


def material_row(record: dict[str, Any]) -> dict[str, Any]:
    return next(r for r in record["details"]["COST_MATERIAL"] if r["rowKey"] == DTLID)


def save_detail(client: TestClient, csrf: str, changes: dict[str, Any]) -> dict[str, Any]:
    command = {
        "requestKey": str(uuid.uuid4()), "page": PAGE, "operation": "COST_PINGGU.save", "params": {},
        "documents": [{"entity": "COST_PINGGU", "master": {"op": "none", "rowKey": DOCID},
                       "details": [{"entity": "COST_MATERIAL", "op": "modify", "rowKey": DTLID, "changes": changes}]}],
    }
    response = client.post("/api/commands", json=command, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
    assert response.status_code == 200, response.text
    return response.json()


def test_page_view_has_two_detail_tabs(client: TestClient, csrf: str) -> None:
    view = client.get(f"/api/pages/{PAGE}/view").json()
    assert view["layout"] == "masterDetail" and view["detailMode"] == "tabs"
    assert [(d["entity"], d["title"], d["primaryKey"], d["parentKey"]) for d in view["details"]] == [
        ("COST_MATERIAL", "原料/辅料", "DTLID", "DOCID"), ("COST_PACKAGE", "包材", "DTLID", "DOCID")]
    for detail in view["details"]:
        fields = {f["name"]: f for f in detail["fields"]}
        assert [n for n, f in fields.items() if f["editable"]] == ["CUSTOMER_SPECIFIED", "MEMO"]
        assert fields["CUSTOMER_SPECIFIED"]["type"] == "boolean"
        assert fields["BATCH_QTY"]["calculated"] and fields["COST_BATCH"]["calculated"]
    material = {f["name"]: f for f in view["details"][0]["fields"]}
    assert list(material)[:6] == ["DTLID", "DOCID", "DTL_USEFLAG", "GOODSID", "GOODSNAME", "CUSTOMER_SPECIFIED"]
    assert material["DTL_USEFLAG"]["label"] == "分类" and material["PER_HL"]["label"] == "每片含量"


def test_record_loads_details_from_views(client: TestClient, csrf: str, engine: Any) -> None:
    record = load_record(client)
    assert record["master"]["rowKey"] == DOCID
    with engine.connect() as conn:
        for entity, view in (("COST_MATERIAL", "v_cost_pinggu_material"), ("COST_PACKAGE", "v_cost_pinggu_package")):
            keys = [str(k) for k in conn.execute(text(f"SELECT dtlid FROM {view} WHERE docid = :d ORDER BY dtlid"),
                                                 {"d": int(DOCID)}).scalars()]
            assert [r["rowKey"] for r in record["details"][entity]] == keys
    assert record["details"]["COST_MATERIAL"][0]["rowKey"] == DTLID
    first = material_row(record)["values"]
    assert first["GOODSNAME"] == "聚维酮K30" and first["CUSTOMER_SPECIFIED"] is False


def test_admin_changes_detail_memo_and_restores(client: TestClient, csrf: str, engine: Any) -> None:
    detail_before, master_before = db_rows(engine)
    original = material_row(load_record(client))["values"]["MEMO"]
    assert original == detail_before["memo"] and original != "测试"

    saved = save_detail(client, csrf, {"MEMO": "测试"})
    assert saved["outcome"] == "saved"
    assert [(r["entity"], r["rowKey"]) for r in saved["rows"]] == [("COST_MATERIAL", DTLID)]
    values = saved["rows"][0]["values"]
    assert values["MEMO"] == "测试" and values["GOODSNAME"] == "聚维酮K30"  # WP-12：含实体的全部字段

    detail_after, master_after = db_rows(engine)
    assert detail_after["memo"] == "测试"
    assert {k: v for k, v in detail_after.items() if k != "memo"} == {k: v for k, v in detail_before.items() if k != "memo"}
    assert master_after == master_before  # 主表为 none，不写
    assert material_row(load_record(client))["values"]["MEMO"] == "测试"  # 重新打开单据

    restored = save_detail(client, csrf, {"MEMO": original})
    assert restored["outcome"] == "saved"
    assert db_rows(engine) == (detail_before, master_before)
    assert material_row(load_record(client))["values"]["MEMO"] == original


def test_admin_checks_customer_specified_and_restores(client: TestClient, csrf: str, engine: Any) -> None:
    detail_before, master_before = db_rows(engine)
    assert detail_before["customer_specified"] == 0

    saved = save_detail(client, csrf, {"CUSTOMER_SPECIFIED": True})
    assert saved["outcome"] == "saved" and saved["rows"][0]["values"]["CUSTOMER_SPECIFIED"] is True
    detail_after, _ = db_rows(engine)
    assert detail_after["customer_specified"] == 1
    assert material_row(load_record(client))["values"]["CUSTOMER_SPECIFIED"] is True

    restored = save_detail(client, csrf, {"CUSTOMER_SPECIFIED": False})
    assert restored["outcome"] == "saved" and restored["rows"][0]["values"]["CUSTOMER_SPECIFIED"] is False
    assert db_rows(engine) == (detail_before, master_before)
