"""生成样例集用的规则包（C07 第 1 节）。

规则按 C06 第 5 节的写法给出（field、expression 或 branches、when），按 rules-core 的 JDM 约定（README 第 2 节）
转成 JDM：输入 → 表达式 → 输出。计算规则的表达式节点只有一个表达式，key 为作用的字段：
- 只有 expression：值为表达式；
- 有 when：`(when) ? (expression) : 字段`，不成立时字段不变；
- branches：按顺序取第一个 when 成立的分支，`(w1) ? (e1) : ((w2) ? (e2) : 字段)`，都不成立时字段不变。
校验、界面规则的写法见 `check_items`。
"""

from __future__ import annotations

import json
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
    return jdm_items(name, [(key, value)])


def jdm_items(name: str, items: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "in", "name": "输入", "type": "inputNode", "content": {}},
            {"id": "expr", "name": name, "type": "expressionNode",
             "content": {"expressions": [{"id": f"e{i + 1}", "key": k, "value": v} for i, (k, v) in enumerate(items)]}},
            {"id": "out", "name": "输出", "type": "outputNode", "content": {}},
        ],
        "edges": [
            {"id": "e-in", "sourceId": "in", "targetId": "expr"},
            {"id": "e-out", "sourceId": "expr", "targetId": "out"},
        ],
    }


def lit(text: str) -> str:
    """ZEN 的字符串常量：没有转义，到下一个同样的引号为止；含单引号时用双引号。"""
    return f'"{text}"' if "'" in text else f"'{text}'"


def check_items(rule: dict[str, Any]) -> list[tuple[str, str]]:
    """校验、界面规则的 JDM 表达式（与 config `packs.py` 相同）：matched（条件）、field（作用的字段，整行时没有），
    校验另有 level、message；界面另有 effect 中写了的 editable、required、rowStyle、cellStyle（样式 JSON 文本）。"""
    items = [("matched", rule.get("when") or "true")]
    if rule.get("field"):
        items.append(("field", lit(rule["field"])))
    if rule["category"] == "validate":
        return items + [("level", lit(rule.get("level", "reject"))), ("message", lit(rule.get("message", "")))]
    effect = rule.get("effect", {})
    for key in ("editable", "required"):
        if key in effect:
            items.append((key, "true" if effect[key] else "false"))
    for key in ("rowStyle", "cellStyle"):
        if key in effect:
            items.append((key, lit(json.dumps(effect[key], ensure_ascii=False, separators=(",", ":")))))
    return items


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
            graphs[r["id"]] = jdm_items(r["id"], check_items(r))
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
    # 旧系统成本核算 material 的 VALIDATION（失败时不保存 → reject，提示文字照旧配置）和 masterGrid 的 GRID_STYLE
    # （.reports/editable-20261029/01-旧页面规则.out.txt）；与 backend/seed/config/rule.<编码>.json 相同
    {"id": "R_MAT_PER_HL_GT0", "entity": "COST_MATERIAL", "category": "validate", "field": "PER_HL", "order": 100,
     "when": "PER_HL <= 0", "level": "reject", "message": "每片含量必填且必须大于0"},
    {"id": "R_MAT_PRICE_GE0", "entity": "COST_MATERIAL", "category": "validate", "field": "PRICE", "order": 101,
     "when": "PRICE < 0", "level": "reject", "message": "单价必填且不能为负数"},
    {"id": "R_MASTER_NO_BOM_RED", "layer": "page", "page": "COST_PINGGU", "entity": "COST_PINGGU", "category": "ui", "order": 200,
     "when": "(MEMO == 'ERP未搭建BOM')", "effect": {"rowStyle": {"backgroundColor": "#ffcccc"}}},
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
    # 界面规则（只在 preview 执行）：整行不可编辑（C06 第 5 节的例子，field 为空），单价必填并改字体颜色（假设的规则）
    {"id": "R_UI_ROW_LOCK", "layer": "page", "page": "DEMO_ORDER", "entity": "DEMO_ORDER", "category": "ui", "order": 300,
     "when": "QTY >= 100", "effect": {"editable": False}},
    {"id": "R_UI_PRICE_REQUIRED", "layer": "page", "page": "DEMO_ORDER", "entity": "DEMO_ORDER", "category": "ui", "field": "PRICE",
     "order": 301, "when": "QTY >= 100", "effect": {"required": True, "cellStyle": {"color": "#999999"}}},
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


# ---------------------------------------------------------------- T-RC-3：模块说明第 8 节的数值处理规则表，每一行至少一条规则

NUM_CALCULATED = ["NULL_ADD", "DIV0", "ZERO_ZERO", "OVER", "BAD", "COND", "KEEP", "THIRD", "SUM_V", "SUM_E", "COUNT_E", "AVG_E", "MAX_E", "MIN_E"]
NUM_FIELDS = {
    "NUM_DEMO": {"ID": num("system", 0), "A": num(), "Z": num(), "E": num(), "BIG": num(), "S": text(), "NAME": text(),
                 **{f: num("calculated") for f in NUM_CALCULATED}},
    "NUM_DTL": {"DTLID": num("system", 0), "V": num()},
    "NUM_EMPTY": {"DTLID": num("system", 0), "V": num()},
}
NUM_EXPRESSIONS = [
    ("NULL_ADD", "E + NOFIELD + 1"),          # 字段为空（E）、行中没有这个字段（NOFIELD）：按 0
    ("DIV0", "A / Z"),                         # 除以 0
    ("ZERO_ZERO", "Z / Z"),                    # 0/0
    ("OVER", "BIG * 10"),                      # 溢出：超出 28 位有效数字
    ("BAD", "S * 2"),                          # 计算规则求值出错：文本乘数值
    ("THIRD", "A / 3"),                        # 不舍入
    ("SUM_V", "sum(map(NUM_DTL, #.V))"),       # 汇总时某行的字段为空
    ("SUM_E", "sum(map(NUM_EMPTY, #.V))"),     # 汇总时没有行
    ("COUNT_E", "count(NUM_EMPTY, true)"),
    ("AVG_E", "avg(map(NUM_EMPTY, #.V))"),
    ("MAX_E", "max(map(NUM_EMPTY, #.V))"),
    ("MIN_E", "min(map(NUM_EMPTY, #.V))"),
]
NUM_RULES: list[dict[str, Any]] = [
    *({"id": f"R_{f}", "entity": "NUM_DEMO", "field": f, "order": i + 1, "expression": e} for i, (f, e) in enumerate(NUM_EXPRESSIONS)),
    # 条件（when）求值出错按成立：NAME 为空时 matches 出错
    {"id": "R_COND", "entity": "NUM_DEMO", "field": "COND", "order": 20, "when": "matches(NAME, '胶囊')", "expression": "A + 1"},
    # 分支都不匹配：字段保持原值
    {"id": "R_KEEP", "entity": "NUM_DEMO", "field": "KEEP", "order": 21, "when": "S == '胶囊'", "expression": "A * 100"},
    # 校验规则的条件出错同样按成立
    {"id": "R_V_COND", "entity": "NUM_DEMO", "category": "validate", "field": "NAME", "order": 30,
     "when": "matches(NAME, '胶囊')", "level": "prompt", "message": "名称含胶囊"},
]


def numeric_pack() -> dict[str, Any]:
    return pack("NUM_DEMO", 1, NUM_FIELDS, NUM_RULES)


# ---------------------------------------------------------------- 显示求值（C07 v6 第 3.1 节）：只执行界面规则，不计算、不校验

DISP_FIELDS = {
    "DISP_DEMO": {"ID": num("system", 0), "STATUS": text(), "TOTAL": num("calculated")},
    "DISP_DTL": {"DTLID": num("system", 0), "QTY": num()},
}
# 假设的规则：主表合计汇总明细数量（计算），合计超过 100、明细数量 ≤ 0 时拒绝（校验）；停用的单据整行不可编辑、字体变灰，
# 没有明细时整行黄底（条件引用明细），明细数量 ≤ 0 时数量必填、标红（界面）
DISP_RULES: list[dict[str, Any]] = [
    {"id": "R_DISP_TOTAL", "entity": "DISP_DEMO", "field": "TOTAL", "order": 10, "expression": "sum(map(DISP_DTL, #.QTY))"},
    {"id": "R_DISP_TOTAL_MAX", "entity": "DISP_DEMO", "category": "validate", "field": "TOTAL", "order": 20,
     "when": "TOTAL > 100", "level": "reject", "message": "合计不能超过100"},
    {"id": "R_DISP_QTY_GT0", "entity": "DISP_DTL", "category": "validate", "field": "QTY", "order": 21,
     "when": "QTY <= 0", "level": "reject", "message": "数量必须大于0"},
    {"id": "R_DISP_STOPPED", "layer": "page", "page": "DISP_DEMO", "entity": "DISP_DEMO", "category": "ui", "order": 30,
     "when": "STATUS == '停用'", "effect": {"editable": False, "rowStyle": {"color": "#999999"}}},
    {"id": "R_DISP_NO_DTL", "layer": "page", "page": "DISP_DEMO", "entity": "DISP_DEMO", "category": "ui", "order": 31,
     "when": "count(DISP_DTL, true) == 0", "effect": {"rowStyle": {"backgroundColor": "#fff3cd"}}},
    {"id": "R_DISP_QTY_RED", "layer": "page", "page": "DISP_DEMO", "entity": "DISP_DTL", "category": "ui", "field": "QTY", "order": 32,
     "when": "QTY <= 0", "effect": {"required": True, "cellStyle": {"color": "#d03050"}}},
]


def display_pack() -> dict[str, Any]:
    return pack("DISP_DEMO", 1, DISP_FIELDS, DISP_RULES)


# ---------------------------------------------------------------- 跨实体依赖成环：主表汇总明细 X，明细 X 又引用主表汇总

def cycle_pack() -> dict[str, Any]:
    fields = {"CYC": {"ID": num("system", 0), "SUM_X": num("calculated")},
              "CYC_DTL": {"DTLID": num("system", 0), "X": num("calculated"), "Y": num()}}
    rules = [
        {"id": "R_SUM_X", "entity": "CYC", "field": "SUM_X", "order": 10, "expression": "sum(map(CYC_DTL, #.X))"},
        {"id": "R_X", "entity": "CYC_DTL", "field": "X", "order": 20, "expression": "master.SUM_X + Y"},
    ]
    return pack("CYC", 1, fields, rules)
