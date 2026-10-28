"""公式转换（T-MG-2）：旧数据中出现的每种写法至少一个用例。

Oracle 虚拟列的完整表达式取自 cmx 快照（tests/migration/data/cmx-snapshot.json），其余用例是旧数据中写法的片段。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cost_platform.migration.expressions import Scope, Unconvertible, convert_legacy_calc, convert_oracle

SNAPSHOT = json.loads((Path(__file__).parent / "data" / "cmx-snapshot.json").read_text(encoding="utf-8"))


def virtual(table: str) -> dict[str, str]:
    return {r["COLUMN_NAME"]: r["DATA_DEFAULT"].strip() for r in SNAPSHOT["ALL_TAB_COLS"]
            if r["TABLE_NAME"] == table and r["VIRTUAL_COLUMN"] == "YES"}


MASTER_FIELDS = frozenset({
    "DOCID", "APEX_PL", "P_PERPACK", "S_PERBACK", "X_PERBACK", "M_PERPACK", "TOTAL_YL", "TOTAL_FL", "TOTAL_BC",
    "YIELD", "OUT_PRICE_F", "FMRATE", "COST_PERQP", "ANNUAL_QTY", "OUT_PRICE_RMB", "TOTAL_COST", "SALEMONEY",
    "JGF_BATCH", "COST_PERBOX", "JGF_PERQP", "ML_PERQP", "Y_JG_RE", "Y_ML", "Y_SALE"})
DETAIL_FIELDS = frozenset({"DTLID", "DOCID", "GOODSID", "GOODSNAME", "DTL_USEFLAG", "PER_HL", "EXADD_MATER", "PRICE",
                           "BATCH_QTY", "COST_BATCH"})
CODES = {"CostPinggu": "COST_PINGGU", "CostMaterial": "COST_MATERIAL", "CostPackage": "COST_PACKAGE"}


def master_scope() -> Scope:
    return Scope("COST_PINGGU", MASTER_FIELDS, details={"COST_MATERIAL": DETAIL_FIELDS, "COST_PACKAGE": DETAIL_FIELDS},
                 legacy_codes=CODES)


def detail_scope(entity: str = "COST_MATERIAL") -> Scope:
    return Scope(entity, DETAIL_FIELDS, master_entity="COST_PINGGU", master=MASTER_FIELDS, legacy_codes=CODES)


# ---------------------------------------------------------------- Oracle 虚拟列（MG-12）

def test_master_virtual_columns_reuse_other_virtual_columns() -> None:
    exprs = virtual("T_COST_PINGGU")
    got = {name: convert_oracle(text, name, master_scope(), exprs).expression for name, text in exprs.items()}
    assert got == {
        "OUT_PRICE_RMB": "OUT_PRICE_F * FMRATE",
        "TOTAL_COST": "TOTAL_YL + TOTAL_FL + TOTAL_BC",
        "SALEMONEY": "OUT_PRICE_RMB / P_PERPACK * APEX_PL * (YIELD / 100)",
        "JGF_BATCH": "SALEMONEY - TOTAL_COST",
        "COST_PERBOX": "TOTAL_COST / APEX_PL * P_PERPACK",
        "JGF_PERQP": "JGF_BATCH / APEX_PL * 1000",
        "ML_PERQP": "JGF_PERQP - COST_PERQP",
        "Y_JG_RE": "JGF_PERQP / 1000 * ANNUAL_QTY",
        "Y_ML": "ML_PERQP / 1000 * ANNUAL_QTY",
        "Y_SALE": "SALEMONEY / APEX_PL * ANNUAL_QTY",
    }


def test_detail_batch_qty_branches_use_master_and_keep_value_when_no_branch_matches() -> None:
    exprs = virtual("T_COST_PINGGU_DTL")
    scope = detail_scope()
    got = convert_oracle(exprs["BATCH_QTY"], "BATCH_QTY", scope, exprs)
    packs = "(DTL_USEFLAG == '非印字包材' or DTL_USEFLAG == '印字包材')"
    assert got.branches == [
        ("(DTL_USEFLAG == '原料' or DTL_USEFLAG == '辅料') and matches(GOODSNAME, '胶囊')",
         "master.APEX_PL / 10000 * (1 + EXADD_MATER / 100)"),
        ("DTL_USEFLAG == '原料' or DTL_USEFLAG == '辅料'",
         "PER_HL * master.APEX_PL * (1 + EXADD_MATER / 100) / 1000000"),
        (f"{packs} and matches(GOODSNAME, '桶|说明书|小盒|标签|瓶|盖|干燥剂|序列化')",
         "master.APEX_PL / master.P_PERPACK * (1 + EXADD_MATER / 100)"),
        (f"{packs} and matches(GOODSNAME, '硬片|铝箔|复合膜')",
         "PER_HL * master.APEX_PL * (1 + EXADD_MATER / 100) / 1000000"),
        (f"{packs} and matches(GOODSNAME, '大纸箱')",
         "ceil(master.APEX_PL / (master.P_PERPACK * master.S_PERBACK) * (1 + EXADD_MATER / 100))"),
        (f"{packs} and matches(GOODSNAME, '托盘')",
         "ceil(master.APEX_PL / (master.P_PERPACK * master.S_PERBACK * master.X_PERBACK) * (1 + EXADD_MATER / 100))"),
        (f"{packs} and matches(GOODSNAME, '中盒')",
         "ceil(master.APEX_PL / (master.M_PERPACK * master.S_PERBACK) * (1 + EXADD_MATER / 100))"),
    ]
    assert got.dropped_else == 'NVL("BATCH_QTY_OLD", 0)'
    assert scope.master_refs == {"APEX_PL", "P_PERPACK", "S_PERBACK", "X_PERBACK", "M_PERPACK"}


def test_detail_cost_batch_is_batch_qty_times_price() -> None:
    exprs = virtual("T_COST_PINGGU_DTL")
    assert convert_oracle(exprs["COST_BATCH"], "COST_BATCH", detail_scope(), exprs).expression == "BATCH_QTY * PRICE"


def test_division_without_outer_nvl_is_not_converted() -> None:
    with pytest.raises(Unconvertible):
        convert_oracle('NVL("APEX_PL",0)/CASE "P_PERPACK" WHEN 0 THEN NULL ELSE "P_PERPACK" END', "X", master_scope())


def test_nvl_with_non_zero_default_is_not_converted() -> None:
    with pytest.raises(Unconvertible):
        convert_oracle('NVL("APEX_PL",1)*2', "X", master_scope())


# ---------------------------------------------------------------- 旧前端 CALC

def test_sum_if_with_qualified_condition_and_ternary() -> None:
    rule = {"field": "TOTAL_BC", "expression": "SUM_IF('CostPackage.COST_BATCH', \"CostPackage.DTL_USEFLAG == '印字包材' || "
            "CostPackage.DTL_USEFLAG == '非印字包材'\") * (SUM_IF('CostMaterial.COST_BATCH', \"CostMaterial.DTL_USEFLAG == '原料'\") > 0 ? 1 / 1.13 : 1)"}
    assert convert_legacy_calc(rule, master_scope()).expression == (
        "sum(map(filter(COST_PACKAGE, #.DTL_USEFLAG == '印字包材' or #.DTL_USEFLAG == '非印字包材'), #.COST_BATCH)) * "
        "(sum(map(filter(COST_MATERIAL, #.DTL_USEFLAG == '原料'), #.COST_BATCH)) > 0 ? 1 / 1.13 : 1)")


def test_sum_if_with_unqualified_condition() -> None:
    rule = {"field": "TOTAL_FL", "expression": "SUM_IF('CostMaterial.COST_BATCH', \"DTL_USEFLAG == '辅料'\")"}
    assert convert_legacy_calc(rule, master_scope()).expression == \
        "sum(map(filter(COST_MATERIAL, #.DTL_USEFLAG == '辅料'), #.COST_BATCH))"


def test_master_field_arithmetic() -> None:
    rule = {"field": "Y_SALE", "expression": "CostPinggu.ANNUAL_QTY*CostPinggu.OUT_PRICE_RMB*(CostPinggu.YIELD/100)"}
    assert convert_legacy_calc(rule, master_scope()).expression == "ANNUAL_QTY * OUT_PRICE_RMB * (YIELD / 100)"


def test_detail_formula_branches_by_regex() -> None:
    rule = {"field": "BATCH_QTY", "formulaField": "CostPackage.GOODSNAME", "formulas": {
        "__branch_1": {"key": "托盘", "matchType": "regex",
                       "expression": "ceil(CostPinggu.APEX_PL / (CostPinggu.S_PERBACK * CostPinggu.X_PERBACK) * (1 + CostPackage.EXADD_MATER / 100))"},
        "__branch_0": {"key": "桶|说明书", "matchType": "regex", "expression": "CostPinggu.APEX_PL * (1 + CostPackage.EXADD_MATER / 100)"}}}
    assert convert_legacy_calc(rule, detail_scope("COST_PACKAGE")).branches == [
        ("matches(GOODSNAME, '桶|说明书')", "master.APEX_PL * (1 + EXADD_MATER / 100)"),
        ("matches(GOODSNAME, '托盘')", "ceil(master.APEX_PL / (master.S_PERBACK * master.X_PERBACK) * (1 + EXADD_MATER / 100))"),
    ]


def test_null_checks_and_single_ampersand() -> None:
    scope = Scope("COST_PACKAGE_LQ", frozenset({"SOURCE_BATCH_QTY", "EXADD_MATER"}), master_entity="COST_PINGGU_LQ",
                  master=frozenset({"APEX_PL"}), legacy_codes={"CostPackageLq": "COST_PACKAGE_LQ", "CostPingguLq": "COST_PINGGU_LQ"})
    rule = {"field": "BATCH_QTY", "expression": "CostPackageLq.SOURCE_BATCH_QTY != null & CostPackageLq.SOURCE_BATCH_QTY != 0 ? "
            "CostPackageLq.SOURCE_BATCH_QTY : CostPingguLq.APEX_PL * (1 + CostPackageLq.EXADD_MATER / 100)"}
    assert convert_legacy_calc(rule, scope).expression == (
        "SOURCE_BATCH_QTY != null and SOURCE_BATCH_QTY != 0 ? SOURCE_BATCH_QTY : master.APEX_PL * (1 + EXADD_MATER / 100)")


def test_field_not_in_entity_is_not_converted() -> None:
    rule = {"field": "PER_HL", "expression": "CostMaterial.SOURCE_BATCH_QTY == null || CostMaterial.SOURCE_BATCH_QTY == 0 ? "
            "CostMaterial.PER_HL : CostMaterial.SOURCE_BATCH_QTY / CostPinggu.APEX_PL * 1000000"}
    with pytest.raises(Unconvertible, match="SOURCE_BATCH_QTY"):
        convert_legacy_calc(rule, detail_scope())


def test_regex_lookahead_is_not_converted() -> None:
    rule = {"field": "BATCH_QTY", "formulaField": "CostMaterial.GOODSNAME", "formulas": {
        "__branch_0": {"key": "^(?!.*胶囊).*$", "matchType": "regex", "expression": "CostMaterial.PER_HL"}}}
    with pytest.raises(Unconvertible, match="断言"):
        convert_legacy_calc(rule, detail_scope())
