"""规则包生成（CF-11、C07 第 1 节，T-CF-2）：C06 第 5 节的规则转成 JDM，用 rules-core 的真实 wheel 编译并求值。

运行：`uv run --with ..\\rules-core\\dist\\python\\cost_rules_core-0.1.0-cp313-cp313-win_amd64.whl pytest tests/config/test_packs.py`。
没有装 wheel 时整个文件跳过（与 tests/rules_core 相同）；JDM 写法的比较不需要 wheel，在 test_packs_jdm.py。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from cost_platform.config.catalog import Catalog
from cost_platform.config.packs import build_pack, pack_bytes, pack_json
from cost_platform.contracts.types import ErrorCode, PlatformError

from .support import ROOT, Env, doc_json, draft, goods_price_items, seed_drafts, seed_without_rules

CASES = ROOT / "rules-core" / "fixtures" / "cases"


def _case(name: str) -> dict[str, Any]:
    path = next(p for p in CASES.glob("*.json") if name in p.name)
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


cost_rules_core = pytest.importorskip("cost_rules_core", reason="需要 rules-core 的 wheel：uv run --with <wheel> pytest tests/config")
from cost_rules_core import RulesEngine  # noqa: E402

ENGINE = RulesEngine()


@pytest.mark.parametrize("prefix", ["09-", "17-", "18-", "21-", "22-", "23-", "24-", "30-", "31-", "32-", "33-"])
def test_seed_cost_rules_compile_and_compute_case(prefix: str) -> None:
    """backend/seed/config 的成本核算配置（17 条计算规则、两条校验、整行红底）生成的规则包能 load_pack，与样例集的规则包
    算出相同结果：样例 09（cmx 单据 200726）；17、18（d_cg 单据 2919 的两条校验拒绝和整行红底，preview 和 commit）；
    21–24（d_cg 单据 2757：校验只检查本次修改的行，改另一行的单价不拒绝，改每片含量为 0 那一行的单价拒绝，C07 v5）；
    30–33（改主表批量，计算带出变化的行也校验，C07 v7：2712 胶囊每片含量假设为 0 被拒绝，2757 能保存）。"""
    item = _case(prefix)
    pack = build_pack(Catalog({}).merged(seed_drafts()), "COST_PINGGU", 1, ENGINE.core_version())
    handle = ENGINE.load_pack(pack_bytes(pack))
    result = ENGINE.evaluate(handle, json.dumps(item["request"], ensure_ascii=False))
    assert cost_rules_core.compare_json(result, json.dumps(item["expected"], ensure_ascii=False)) == []


def test_saved_pack_is_served_by_snapshot() -> None:
    """经保存流程生成、存进 PF_CONFIG_ITEM 的规则包，配置快照的 rules_pack 返回编译好的句柄，计算结果同样例 09。"""
    env = Env(engine=ENGINE)
    env.save(seed_drafts())
    stored = env.stored("rulesPack", "COST_PINGGU")
    assert stored is not None and stored["coreVersion"] == ENGINE.core_version()
    snapshot = env.reader.read("ADMIN")
    assert snapshot.page_view("COST_PINGGU").rules_pack.version == stored["version"]
    item = _case("09-")
    result = ENGINE.evaluate(snapshot.rules_pack("COST_PINGGU"), json.dumps(item["request"], ensure_ascii=False))
    assert cost_rules_core.compare_json(result, json.dumps(item["expected"], ensure_ascii=False)) == []


def _e02_request() -> dict[str, Any]:
    """E02：包材明细物料名含"瓶"，APEX_PL=100000，P_PERPACK=100，EXADD_MATER=2；含"铝箔"，PER_HL=50，其余相同。"""
    context = {"userId": "1", "departmentId": "10", "role": "ADMIN", "today": "2026-10-29", "origin": "user"}
    rows = [{"rowKey": "1", "values": {"GOODSNAME": "瓶", "EXADD_MATER": "2", "PER_HL": None}},
            {"rowKey": "2", "values": {"GOODSNAME": "铝箔", "EXADD_MATER": "2", "PER_HL": "50"}}]
    return {"purpose": "operation", "operation": "COST_PINGGU.save", "page": "COST_PINGGU", "phase": "commit", "context": context,
            "document": {"entity": "COST_PINGGU", "master": {"rowKey": "9", "values": {"APEX_PL": "100000", "P_PERPACK": "100"}},
                         "details": {"COST_PACKAGE": rows}}, "changed": [], "data": {}}


def test_c06_calc_rule_sample_e02() -> None:
    """C06 第 5 节的计算规则（包材批量按物料名称分两种算法）：E02 的两行分别算出 1020 和 5.1。"""
    catalog = Catalog({}).merged([*seed_without_rules(), draft("rule", "R_PKG_BATCH_QTY", doc_json("C06", 4))])
    handle = ENGINE.load_pack(pack_bytes(build_pack(catalog, "COST_PINGGU", 1, ENGINE.core_version())))
    result = json.loads(ENGINE.evaluate(handle, json.dumps(_e02_request(), ensure_ascii=False)))
    assert result["ok"] is True
    batch = {r["rowKey"]: r["computed"]["BATCH_QTY"] for r in result["rows"] if r["entity"] == "COST_PACKAGE"}
    assert batch == {"1": "1020", "2": "5.1"}


def test_c06_ui_rule_sample_whole_row() -> None:
    """C06 第 5 节的界面规则（ERP 来的物料整行不能编辑，field 为空）编进物料管理页的规则包：preview 时 ERP 行的每个字段
    都不可编辑，自建的行不受影响。"""
    items = goods_price_items()
    page = next(d for d in items if d.type == "page")
    catalog = Catalog({}).merged([*items, draft("page", "GOODS_MANAGE", {**page.content, "title": "物料管理"}),
                                  draft("rule", "R_GOODS_ERP_LOCK", doc_json("C06", 5))])
    pack = build_pack(catalog, "COST_GOODS_PRICE", 1, ENGINE.core_version())
    handle = ENGINE.load_pack(pack_bytes(pack))
    rule = next(r for r in pack.rules if r.id == "R_GOODS_ERP_LOCK")
    assert (rule.layer, rule.page, rule.entity, rule.category) == ("page", "GOODS_MANAGE", "COST_GOODS_PRICE", "ui")
    expressions = pack_json(pack)["jdm"]["R_GOODS_ERP_LOCK"]["nodes"][1]["content"]["expressions"]
    assert [(e["key"], e["value"]) for e in expressions] == [("matched", "(ISERP == 1)"), ("editable", "false")]
    context = {"userId": "1", "departmentId": "10", "role": "ADMIN", "today": "2026-10-30", "origin": "user"}
    fields = [f.name for f in Catalog({}).merged(items).entity("COST_GOODS_PRICE").fields]
    for iserp, locked in (("1", True), ("0", False)):
        request = {"purpose": "operation", "page": "GOODS_MANAGE", "phase": "preview", "context": context,
                   "document": {"entity": "COST_GOODS_PRICE", "master": {"rowKey": "115", "values": {"GOODSID": "115", "ISERP": iserp}},
                                "details": {}}, "changed": [], "data": {}}
        row = json.loads(ENGINE.evaluate(handle, json.dumps(request, ensure_ascii=False)))["rows"][0]
        assert row["fields"] == ({f: {"editable": False} for f in fields} if locked else {})


def test_dependency_cycle_rejects_save() -> None:
    """计算规则的依赖成环（跨实体）时保存被拒绝，错误中列出环上的规则（C06 第 5 节执行顺序 4、RC-09）。"""
    env = Env(engine=ENGINE)
    env.save(seed_without_rules())
    rules = [draft("rule", "R_SUM", {"layer": "entity", "target": "COST_PINGGU", "category": "calc", "field": "TOTAL_COST",
                                     "order": 1, "expression": "sum(map(COST_MATERIAL, #.COST_BATCH))"}),
             draft("rule", "R_BATCH", {"layer": "entity", "target": "COST_MATERIAL", "category": "calc", "field": "COST_BATCH",
                                       "order": 2, "expression": "master.TOTAL_COST + PRICE"})]
    generation = env.generation()
    with pytest.raises(PlatformError) as caught:
        env.save(rules)
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    message = " ".join(d.message or "" for d in caught.value.details)
    assert "依赖成环" in message and "R_SUM" in message and "R_BATCH" in message
    assert env.generation() == generation and env.stored("rule", "R_SUM") is None
