"""保存时规则读取的字段（C08 第 4 节 `ConfigSnapshot.rule_fields`，WP-08）：用成本核算的真实规则（公式与 cmx 虚拟列一致）。

用户 2026-10-29 选定：只有改到这些字段时，保存才读明细、求值；改备注这类字段直接写入，其他列不变。
"""

from __future__ import annotations

from cost_platform.config.catalog import Catalog
from cost_platform.config.packs import build_pack, pack_json
from cost_platform.config.rule_fields import name_chains, rule_fields

from .support import seed_drafts


def test_cost_pinggu_rule_fields() -> None:
    pack = pack_json(build_pack(Catalog({}).merged(seed_drafts()), "COST_PINGGU", 1, "0.1.0"))
    used = rule_fields(pack)
    # 主表：备注不被规则读取；每批数量、包装规格、外销价、汇率、得率、年需求量被读取
    assert "MEMO" not in used["COST_PINGGU"]
    assert {"APEX_PL", "P_PERPACK", "S_PERBACK", "X_PERBACK", "M_PERPACK", "OUT_PRICE_F", "FMRATE", "YIELD",
            "ANNUAL_QTY"} <= used["COST_PINGGU"]
    # 原辅料：每批用量的分支、金额 = 每批数量 × 单价，主表按用途汇总金额
    assert used["COST_MATERIAL"] == {"DTL_USEFLAG", "GOODSNAME", "PER_HL", "EXADD_MATER", "BATCH_QTY", "PRICE", "COST_BATCH"}
    assert used["COST_PACKAGE"] == used["COST_MATERIAL"]


def test_name_chains_skip_functions_strings_and_keywords() -> None:
    chains = name_chains("sum(map(filter(COST_MATERIAL, #.DTL_USEFLAG == '原料/辅料'), #.COST_BATCH)) > 0 "
                         "and matches(GOODSNAME, '桶|瓶') ? master.APEX_PL / 1000 : null")
    assert [".".join(c) for c in chains] == ["COST_MATERIAL", "#.DTL_USEFLAG", "#.COST_BATCH", "GOODSNAME", "master.APEX_PL"]
