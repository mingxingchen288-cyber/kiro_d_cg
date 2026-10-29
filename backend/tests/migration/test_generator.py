"""用 cmx 的旧数据快照生成配置和清单（T-MG-1、T-MG-2 的模拟验证）。

快照 tests/migration/data/cmx-snapshot.json 由 `snapshot.read_snapshot` 只读查询 cmx 得到。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from cost_platform.contracts.types import parse_config_content
from cost_platform.migration import generate_from_snapshot
from cost_platform.migration.snapshot import load_snapshot

SNAPSHOT = load_snapshot(Path(__file__).parent / "data" / "cmx-snapshot.json")


@pytest.fixture(scope="module")
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("migration")
    generate_from_snapshot(SNAPSHOT, path)
    return path


def item(out: Path, type_: str, key: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((out / "config" / f"{type_}.{key}.json").read_text(encoding="utf-8"))
    return data["content"]


def fields(out: Path, entity: str) -> dict[str, dict[str, Any]]:
    return {f["name"]: f for f in item(out, "entity", entity)["fields"]}


def entries(out: Path) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in json.loads((out / "清单.json").read_text(encoding="utf-8"))}


# ---------------------------------------------------------------- MG-01、MG-11、C06 解析

def test_repeated_runs_write_identical_bytes(out: Path, tmp_path: Path) -> None:
    generate_from_snapshot(SNAPSHOT, tmp_path)
    first = {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    second = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert first == second


def test_every_item_parses_and_traces_to_legacy_rows(out: Path) -> None:
    sources = {(s["type"], s["key"]): s["sources"] for s in json.loads((out / "来源.json").read_text(encoding="utf-8"))}
    files = sorted((out / "config").glob("*.json"))
    assert len(files) == len(sources) > 0
    for path in files:
        draft = json.loads(path.read_text(encoding="utf-8"))
        assert set(draft) == {"type", "key", "name", "content"}
        parse_config_content(draft["type"], draft["content"])
        found = sources[(draft["type"], draft["key"])]
        assert found and all(_exists(s) for s in found), path.name


def test_every_list_entry_traces_to_legacy_rows(out: Path) -> None:
    for e in entries(out).values():
        assert e["sources"] and all(_exists(s) for s in e["sources"]), e["id"]


def _exists(source: dict[str, str]) -> bool:
    if source["table"] == "ALL_TAB_COLS":
        table, column = (p.split("=")[1] for p in source["key"].split(","))
        return any(r["TABLE_NAME"] == table and r["COLUMN_NAME"] == column for r in SNAPSHOT["ALL_TAB_COLS"])
    column, value = source["key"].split("=")
    return any(str(r[column]) == value for r in SNAPSHOT[source["table"]])


# ---------------------------------------------------------------- 成本核算：实体（MG-13、MG-14）

def test_master_entity_has_the_43_visible_columns_and_memo_is_editable(out: Path) -> None:
    entity = item(out, "entity", "COST_PINGGU")
    names = [f["name"] for f in entity["fields"]]
    assert len(names) == 43 and "DELETED" not in names and not any(n.endswith("_OLD") for n in names)
    assert "MEMO" not in entity["fieldDefaults"]
    assert "MEMO" in item(out, "operation", "COST_PINGGU.save")["writableFields"]["COST_PINGGU"]


def test_detail_fields_from_goods_table_are_read_only_view_fields(out: Path) -> None:
    from_goods = {"GOODSNAME", "DTL_USEFLAG", "STANDARDTYPE", "FACTORYNAME", "GOODSTYPE", "BASE_PRICE", "SUQTY", "GOODSNAME_EN"}
    for entity, view in (("COST_MATERIAL", "V_COST_PINGGU_MATERIAL"), ("COST_PACKAGE", "V_COST_PINGGU_PACKAGE")):
        content = item(out, "entity", entity)
        assert (content["table"], content["readView"]) == ("T_COST_PINGGU_DTL", view)
        got = fields(out, entity)
        assert {n for n, f in got.items() if f["column"] is None} == from_goods
        assert not {"APEX_PL", "P_PERPACK", "S_PERBACK", "X_PERBACK", "M_PERPACK", "BATCH_QTY_OLD"} & set(got)
        assert "DTL_USEFLAG" not in item(out, "operation", "COST_PINGGU.save")["writableFields"][entity]


# ---------------------------------------------------------------- 成本核算：计算规则（MG-12）

def test_virtual_columns_and_master_totals_are_calculated(out: Path) -> None:
    calculated = {n for n, f in fields(out, "COST_PINGGU").items() if f["role"] == "calculated"}
    assert calculated == {"OUT_PRICE_RMB", "TOTAL_COST", "SALEMONEY", "JGF_BATCH", "COST_PERBOX", "JGF_PERQP", "ML_PERQP",
                          "Y_JG_RE", "Y_ML", "Y_SALE", "TOTAL_YL", "TOTAL_FL", "TOTAL_BC"}
    assert item(out, "rule", "COST_PINGGU.JGF_BATCH")["expression"] == "SALEMONEY - TOTAL_COST"
    assert item(out, "rule", "COST_PINGGU.TOTAL_FL")["expression"] == (
        "sum(map(filter(COST_MATERIAL, #.DTL_USEFLAG == '辅料'), #.COST_BATCH)) * "
        "(sum(map(filter(COST_MATERIAL, #.DTL_USEFLAG == '原料'), #.COST_BATCH)) > 0 ? 1 / 1.13 : 1)")


def test_detail_batch_qty_takes_master_values_and_cost_batch_follows(out: Path) -> None:
    for entity in ("COST_MATERIAL", "COST_PACKAGE"):
        rule = item(out, "rule", f"{entity}.BATCH_QTY")
        assert rule["target"] == entity and len(rule["branches"]) == 7
        assert all("when" in b for b in rule["branches"])  # 都不成立时保持原值，没有兜底分支
        assert rule["branches"][2]["expression"] == "master.APEX_PL / master.P_PERPACK * (1 + EXADD_MATER / 100)"
        assert item(out, "rule", f"{entity}.COST_BATCH")["expression"] == "BATCH_QTY * PRICE"


# ---------------------------------------------------------------- 页面、Lookup、角色、菜单

def test_page_regions_buttons_and_lookup(out: Path) -> None:
    page = item(out, "page", "COST_PINGGU")
    assert (page["layout"], page["detailMode"], page["audit"], page["saveOperation"]) == \
        ("masterDetail", "tabs", False, "COST_PINGGU.save")
    assert [d["entity"] for d in page["details"]] == ["COST_MATERIAL", "COST_PACKAGE"]
    assert [b["action"] for b in page["master"]["buttons"]] == ["addRow", "copyRow", "deleteRow", "saveGridConfig"]
    lookup = page["details"][0]["fields"]["GOODSID"]["lookup"]
    assert lookup["code"] == "COST_MATERIAL_EFFECTIVE" and lookup["fill"]["PRICE"] == "ZX_PRICE"
    assert item(out, "lookup", "COST_MATERIAL_EFFECTIVE")["table"] == "T_COST_GOODS_PRICE_V"


def test_roles_convert_button_groups_and_keep_row_policy(out: Path) -> None:
    admin = item(out, "role", "ADMIN")
    assert admin["admin"] is True and admin["pages"]["COST_PINGGU"]["buttons"] == ["*"]
    tech = item(out, "role", "技术中心")
    assert tech["admin"] is False
    assert tech["pages"]["COST_PINGGU"]["buttons"] == [
        "system:save", "system:advancedSearch", "master:copyRow", "master:saveGridConfig",
        "COST_MATERIAL:copyRow", "COST_MATERIAL:saveGridConfig", "COST_PACKAGE:copyRow", "COST_PACKAGE:saveGridConfig"]
    assert tech["pages"]["COST_PINGGU"]["rows"]["sql"] == "USESTATUS = '评估中' OR USESTATUS = '已立项'"
    assert tech["pages"]["COST_PINGGU"]["columns"]["COST_MATERIAL"]["PRICE"] == {"visible": False, "editable": False}


def test_menu_has_the_migrated_pages(out: Path) -> None:
    items = item(out, "menu", "main")["items"]
    assert [i["key"] for i in items] == ["COST_PINGGU", "COST_PINGGU_LQ", "COST"]
    assert items[2]["children"][0]["pageCode"] == "GOODS_PRICE_MANAGE"


# ---------------------------------------------------------------- 审批流（MG-03，C06 7.8～7.10）

_DOCS = Path(__file__).resolve().parents[3] / "docs" / "契约"
_FLOW_IDS = {"COST_TO_GOODS": 81, "TECH_CUSTOMER_MATERIAL": 71, "GOODS_TO_COST": 82}


def _flow_samples() -> dict[str, dict[str, Any]]:
    text = next(_DOCS.glob("C06-*.md")).read_text(encoding="utf-8")
    blocks = [json.loads(b) for b in re.findall(r"```json\n(.*?)```", text, flags=re.S)]
    return {b["key"]: b["content"] for b in blocks if b.get("type") == "approvalFlow"}


def _confirmed_flows() -> dict[str, str]:
    """用户确认的审核操作和第 1 级入口条件（《审批流配置定稿》，2026-10-28），取自 C06 7.8～7.10 的样例。"""
    out = {}
    for key, content in _flow_samples().items():
        node = content["levels"][0]["nodes"][0]
        confirmed: dict[str, Any] = {"operations": content["operations"], "condition": node["condition"]}
        if node.get("department"):
            confirmed["department"] = node["department"]
        if key == "TECH_CUSTOMER_MATERIAL":
            confirmed["key"] = key
        out[f"MR-FLOW-{_FLOW_IDS[key]}-入口条件"] = json.dumps(confirmed, ensure_ascii=False)
    return out


@pytest.fixture(scope="module")
def flows_out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("migration-flows")
    generate_from_snapshot(SNAPSHOT, path, _confirmed_flows())
    return path


def test_flows_wait_for_confirmed_entry_conditions(out: Path) -> None:
    assert not list((out / "config").glob("approvalFlow.*.json"))
    assert {f"MR-FLOW-{i}-入口条件" for i in _FLOW_IDS.values()} <= set(entries(out))


def test_cost_to_goods_flow(flows_out: Path) -> None:
    sample = _flow_samples()["COST_TO_GOODS"]
    flow = item(flows_out, "approvalFlow", "COST_TO_GOODS")
    parse_config_content("approvalFlow", flow)
    assert (flow["page"], flow["operations"]) == ("COST_PINGGU", sample["operations"])
    assert flow["levels"][0]["nodes"][0] == {"name": "管理员审批", "conditionType": "sql",
                                             "condition": sample["levels"][0]["nodes"][0]["condition"],
                                             "approvers": [{"type": "role", "role": "ADMIN"}], "mode": "or"}
    assert flow["freeze"] == [{"table": "T_COST_GOODS", "condition": "GOODSID = :new_GOODSID"}]
    goods = [b for b in flow["display"] if b["region"] == "affected"]
    assert [(b["source"], b["targetTable"], b["keyColumn"], b["condition"]) for b in goods] == [
        ("T_COST_GOODS_PRICE_V", "T_COST_GOODS", "GOODSID", "GOODSID = :new_GOODSID")]
    assert goods[0]["actions"] == [{"action": "updateFields", "fields": [{"column": "ZX_PRICE", "value": ":new_PRICE"}]}]


def test_goods_to_cost_flow(flows_out: Path) -> None:
    flow = item(flows_out, "approvalFlow", "GOODS_TO_COST")
    parse_config_content("approvalFlow", flow)
    assert flow["page"] == "GOODS_PRICE_MANAGE"
    assert flow["operations"] == {"COST_GOODS_PRICE": ["modify"]}
    assert flow["freeze"] == [{"table": "T_COST_PINGGU_DTL", "condition": "GOODSID = :new_GOODSID"}]
    blocks = [b for b in flow["display"] if b["region"] == "affected"]
    assert [(b["source"], b["targetTable"], b["keyColumn"], b["selection"]) for b in blocks] == [
        ("V_COST_PINGGU_MATERIAL", "T_COST_PINGGU_DTL", "DTLID", "checked"),
        ("V_COST_PINGGU_PACKAGE", "T_COST_PINGGU_DTL", "DTLID", "checked")]
    assert blocks[0]["actions"] == [{"action": "updateFields", "fields": [{"column": "PRICE", "value": "NVL(:new_ZX_PRICE, :old_PRICE)"}]}]
    assert ("master.COST_PERBOX", "每盒成本") in [(c["field"], c["label"]) for c in blocks[0]["columns"]]
    goods = item(flows_out, "entity", "COST_GOODS_PRICE")
    assert goods["erpRow"] == {"column": "ISERP", "value": "1", "localValue": "0"}
    assert goods["approvalRequired"][0]["fields"] == ["ZX_PRICE"]


def test_tech_customer_flow(flows_out: Path) -> None:
    sample = _flow_samples()["TECH_CUSTOMER_MATERIAL"]
    flow = item(flows_out, "approvalFlow", "TECH_CUSTOMER_MATERIAL")
    parse_config_content("approvalFlow", flow)
    assert (flow["page"], flow["operations"]) == ("COST_PINGGU", sample["operations"])
    node = flow["levels"][0]["nodes"][0]
    assert (node["department"], node["condition"]) == ("1069", sample["levels"][0]["nodes"][0]["condition"])
    assert "freeze" not in flow


# ---------------------------------------------------------------- 清单（MG-02、MG-13）

def test_items_using_columns_not_copied_wait_for_confirmation(out: Path) -> None:
    found = entries(out)
    assert not (out / "config" / "export.cost-pinggu-export.json").exists()
    assert not (out / "config" / "role.003.json").exists()
    export = found["MR-cost-pinggu-export-master-SQL"]
    assert export["original"].endswith("WHERE m.DELETED = 0") and not export["proposal"].endswith("DELETED = 0")
    assert "CREATE_BY" not in found["MR-ROLE-123-COST_PINGGU-行权限"]["proposal"]
    assert "export:cost-pinggu-export" not in item(out, "role", "001")["pages"]["COST_PINGGU"]["buttons"]


def test_confirmed_rewrites_generate_the_withheld_items(tmp_path: Path) -> None:
    base = tmp_path / "base"
    generate_from_snapshot(SNAPSHOT, base)
    proposals = {e["id"]: e["proposal"] for e in entries(base).values() if e["id"] in (
        "MR-cost-pinggu-export-master-SQL", "MR-cost-pinggu-export-detail-material-SQL",
        "MR-cost-pinggu-export-detail-package-SQL", "MR-ROLE-123-COST_PINGGU-行权限")}
    confirmed = tmp_path / "confirmed"
    generate_from_snapshot(SNAPSHOT, confirmed, proposals)
    export = item(confirmed, "export", "cost-pinggu-export")
    assert "DELETED" not in export["master"]["sql"] and export["master"]["keyColumn"] == "DOCID"
    assert [d["linkColumn"] for d in export["details"]] == ["DOCID", "DOCID"]
    role = item(confirmed, "role", "003")
    assert "CREATE_BY" not in role["pages"]["COST_PINGGU"]["rows"]["sql"]
    assert "export:cost-pinggu-export" in item(confirmed, "role", "001")["pages"]["COST_PINGGU"]["buttons"]


def test_lists_cover_procedures_and_unconfirmed_flows(out: Path) -> None:
    found = entries(out)
    assert {e["id"] for e in found.values() if e["list"] == "escape"} == {
        "EH-COST_PINGGU-master:generateFromBom", "EH-COST_PINGGU-master:syncPrice",
        "EH-COST_PINGGU_LQ-master:generateFromBom", "EH-COST_PINGGU_LQ-master:syncPrice"}
    assert "MR-FLOW-71-入口条件" in found
    assert "MR-COST_PINGGU-masterGrid-SUMMARY_CONFIG" in found
