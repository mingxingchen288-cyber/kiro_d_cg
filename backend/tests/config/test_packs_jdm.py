"""规则包的 JDM 写法（CF-11）：与 rules-core 样例集的生成脚本（rules-core/fixtures/gen_packs.py）逐个相同，不需要 wheel。"""

from __future__ import annotations

from cost_platform.config.catalog import Catalog
from cost_platform.config.packs import build_pack
from cost_platform.contracts.types import JdmGraph, dump_wire

from .support import gen_packs, seed_drafts


def test_calc_jdm_matches_gen_packs() -> None:
    """seed 的计算规则的 JDM：输入 → 表达式 → 输出，表达式的 key 是作用的字段；branches 编成一个条件表达式。"""
    module = gen_packs()
    pack = build_pack(Catalog({}).merged(seed_drafts()), "COST_PINGGU", 1, "0.1.0")
    calc = [r for r in module.COST_RULES if r.get("category", "calc") == "calc"]
    for rule in calc:
        expected = module.jdm(rule["id"], rule["field"], module.calc_expression(rule))
        assert dump_wire(JdmGraph, pack.jdm[rule["id"]]) == expected, rule["id"]
    entities = {r.id: r.entity for r in pack.rules}
    assert entities["R_MAT_BATCH_QTY"] == "COST_MATERIAL" and entities["R_MASTER_TOTAL_COST"] == "COST_PINGGU"
    assert set(pack.fields) == {"COST_PINGGU", "COST_MATERIAL", "COST_PACKAGE"}
    assert all(not r.server_only and r.layer == "entity" for r in pack.rules if r.category == "calc")


def test_check_jdm_matches_gen_packs() -> None:
    """seed 的校验、界面规则（旧系统成本核算的两条校验和整行红底）：JDM 为 matched、field 和 level、message，
    或 effect 的各项；可视化条件编成 `(MEMO == 'ERP未搭建BOM')`。与样例集用的规则包相同，规则包里没有别的规则。"""
    module = gen_packs()
    pack = build_pack(Catalog({}).merged(seed_drafts()), "COST_PINGGU", 1, "0.1.0")
    assert sorted(r.id for r in pack.rules) == sorted(r["id"] for r in module.COST_RULES)
    rules = {r.id: r for r in pack.rules}
    for rule in (r for r in module.COST_RULES if r.get("category", "calc") != "calc"):
        assert dump_wire(JdmGraph, pack.jdm[rule["id"]]) == module.jdm_items(rule["id"], module.check_items(rule)), rule["id"]
        got = rules[rule["id"]]
        assert (got.layer, got.entity, got.page, got.category, got.order) == (
            rule.get("layer", "entity"), rule["entity"], rule.get("page"), rule["category"], rule["order"])
