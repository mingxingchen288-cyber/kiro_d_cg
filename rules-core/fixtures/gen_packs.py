"""生成样例集用的规则包（C07 第 1 节）。

规则按 C06 第 5 节的写法给出（field、expression 或 branches、when），按 rules-core 的 JDM 约定（README 第 2 节）
转成 JDM：输入 → 表达式（一个表达式，key 为作用的字段）→ 输出。
- 只有 expression：值为表达式；
- 有 when：`(when) ? (expression) : 字段`，不成立时字段不变；
- branches：按顺序取第一个 when 成立的分支，`(w1) ? (e1) : ((w2) ? (e2) : 字段)`，都不成立时字段不变。
"""

from __future__ import annotations

from typing import Any


def calc_expression(rule: dict[str, Any]) -> str:
    field = rule["field"]
    if "branches" in rule:
        text = field
        for branch in reversed(rule["branches"]):
            when = branch.get("when")
            text = f"({branch['expression']})" if when is None else f"({when}) ? ({branch['expression']}) : ({text})"
        return text
    if rule.get("when"):
        return f"({rule['when']}) ? ({rule['expression']}) : ({field})"
    return rule["expression"]


def jdm(name: str, key: str, value: str) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "in", "name": "输入", "type": "inputNode", "content": {}},
            {"id": "expr", "name": name, "type": "expressionNode",
             "content": {"expressions": [{"id": "e1", "key": key, "value": value}]}},
            {"id": "out", "name": "输出", "type": "outputNode", "content": {}},
        ],
        "edges": [
            {"id": "e-in", "sourceId": "in", "targetId": "expr"},
            {"id": "e-out", "sourceId": "expr", "targetId": "out"},
        ],
    }


def pack(pack_id: str, version: int, fields: dict[str, dict[str, Any]], rules: list[dict[str, Any]]) -> dict[str, Any]:
    out_rules, graphs = [], {}
    for r in rules:
        entry = {"id": r["id"], "layer": r.get("layer", "entity")}
        for key in ("entity", "operation", "page"):
            if key in r:
                entry[key] = r[key]
        entry.update({"category": r.get("category", "calc"), "order": r["order"], "serverOnly": r.get("serverOnly", False), "jdm": r["id"]})
        out_rules.append(entry)
        if entry["category"] == "calc":
            graphs[r["id"]] = jdm(r["id"], r["field"], calc_expression(r))
        else:
            # validate、ui 以后实现；先给出条件表达式，load_pack 照常检查和编译
            graphs[r["id"]] = jdm(r["id"], "matched", r["when"])
    return {"packId": pack_id, "version": version, "coreVersion": "0.1.0", "fields": fields,
            "rules": out_rules, "jdm": graphs}


def num(role: str = "input", scale: int | None = None) -> dict[str, Any]:
    f: dict[str, Any] = {"type": "number", "role": role, "source": "own"}
    if scale is not None:
        f["scale"] = scale
    return f


def text(source: str = "own") -> dict[str, Any]:
    return {"type": "text", "role": "input", "source": source}


# ---------------------------------------------------------------- 成本核算（公式与 cmx 虚拟列一致，.reports/virtual-columns/findings.md）

RAW = "(DTL_USEFLAG == '原料' or DTL_USEFLAG == '辅料')"
PKG = "(DTL_USEFLAG == '印字包材' or DTL_USEFLAG == '非印字包材')"
EX = "(1 + EXADD_MATER / 100)"
BATCH_QTY_BRANCHES = [
    {"when": f"{RAW} and matches(GOODSNAME, '胶囊')", "expression": f"master.APEX_PL / 10000 * {EX}"},
    {"when": RAW, "expression": f"PER_HL * master.APEX_PL * {EX} / 1000000"},
    {"when": f"{PKG} and matches(GOODSNAME, '桶|说明书|小盒|标签|瓶|盖|干燥剂|序列化')", "expression": f"master.APEX_PL / master.P_PERPACK * {EX}"},
    {"when": f"{PKG} and matches(GOODSNAME, '硬片|铝箔|复合膜')", "expression": f"PER_HL * master.APEX_PL * {EX} / 1000000"},
    {"when": f"{PKG} and matches(GOODSNAME, '大纸箱')", "expression": f"ceil(master.APEX_PL / (master.P_PERPACK * master.S_PERBACK) * {EX})"},
    {"when": f"{PKG} and matches(GOODSNAME, '托盘')", "expression": f"ceil(master.APEX_PL / (master.P_PERPACK * master.S_PERBACK * master.X_PERBACK) * {EX})"},
    {"when": f"{PKG} and matches(GOODSNAME, '中盒')", "expression": f"ceil(master.APEX_PL / (master.M_PERPACK * master.S_PERBACK) * {EX})"},
]


def _sum(entity: str, flags: list[str]) -> str:
    cond = " or ".join(f"#.DTL_USEFLAG == '{f}'" for f in flags)
    return f"sum(map(filter({entity}, {cond}), #.COST_BATCH))"


YL = _sum("COST_MATERIAL", ["原料"])
FACTOR = f"({YL} > 0 ? 1 / 1.13 : 1)"

DETAIL_FIELDS = {
    "DTLID": num("system", 0), "DOCID": num("system", 0), "GOODSID": num("input", 0), "GOODSNAME": text("erp"),
    "DTL_USEFLAG": text("erp"), "PER_HL": num(), "EXADD_MATER": num(), "PRICE": num("input", 4),
    "BATCH_QTY": num("calculated", 4), "COST_BATCH": num("calculated", 2),
}
MASTER_INPUTS = ["APEX_PL", "P_PERPACK", "S_PERBACK", "X_PERBACK", "M_PERPACK", "OUT_PRICE_F", "FMRATE", "YIELD", "COST_PERQP", "ANNUAL_QTY"]
MASTER_CALCULATED = ["TOTAL_YL", "TOTAL_FL", "TOTAL_BC", "TOTAL_COST", "OUT_PRICE_RMB", "SALEMONEY", "JGF_BATCH",
                     "COST_PERBOX", "JGF_PERQP", "ML_PERQP", "Y_JG_RE", "Y_ML", "Y_SALE"]
MASTER_FIELDS = {"DOCID": num("system", 0), "GOODSNAME": text("erp"), "MEMO": text(),
                 **{f: num() for f in MASTER_INPUTS}, **{f: num("calculated", 4) for f in MASTER_CALCULATED}}

# order 故意与依赖顺序相反，检查 load_pack 按依赖排序（C06 第 5 节执行顺序 1）
COST_RULES: list[dict[str, Any]] = [
    {"id": "R_MASTER_Y_SALE", "entity": "COST_PINGGU", "field": "Y_SALE", "order": 1, "expression": "SALEMONEY / APEX_PL * ANNUAL_QTY"},
    {"id": "R_MASTER_Y_ML", "entity": "COST_PINGGU", "field": "Y_ML", "order": 2, "expression": "ML_PERQP / 1000 * ANNUAL_QTY"},
    {"id": "R_MASTER_Y_JG_RE", "entity": "COST_PINGGU", "field": "Y_JG_RE", "order": 3, "expression": "JGF_PERQP / 1000 * ANNUAL_QTY"},
    {"id": "R_MASTER_ML_PERQP", "entity": "COST_PINGGU", "field": "ML_PERQP", "order": 4, "expression": "JGF_PERQP - COST_PERQP"},
    {"id": "R_MASTER_JGF_PERQP", "entity": "COST_PINGGU", "field": "JGF_PERQP", "order": 5, "expression": "JGF_BATCH / APEX_PL * 1000"},
    {"id": "R_MASTER_COST_PERBOX", "entity": "COST_PINGGU", "field": "COST_PERBOX", "order": 6, "expression": "TOTAL_COST / APEX_PL * P_PERPACK"},
    {"id": "R_MASTER_JGF_BATCH", "entity": "COST_PINGGU", "field": "JGF_BATCH", "order": 7, "expression": "SALEMONEY - TOTAL_COST"},
    {"id": "R_MASTER_SALEMONEY", "entity": "COST_PINGGU", "field": "SALEMONEY", "order": 8, "expression": "OUT_PRICE_RMB / P_PERPACK * APEX_PL * (YIELD / 100)"},
    {"id": "R_MASTER_OUT_PRICE_RMB", "entity": "COST_PINGGU", "field": "OUT_PRICE_RMB", "order": 9, "expression": "OUT_PRICE_F * FMRATE"},
    {"id": "R_MASTER_TOTAL_COST", "entity": "COST_PINGGU", "field": "TOTAL_COST", "order": 10, "expression": "TOTAL_YL + TOTAL_FL + TOTAL_BC"},
    {"id": "R_MASTER_TOTAL_BC", "entity": "COST_PINGGU", "field": "TOTAL_BC", "order": 11,
     "expression": f"{_sum('COST_PACKAGE', ['印字包材', '非印字包材'])} * {FACTOR}"},
    {"id": "R_MASTER_TOTAL_FL", "entity": "COST_PINGGU", "field": "TOTAL_FL", "order": 12, "expression": f"{_sum('COST_MATERIAL', ['辅料'])} * {FACTOR}"},
    {"id": "R_MASTER_TOTAL_YL", "entity": "COST_PINGGU", "field": "TOTAL_YL", "order": 13, "expression": f"{YL} * {FACTOR}"},
    {"id": "R_MAT_COST_BATCH", "entity": "COST_MATERIAL", "field": "COST_BATCH", "order": 14, "expression": "BATCH_QTY * PRICE"},
    {"id": "R_MAT_BATCH_QTY", "entity": "COST_MATERIAL", "field": "BATCH_QTY", "order": 15, "branches": BATCH_QTY_BRANCHES},
    {"id": "R_PKG_COST_BATCH", "entity": "COST_PACKAGE", "field": "COST_BATCH", "order": 16, "expression": "BATCH_QTY * PRICE"},
    {"id": "R_PKG_BATCH_QTY", "entity": "COST_PACKAGE", "field": "BATCH_QTY", "order": 17, "branches": BATCH_QTY_BRANCHES},
    # 以下两类以后实现：求值时没有提示、没有效果
    {"id": "R_V_PRICE", "entity": "COST_MATERIAL", "category": "validate", "order": 100, "when": "PRICE < 0"},
    {"id": "R_UI_ERP", "layer": "page", "page": "COST_PINGGU", "category": "ui", "order": 200, "when": "DTL_USEFLAG == '原料'"},
]


def cost_pack() -> dict[str, Any]:
    fields = {"COST_PINGGU": MASTER_FIELDS, "COST_MATERIAL": DETAIL_FIELDS, "COST_PACKAGE": DETAIL_FIELDS}
    return pack("COST_PINGGU", 1, fields, COST_RULES)


# ---------------------------------------------------------------- 单表演示：精度、old、preview/commit、serverOnly、E04

DEMO_FIELDS = {"DEMO_ORDER": {
    "ID": num("system", 0), "QTY": num(), "PRICE": num("input", 8), "AMOUNT": num("calculated", 8),
    "THIRD": num("calculated", 8), "BACK": num("calculated", 8), "PRICE_DELTA": num("calculated", 8),
    "QTY_DELTA": num("calculated", 8), "NET": num("calculated", 8),
}}
DEMO_RULES: list[dict[str, Any]] = [
    {"id": "R_BACK", "entity": "DEMO_ORDER", "field": "BACK", "order": 10, "expression": "THIRD * 3"},
    {"id": "R_THIRD", "entity": "DEMO_ORDER", "field": "THIRD", "order": 20, "expression": "QTY / 3"},
    {"id": "R_AMOUNT", "entity": "DEMO_ORDER", "field": "AMOUNT", "order": 30, "expression": "QTY * PRICE"},
    {"id": "R_PRICE_DELTA", "entity": "DEMO_ORDER", "field": "PRICE_DELTA", "order": 40, "expression": "PRICE - old.PRICE"},
    {"id": "R_QTY_DELTA", "entity": "DEMO_ORDER", "field": "QTY_DELTA", "order": 41, "expression": "QTY - old.QTY"},
    {"id": "R_NET", "layer": "operation", "operation": "DEMO_ORDER.save", "entity": "DEMO_ORDER", "field": "NET", "order": 50,
     "serverOnly": True, "expression": "AMOUNT * (1 - data.discountRate)"},
]


def demo_pack() -> dict[str, Any]:
    return pack("DEMO_ORDER", 1, DEMO_FIELDS, DEMO_RULES)


# ---------------------------------------------------------------- T-RC-1：一条表达式规则

EXPR_FIELDS = {"EXPR_DEMO": {"ID": num("system", 0), "A": num(), "B": num(), "SUM": num("calculated"), "QUOT": num("calculated")}}
EXPR_RULES = [
    {"id": "R_SUM", "entity": "EXPR_DEMO", "field": "SUM", "order": 10, "expression": "A + B"},
    {"id": "R_QUOT", "entity": "EXPR_DEMO", "field": "QUOT", "order": 20, "expression": "A / B"},
]


def expr_pack() -> dict[str, Any]:
    return pack("EXPR_DEMO", 1, EXPR_FIELDS, EXPR_RULES)


# ---------------------------------------------------------------- 跨实体依赖成环：主表汇总明细 X，明细 X 又引用主表汇总

def cycle_pack() -> dict[str, Any]:
    fields = {"CYC": {"ID": num("system", 0), "SUM_X": num("calculated")},
              "CYC_DTL": {"DTLID": num("system", 0), "X": num("calculated"), "Y": num()}}
    rules = [
        {"id": "R_SUM_X", "entity": "CYC", "field": "SUM_X", "order": 10, "expression": "sum(map(CYC_DTL, #.X))"},
        {"id": "R_X", "entity": "CYC_DTL", "field": "X", "order": 20, "expression": "master.SUM_X + Y"},
    ]
    return pack("CYC", 1, fields, rules)
