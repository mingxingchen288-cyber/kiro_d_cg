"""生成 rules-core/fixtures/ 下成对的请求和期望结果（C07 第 6 节）。运行：python rules-core/fixtures/gen_fixtures.py

期望值由 oracle.py 按用户公式独立算出，并与业务例子给出的数和 cmx 中的真实值核对（见各样例的 source）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gen_packs
import oracle

HERE = Path(__file__).resolve().parent
CTX = {"userId": "1", "departmentId": "10", "role": "COST_ACCOUNTANT", "today": "2026-10-28", "origin": "user"}


def write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request(entity: str, master: dict[str, Any], details: dict[str, list[dict[str, Any]]], *, phase: str = "preview",
            operation: str | None = None, changed: list[dict[str, Any]] | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"purpose": "operation", "operation": operation or f"{entity}.save", "page": entity, "phase": phase, "context": CTX,
            "document": {"entity": entity, "master": master, "details": details}, "changed": changed or [], "data": data or {}}


def row(values: dict[str, Any], key: str | None = None, client: str | None = None, old: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"rowKey": key} if key is not None else {"clientRowId": client}
    out["values"] = values
    if old:
        out["old"] = old
    return out


def result_row(entity: str, r: dict[str, Any], computed: dict[str, Any], fields: dict[str, Any] | None = None,
               style_row: dict[str, Any] | None = None, cells: dict[str, Any] | None = None) -> dict[str, Any]:
    """C07 第 3 节的一行：界面规则给出的字段状态在 fields，行样式和单元格样式在 style。"""
    ident = {"rowKey": r["rowKey"]} if "rowKey" in r else {"clientRowId": r["clientRowId"]}
    return {"entity": entity, **ident, "computed": computed, "fields": fields or {}, "style": {"row": style_row, "cells": cells or {}}}


def ok(rows: list[dict[str, Any]], effects: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"ok": True, "rows": rows, "effects": effects or []}


def effect(kind: str, rule: str, message: str, entity: str, row_key: str, field: str) -> dict[str, Any]:
    """C07 第 3 节的效果，定位到实体、行和字段。"""
    return {"kind": kind, "rule": rule, "message": message, "entity": entity, "rowKey": row_key, "field": field}


def fixture(name: str, source: str, pack: str, req: dict[str, Any], expected: dict[str, Any], match: str = "full") -> dict[str, Any]:
    return {"kind": "evaluate", "name": name, "source": source, "pack": pack, "match": match, "request": req, "expected": expected}


# ---------------------------------------------------------------- T-RC-1

def expr_fixture(name: str, source: str, a: str, b: str, sum_: str, quot: str) -> dict[str, Any]:
    master = row({"ID": "1", "A": a, "B": b, "SUM": None, "QUOT": None}, key="1")
    req = request("EXPR_DEMO", master, {})
    return fixture(name, source, "packs/expr-demo.json", req, ok([result_row("EXPR_DEMO", master, {"SUM": sum_, "QUOT": quot})]))


C01_CASES = [
    ("1.23", "1.230000000000000", True), ("1.2345678901234561", "1.2345678901234562", True),
    ("0.000000000000001", "0.000000000000002", False), ("123456789012345.67", "123456789012345.68", False),
    ("2.5", "3.5", False), ("1.5", "-1.5", False), ("-0", "0", True), ("-0.00", "0", True),
    ("-0.0000000000000001", "0", True),
]


# ---------------------------------------------------------------- 成本核算

COST_MASTER_DEFAULTS = {"GOODSNAME": None, "MEMO": None, "APEX_PL": "100000", "P_PERPACK": "100", "S_PERBACK": "40", "X_PERBACK": "20",
                        "M_PERPACK": "10", "OUT_PRICE_F": "0.2", "FMRATE": "7.1", "YIELD": "98", "COST_PERQP": "15", "ANNUAL_QTY": "5000000"}


def cost_master(docid: str, **values: Any) -> dict[str, Any]:
    v = {"DOCID": docid, **COST_MASTER_DEFAULTS, **values}
    v.update({f: "0" for f in gen_packs.MASTER_CALCULATED if f not in v})
    return v


def dtl(dtlid: str, docid: str, goodsid: str, name: str, flag: str, per_hl: str | None, exadd: str | None, price: str | None,
        batch_qty: str = "0", cost_batch: str = "0") -> dict[str, Any]:
    return {"DTLID": dtlid, "DOCID": docid, "GOODSID": goodsid, "GOODSNAME": name, "DTL_USEFLAG": flag, "PER_HL": per_hl,
            "EXADD_MATER": exadd, "PRICE": price, "BATCH_QTY": batch_qty, "COST_BATCH": cost_batch}


def cost_fixture(name: str, source: str, master_values: dict[str, Any], details: dict[str, list[dict[str, Any]]], *,
                 phase: str = "preview", changed: list[dict[str, Any]] | None = None, deleted: set[str] = frozenset(),
                 check: dict[tuple[str, int], dict[str, str]] | None = None, effects: list[dict[str, Any]] | None = None,
                 master_style: dict[str, Any] | None = None) -> dict[str, Any]:
    """details 中的每行为 row(...)；deleted 为标为删除的 rowKey，不进入汇总和结果。check：与业务例子或 cmx 核对的值。
    effects：校验规则给出的效果；master_style：界面规则给主表行的样式。"""
    master = row(master_values, key=master_values["DOCID"])
    live = {e: [r for r in rs if r.get("rowKey") not in deleted] for e, rs in details.items()}
    calc = oracle.cost_document(master_values, {e: [r["values"] for r in rs] for e, rs in live.items()})
    for (entity, i), want in (check or {}).items():
        for f, v in want.items():
            assert oracle.D(calc["details"][entity][i][f]) == oracle.D(v), (name, entity, i, f, calc["details"][entity][i][f], v)
    rows = [result_row("COST_PINGGU", master, calc["master"], style_row=master_style)]
    for entity, rs in live.items():
        rows += [result_row(entity, r, c) for r, c in zip(rs, calc["details"][entity])]
    req = request("COST_PINGGU", master, details, phase=phase, changed=changed)
    return fixture(name, source, "packs/cost-pinggu.json", req, ok(rows, effects))


def e02(phase: str) -> dict[str, Any]:
    m = cost_master("900001", APEX_PL="100000", P_PERPACK="100")
    pk = [row(dtl("910001", "900001", "200500", "塑料瓶", "印字包材", None, "2", "0.35"), key="910001", old={"EXADD_MATER": "0"}),
          row(dtl("910002", "900001", "200186", "铝箔", "印字包材", "50", "2", "48"), key="910002", old={"EXADD_MATER": "0"})]
    changed = [{"entity": "COST_PACKAGE", "rowKey": k, "op": "modify", "fields": ["EXADD_MATER"]} for k in ("910001", "910002")]
    return cost_fixture(f"E02-包材批量-{phase}", "业务例子 E02：瓶 BATCH_QTY=1020，铝箔 BATCH_QTY=5.1（单据、单价为假设值）", m,
                        {"COST_MATERIAL": [], "COST_PACKAGE": pk}, phase=phase, changed=changed,
                        check={("COST_PACKAGE", 0): {"BATCH_QTY": "1020"}, ("COST_PACKAGE", 1): {"BATCH_QTY": "5.1"}})


def e03() -> dict[str, Any]:
    m = cost_master("900002", APEX_PL="100000", P_PERPACK="0")
    pk = [row(dtl("910003", "900002", "200500", "塑料瓶", "印字包材", None, "2", "0.35"), key="910003")]
    return cost_fixture("E03-每盒数量为0", "业务例子 E03：P_PERPACK=0 时 BATCH_QTY=0（除以 0 为 0，不出提示）", m,
                        {"COST_MATERIAL": [], "COST_PACKAGE": pk}, phase="commit", check={("COST_PACKAGE", 0): {"BATCH_QTY": "0"}})


# cmx 单据 200726 的真实明细（.reports/chain1/05-替代单据.out.txt）。APEX_PL=600000、P_PERPACK=50 由明细反推；
# S_PERBACK、X_PERBACK 和主表其余输入为假设值（满足大纸箱 27、托盘 2）。
M200726 = [("208517", "10593", "醋酸氟氢可的松", "原料", "0.031", None, "205.13", "0.0186", "3.815418"),
           ("208518", "2007", "一水乳糖80目（直压）", "辅料", "6.875", None, "54", "4.125", "222.75"),
           ("208519", "311", "一水乳糖（200目）", "辅料", "23.25", None, "26", "13.95", "362.7"),
           ("208520", "5412", "羧甲淀粉钠（A类）", "辅料", "0.781", None, None, "0.4686", "0"),
           ("208521", "12618", "硬脂酸镁", "辅料", "0.156", None, "22", "0.0936", "2.0592")]
P200726 = [("208522", "200361", "说明书", "印字包材", None, None, "0.064", "12000", "768"),
           ("208523", "200360", "小盒", "印字包材", None, None, None, "12000", "0"),
           ("208524", "200186", "铝箔", "印字包材", "45", None, "48", "27", "1296"),
           ("208525", "200105", "托盘", "非印字包材", None, None, "147.48", "2", "294.96"),
           ("208526", "14142", "聚氯乙烯/聚乙烯/聚偏二氯乙烯固体药用复合硬片", "非印字包材", "185", None, "54", "111", "5994"),
           ("208527", "7445", "大纸箱", "非印字包材", None, None, None, "27", "0")]
M200726_MASTER = dict(APEX_PL="600000", P_PERPACK="50", S_PERBACK="450", X_PERBACK="20", M_PERPACK=None, OUT_PRICE_F="0.125",
                      FMRATE="7.1", YIELD="98", COST_PERQP="15.32", ANNUAL_QTY="12000000")


def rows_200726(spec: list[tuple], zero: bool) -> tuple[list[dict[str, Any]], dict[int, dict[str, str]]]:
    """zero 为 True 时把计算字段清零后重算，期望值与 cmx 一致。"""
    out, check = [], {}
    for i, (dtlid, gid, name, flag, per_hl, exadd, price, q, c) in enumerate(spec):
        out.append(row(dtl(dtlid, "200726", gid, name, flag, per_hl, exadd, price, "0" if zero else q, "0" if zero else c), key=dtlid))
        check[i] = {"BATCH_QTY": q, "COST_BATCH": c}
    return out, check


def cost_200726() -> dict[str, Any]:
    mat, mc = rows_200726(M200726, zero=True)
    pkg, pc = rows_200726(P200726, zero=True)
    check = {**{("COST_MATERIAL", i): v for i, v in mc.items()}, **{("COST_PACKAGE", i): v for i, v in pc.items()}}
    return cost_fixture("成本核算-单据200726", "cmx 单据 200726 的 11 条真实明细：重算的 BATCH_QTY、COST_BATCH 与 cmx 虚拟列相同；主表汇总按用户公式",
                        cost_master("200726", **M200726_MASTER), {"COST_MATERIAL": mat, "COST_PACKAGE": pkg}, phase="commit", check=check)


def cost_new_and_deleted() -> dict[str, Any]:
    mat, _ = rows_200726(M200726, zero=False)
    new = row(dtl("", "200726", "12618", "硬脂酸镁", "辅料", "0.1", None, "22"), client="tmp-0b8f5a6e-4c1d-4e2a-9f3b-7d6c5e4a3b21")
    del new["values"]["DTLID"]
    pkg, _ = rows_200726(P200726, zero=False)
    changed = [{"entity": "COST_MATERIAL", "clientRowId": new["clientRowId"], "op": "add", "fields": ["GOODSID", "PER_HL", "PRICE"]},
               {"entity": "COST_MATERIAL", "rowKey": "208519", "op": "delete", "fields": []}]
    return cost_fixture("成本核算-新增行和删除行", "C07 第 3 节：汇总包含新增行，不含标为删除的行（在 200726 上新增一行辅料、删除 208519）",
                        cost_master("200726", **M200726_MASTER), {"COST_MATERIAL": mat + [new], "COST_PACKAGE": pkg},
                        changed=changed, deleted={"208519"}, check={("COST_MATERIAL", 4): {"BATCH_QTY": "0.06"}})


def cost_branches() -> dict[str, Any]:
    m = cost_master("900003", **M200726_MASTER)
    mat = [row(dtl("920001", "900003", "3001", "空心胶囊", "辅料", "1", "2", "0.05"), key="920001")]
    pkg = [row(dtl("920002", "900003", "3002", "中盒", "非印字包材", None, None, "0.8"), key="920002"),
           # cmx 单据 200203 的真实明细：名称不含任何包材关键字，BATCH_QTY 保持 370.16，COST_BATCH=5922.56（单价由两者反推）
           row(dtl("920003", "900003", "3003", "PVC 250μm", "印字包材", None, None, "16", "370.16", "5922.56"), key="920003")]
    return cost_fixture("成本核算-胶囊中盒和分支都不匹配", "胶囊分支、中盒分支（假设值）；分支都不匹配保持原值（cmx 200203 的 PVC 250μm）",
                        m.copy() | {"M_PERPACK": "10"}, {"COST_MATERIAL": mat, "COST_PACKAGE": pkg},
                        check={("COST_MATERIAL", 0): {"BATCH_QTY": "61.2"}, ("COST_PACKAGE", 0): {"BATCH_QTY": "134"},
                               ("COST_PACKAGE", 1): {"BATCH_QTY": "370.16", "COST_BATCH": "5922.56"}})


# d_cg 单据 2919 的真实主表和原辅料明细（.reports/batch1-20261029/rules-core/03-单据2919.out.txt）：MEMO 为 ERP未搭建BOM，
# 两行原辅料的 PER_HL 都为空；包材明细（9 行）略去。d_cg 中 PRICE < 0 的行没有，把一水乳糖的单价从 26 改成 -1 是假设的修改。
M2919 = dict(GOODSNAME="比沙可啶肠溶片", MEMO="ERP未搭建BOM", APEX_PL="850000", P_PERPACK="30", S_PERBACK="352", X_PERBACK="12",
             M_PERPACK=None, OUT_PRICE_F="3.432", FMRATE="8.1845", YIELD="90", COST_PERQP="18", ANNUAL_QTY="6000000")
PER_HL_MESSAGE, PRICE_MESSAGE = "每片含量必填且必须大于0", "单价必填且不能为负数"


def cost_2919(phase: str) -> dict[str, Any]:
    mat = [row(dtl("100713", "2919", "4726", "比沙可啶", "原料", None, None, "2489.725"), key="100713"),
           row(dtl("100714", "2919", "311", "一水乳糖（200目）", "辅料", None, None, "-1"), key="100714", old={"PRICE": "26"})]
    changed = [{"entity": "COST_MATERIAL", "rowKey": "100714", "op": "modify", "fields": ["PRICE"]}]
    # 校验规则按 order 执行，每条规则逐行检查：先两行的每片含量，再一水乳糖的单价
    effects = [effect("reject", "R_MAT_PER_HL_GT0", PER_HL_MESSAGE, "COST_MATERIAL", "100713", "PER_HL"),
               effect("reject", "R_MAT_PER_HL_GT0", PER_HL_MESSAGE, "COST_MATERIAL", "100714", "PER_HL"),
               effect("reject", "R_MAT_PRICE_GE0", PRICE_MESSAGE, "COST_MATERIAL", "100714", "PRICE")]
    # 整行红底是页面规则，只在 preview 执行（C07 第 2 节）
    style = {"backgroundColor": "#ffcccc"} if phase == "preview" else None
    return cost_fixture(f"成本核算-校验和整行红底-{phase}",
                        "旧系统成本核算的两条校验（PER_HL > 0、PRICE ≥ 0，拒绝保存）和主表 MEMO='ERP未搭建BOM' 整行红底（旧 GRID_STYLE）；"
                        "d_cg 单据 2919 的真实主表和原辅料（PER_HL 为空），单价改成 -1 为假设的修改",
                        cost_master("2919", **M2919), {"COST_MATERIAL": mat, "COST_PACKAGE": []}, phase=phase, changed=changed,
                        effects=effects, master_style=style)


# ---------------------------------------------------------------- 单表演示

def demo_fixture(name: str, source: str, values: dict[str, Any], old: dict[str, Any], phase: str, data: dict[str, Any] | None,
                 fields: dict[str, Any] | None = None, cells: dict[str, Any] | None = None) -> dict[str, Any]:
    full = {"ID": "1", "QTY": None, "PRICE": None, **{f: None for f in ("AMOUNT", "THIRD", "BACK", "PRICE_DELTA", "QTY_DELTA", "NET")}, **values}
    master = row(full, key="1", old=old)
    changed = [{"entity": "DEMO_ORDER", "rowKey": "1", "op": "modify", "fields": sorted(old)}]
    req = request("DEMO_ORDER", master, {}, phase=phase, changed=changed, data=data if phase == "commit" else None)
    expected = ok([result_row("DEMO_ORDER", master, oracle.demo(full, old, data if phase == "commit" else None), fields=fields, cells=cells)])
    return fixture(name, source, "packs/demo-order.json", req, expected)


def demo_ui() -> dict[str, Any]:
    """界面规则：R_UI_ROW_LOCK 整行不可编辑（field 为空，给到 DEMO_ORDER 的每个字段），R_UI_PRICE_REQUIRED 单价必填、字体变灰。"""
    fields: dict[str, Any] = {f: {"editable": False} for f in sorted(gen_packs.DEMO_FIELDS["DEMO_ORDER"])}
    fields["PRICE"] = {"editable": False, "required": True}
    return demo_fixture("界面规则-整行不可编辑和单价必填", "C06 第 5 节：ui 规则的 field 为空时作用于整行；指定字段的 required 和 cellStyle（假设的规则）",
                        {"QTY": "100", "PRICE": "2.5"}, {}, "preview", None, fields=fields, cells={"PRICE": {"color": "#999999"}})


# ---------------------------------------------------------------- T-RC-3：模块说明第 8 节的数值处理规则表

# 旧系统前端计算引擎（my-project cost-web/src/v3/logic/calc-engine/calculator.ts）对同一输入的结果：
# 用 node 24 直接运行旧引擎得到，见 .reports/batch1-20261029/rules-core/old-engine/（run-old.mts、old-results.json）。这里是抄录的结果。
OLD_ENGINE: dict[str, Any] = {
    "engine": "my-project cost-web/src/v3/logic/calc-engine/calculator.ts（mathjs 15.1.0，JavaScript 浮点），2026-10-30 用 node 24 运行",
    "computed": {"NULL_ADD": "1", "DIV0": "0", "ZERO_ZERO": "0", "OVER": "100000000000000000000000000000", "BAD": "0",
                 "THIRD": "1.6666666666666667", "COND": "6", "KEEP": "7", "SUM_V": "5", "SUM_E": "0", "COUNT_E": "0", "AVG_E": "0",
                 "MAX_E": "0", "MIN_E": "0"},
    "differences": [
        "THIRD：旧系统浮点 1.6666666666666667，新平台 1.6666666666666666666666666667，浮点误差，按 C01 第 3 节一致",
        "OVER：旧系统 1e29（JavaScript 浮点到 1.8e308 才是 Infinity），新平台超出 28 位有效数字按第 8 节为 0；数的表示范围不同，不是计算出错",
        "BAD：都是 0；旧系统只在控制台告警，新平台另给一条 prompt（第 8 节）",
        "COND：都是 6；旧系统按成立的原因是 evalCondition 的 new Function 遇到作用域里名为 in 的函数报 SyntaxError，"
        "所以旧系统 condition 写法的条件总按成立（同一输入的 KEEP 写成 condition 时旧系统得 500，写成多公式时得 7）",
        "R_V_COND：旧系统的校验（validator.ts）没有条件写法，没有可对照的结果",
    ],
}


def numeric() -> dict[str, Any]:
    values = {"ID": "1", "A": "5", "Z": "0", "E": None, "BIG": "10000000000000000000000000000", "S": "abc", "NAME": None,
              **{f: None for f in gen_packs.NUM_CALCULATED}, "KEEP": "7"}
    master = row(values, key="1")
    dtl_rows = [row({"DTLID": "11", "V": "2"}, key="11"), row({"DTLID": "12", "V": None}, key="12"), row({"DTLID": "13", "V": "3"}, key="13")]
    computed = {"NULL_ADD": "1", "DIV0": "0", "ZERO_ZERO": "0", "OVER": "0", "BAD": "0", "THIRD": oracle.fmt(oracle.fit(oracle.D(5) / 3)),
                "SUM_V": "5", "SUM_E": "0", "COUNT_E": "0", "AVG_E": "0", "MAX_E": "0", "MIN_E": "0", "COND": "6", "KEEP": "7"}
    effects = [{"kind": "prompt", "rule": "R_BAD", "message": BAD_MESSAGE, "entity": "NUM_DEMO", "rowKey": "1", "field": "BAD"},
               {"kind": "prompt", "rule": "R_V_COND", "message": "名称含胶囊", "entity": "NUM_DEMO", "rowKey": "1", "field": "NAME"}]
    rows = [result_row("NUM_DEMO", master, computed)] + [result_row("NUM_DTL", r, {}) for r in dtl_rows]
    req = request("NUM_DEMO", master, {"NUM_DTL": dtl_rows, "NUM_EMPTY": []})
    item = fixture("T-RC-3-数值处理规则表", "模块说明第 8 节每一行一条规则：空值和缺失字段按 0、除以 0 和 0/0 为 0、溢出为 0、"
                   "求值出错为 0 并提示、条件出错按成立（计算和校验）、汇总时空值按 0、没有行时汇总为 0、分支都不匹配保持原值、不舍入",
                   "packs/numeric.json", req, ok(rows, effects))
    item["oldSystem"] = OLD_ENGINE
    return item


# 计算规则求值出错时的提示：规则编码、字段和 zen-expression 给出的原因（zen-expression 2.1.6）
BAD_MESSAGE = "计算规则 R_BAD 求值出错，BAD 按 0 处理：VM error: Opcode Multiply: Unsupported type"


def main() -> None:
    write(HERE / "packs" / "expr-demo.json", gen_packs.expr_pack())
    write(HERE / "packs" / "cost-pinggu.json", gen_packs.cost_pack())
    write(HERE / "packs" / "demo-order.json", gen_packs.demo_pack())
    write(HERE / "packs" / "cycle.json", gen_packs.cycle_pack())
    write(HERE / "packs" / "numeric.json", gen_packs.numeric_pack())
    t1 = "T-RC-1 样例"
    items = [
        expr_fixture("T-RC-1-0.1加0.2", t1 + "：十进制得 0.3（旧系统浮点为 0.30000000000000004）", "0.1", "0.2", "0.3", "0.5"),
        expr_fixture("T-RC-1-除法", t1 + "：1/3 保留 28 位有效数字", "1", "3", "4", "0.3333333333333333333333333333"),
        expr_fixture("T-RC-1-大数加0.01", t1, "123456789012345.67", "0.01", "123456789012345.68", "12345678901234567"),
        expr_fixture("T-RC-1-除以0", t1 + "：除以 0 为 0", "10", "0", "10", "0"),
        expr_fixture("T-RC-1-C01第16位", t1 + "：C01 第 3 节，第 16 位不同仍一致", "1.2345678901234561", "0", "1.2345678901234562", "0"),
        e02("preview"), e02("commit"), e03(), cost_200726(), cost_new_and_deleted(), cost_branches(),
        demo_fixture("E04-正数不舍入", "业务例子 E04：计算值 1.234567885 原样返回，保存时才处理小数位（WP-15）",
                     {"QTY": "0.5", "PRICE": "2.46913577"}, {}, "preview", None),
        demo_fixture("E04-负数不舍入", "业务例子 E04：计算值 -1.234567885 原样返回", {"QTY": "-0.5", "PRICE": "2.46913577"}, {}, "preview", None),
        demo_fixture("精度和old-preview", "T-RC-2：1/3 再乘 3 按 28 位有效数字；old 只给出 PRICE，QTY 的 old 等于当前值；preview 不算 serverOnly 规则",
                     {"QTY": "1", "PRICE": "3.50"}, {"PRICE": "3.20"}, "preview", None),
        demo_fixture("精度和old-commit", "同上，commit 阶段执行操作层的 serverOnly 规则，用 data", {"QTY": "1", "PRICE": "3.50"}, {"PRICE": "3.20"},
                     "commit", {"discountRate": "0.1"}),
    ]
    broken = request("COST_PINGGU", row(cost_master("900001"), key="900001"), {})
    del broken["phase"]
    items.append(fixture("请求缺phase", "C07 第 3 节：请求不合法返回 INPUT_INVALID", "packs/cost-pinggu.json", broken,
                         {"ok": False, "error": {"code": "INPUT_INVALID"}}, match="errorCode"))
    # T-RC-2 的校验、界面规则和 T-RC-3（接在后面，前面的编号不变）
    items += [cost_2919("preview"), cost_2919("commit"), demo_ui(), numeric()]
    for i, item in enumerate(items, 1):
        write(HERE / "cases" / f"{i:02d}-{item['name']}.json", item)
    write(HERE / "cases" / "90-依赖成环.json", {"kind": "packInvalid", "name": "依赖成环", "source": "RC-09：跨实体成环，load_pack 返回 PACK_INVALID",
                                             "pack": "packs/cycle.json", "expected": {"code": "PACK_INVALID", "messageContains": ["R_SUM_X", "R_X"]}})
    write(HERE / "cases" / "91-C01边界样例.json", {"kind": "consistency", "name": "C01边界样例", "source": "C01 第 3 节的边界样例",
                                               "cases": [{"a": a, "b": b, "consistent": c} for a, b, c in C01_CASES]})
    print(f"写出 {len(items) + 2} 个样例")


if __name__ == "__main__":
    main()
