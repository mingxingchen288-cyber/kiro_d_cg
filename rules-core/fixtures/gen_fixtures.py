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


def result_row(entity: str, r: dict[str, Any], computed: dict[str, Any]) -> dict[str, Any]:
    ident = {"rowKey": r["rowKey"]} if "rowKey" in r else {"clientRowId": r["clientRowId"]}
    return {"entity": entity, **ident, "computed": computed, "fields": {}, "style": {"row": None, "cells": {}}}


def ok(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"ok": True, "rows": rows, "effects": []}


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
                 check: dict[tuple[str, int], dict[str, str]] | None = None) -> dict[str, Any]:
    """details 中的每行为 row(...)；deleted 为标为删除的 rowKey，不进入汇总和结果。check：与业务例子或 cmx 核对的值。"""
    master = row(master_values, key=master_values["DOCID"])
    live = {e: [r for r in rs if r.get("rowKey") not in deleted] for e, rs in details.items()}
    calc = oracle.cost_document(master_values, {e: [r["values"] for r in rs] for e, rs in live.items()})
    for (entity, i), want in (check or {}).items():
        for f, v in want.items():
            assert oracle.D(calc["details"][entity][i][f]) == oracle.D(v), (name, entity, i, f, calc["details"][entity][i][f], v)
    rows = [result_row("COST_PINGGU", master, calc["master"])]
    for entity, rs in live.items():
        rows += [result_row(entity, r, c) for r, c in zip(rs, calc["details"][entity])]
    req = request("COST_PINGGU", master, details, phase=phase, changed=changed)
    return fixture(name, source, "packs/cost-pinggu.json", req, ok(rows))


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


# ---------------------------------------------------------------- 单表演示

def demo_fixture(name: str, source: str, values: dict[str, Any], old: dict[str, Any], phase: str, data: dict[str, Any] | None) -> dict[str, Any]:
    full = {"ID": "1", "QTY": None, "PRICE": None, **{f: None for f in ("AMOUNT", "THIRD", "BACK", "PRICE_DELTA", "QTY_DELTA", "NET")}, **values}
    master = row(full, key="1", old=old)
    changed = [{"entity": "DEMO_ORDER", "rowKey": "1", "op": "modify", "fields": sorted(old)}]
    req = request("DEMO_ORDER", master, {}, phase=phase, changed=changed, data=data if phase == "commit" else None)
    expected = ok([result_row("DEMO_ORDER", master, oracle.demo(full, old, data if phase == "commit" else None))])
    return fixture(name, source, "packs/demo-order.json", req, expected)


def main() -> None:
    write(HERE / "packs" / "expr-demo.json", gen_packs.expr_pack())
    write(HERE / "packs" / "cost-pinggu.json", gen_packs.cost_pack())
    write(HERE / "packs" / "demo-order.json", gen_packs.demo_pack())
    write(HERE / "packs" / "cycle.json", gen_packs.cycle_pack())
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
    entry = request("COST_PINGGU", row(cost_master("900001"), key="900001"), {"COST_MATERIAL": [], "COST_PACKAGE": []})
    entry |= {"purpose": "approvalEntry", "flow": "COST_TO_GOODS", "level": 1}
    items.append(fixture("审批入口-以后实现", "C07 第 3 节：审批入口先返回不满足", "packs/cost-pinggu.json", entry, {"ok": True, "satisfied": False}))
    broken = request("COST_PINGGU", row(cost_master("900001"), key="900001"), {})
    del broken["phase"]
    items.append(fixture("请求缺phase", "C07 第 3 节：请求不合法返回 INPUT_INVALID", "packs/cost-pinggu.json", broken,
                         {"ok": False, "error": {"code": "INPUT_INVALID"}}, match="errorCode"))
    for i, item in enumerate(items, 1):
        write(HERE / "cases" / f"{i:02d}-{item['name']}.json", item)
    write(HERE / "cases" / "90-依赖成环.json", {"kind": "packInvalid", "name": "依赖成环", "source": "RC-09：跨实体成环，load_pack 返回 PACK_INVALID",
                                             "pack": "packs/cycle.json", "expected": {"code": "PACK_INVALID", "messageContains": ["R_SUM_X", "R_X"]}})
    write(HERE / "cases" / "91-C01边界样例.json", {"kind": "consistency", "name": "C01边界样例", "source": "C01 第 3 节的边界样例",
                                               "cases": [{"a": a, "b": b, "consistent": c} for a, b, c in C01_CASES]})
    print(f"写出 {len(items) + 2} 个样例")


if __name__ == "__main__":
    main()
