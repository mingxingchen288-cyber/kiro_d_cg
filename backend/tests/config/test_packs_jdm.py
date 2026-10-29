"""规则包的 JDM 写法（CF-11）：与 rules-core 样例集的生成脚本（rules-core/fixtures/gen_packs.py）逐个相同，不需要 wheel。"""

from __future__ import annotations

from cost_platform.config.catalog import Catalog
from cost_platform.config.packs import build_pack
from cost_platform.contracts.types import JdmGraph, dump_wire

from .support import cost_rule_drafts, gen_packs, seed_drafts


def test_calc_jdm_matches_gen_packs() -> None:
    """计算规则的 JDM：输入 → 表达式 → 输出，表达式的 key 是作用的字段；branches 编成一个条件表达式。"""
    module = gen_packs()
    pack = build_pack(Catalog({}).merged([*seed_drafts(), *cost_rule_drafts()]), "COST_PINGGU", 1, "0.1.0")
    calc = [r for r in module.COST_RULES if r.get("category", "calc") == "calc"]
    assert sorted(r.id for r in pack.rules) == sorted(r["id"] for r in calc)
    for rule in calc:
        expected = module.jdm(rule["id"], rule["field"], module.calc_expression(rule))
        assert dump_wire(JdmGraph, pack.jdm[rule["id"]]) == expected, rule["id"]
    entities = {r.id: r.entity for r in pack.rules}
    assert entities["R_MAT_BATCH_QTY"] == "COST_MATERIAL" and entities["R_MASTER_TOTAL_COST"] == "COST_PINGGU"
    assert set(pack.fields) == {"COST_PINGGU", "COST_MATERIAL", "COST_PACKAGE"}
    assert all(not r.server_only and r.layer == "entity" for r in pack.rules)
