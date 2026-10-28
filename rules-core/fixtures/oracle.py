"""样例期望值的独立算法：直接按用户给出的成本核算公式和模块说明第 8 节的数值规则，用 Python Decimal 逐步手算，
不经过 rules-core 和 ZEN 表达式。用来生成 fixtures 中的 expected。

每一步运算都按"28 位有效数字"处理（T-RC-2 验收：上游结果按全部精度参与下游计算，与按 28 位有效数字计算的值一致）：
结果取 rust_decimal 能表示的最多小数位（尾数不超过 96 位、小数位不超过 28），运算顺序与表达式相同（从左到右）。
"""

from __future__ import annotations

import re
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal, getcontext
from typing import Any

getcontext().prec = 80
D = Decimal
_MAX = D(79228162514264337593543950335)  # 2^96 - 1


def fit(x: Decimal) -> Decimal:
    if x == 0:
        return D(0)
    for scale in range(28, -1, -1):
        q = x.quantize(D(1).scaleb(-scale), rounding=ROUND_HALF_EVEN)
        if abs(q.scaleb(scale)) <= _MAX:
            return q
    raise OverflowError(x)


def n(value: Any) -> Decimal:
    """空值按 0（模块说明第 8 节）。"""
    return D(0) if value is None else D(value)


# None 表示除以 0 之后的"无值"：再参与运算仍为无值，整个表达式按 0（模块说明第 8 节）
Num = Decimal | None


def add(a: Num, b: Num) -> Num:
    return None if a is None or b is None else fit(a + b)


def sub(a: Num, b: Num) -> Num:
    return None if a is None or b is None else fit(a - b)


def mul(a: Num, b: Num) -> Num:
    return None if a is None or b is None else fit(a * b)


def div(a: Num, b: Num) -> Num:
    return None if a is None or b is None or b == 0 else fit(a / b)


def ceil(x: Num) -> Num:
    return None if x is None else x.to_integral_value(rounding=ROUND_CEILING)


def z(x: Num) -> Decimal:
    return D(0) if x is None else x


def fmt(x: Decimal) -> str:
    text = format(x.normalize(), "f")
    return "0" if text in ("-0", "0") else text


def batch_qty(row: dict[str, Any], m: dict[str, Any]) -> Decimal | str | None:
    """明细 BATCH_QTY：分支按顺序取第一个成立的，都不成立时保持原值。"""
    flag, name = row.get("DTL_USEFLAG"), row.get("GOODSNAME") or ""
    raw, pkg = flag in ("原料", "辅料"), flag in ("印字包材", "非印字包材")
    ex = add(D(1), div(n(row.get("EXADD_MATER")), D(100)))  # (1 + EXADD_MATER / 100)
    apex, per_hl = n(m.get("APEX_PL")), n(row.get("PER_HL"))
    pp, sp, xp, mp = (n(m.get(k)) for k in ("P_PERPACK", "S_PERBACK", "X_PERBACK", "M_PERPACK"))
    if raw and "胶囊" in name:
        return z(mul(div(apex, D(10000)), ex))
    if raw:
        return z(div(mul(mul(per_hl, apex), ex), D(1000000)))
    if pkg and re.search("桶|说明书|小盒|标签|瓶|盖|干燥剂|序列化", name):
        return z(mul(div(apex, pp), ex))
    if pkg and re.search("硬片|铝箔|复合膜", name):
        return z(div(mul(mul(per_hl, apex), ex), D(1000000)))
    if pkg and re.search("大纸箱", name):
        return z(ceil(mul(div(apex, mul(pp, sp)), ex)))
    if pkg and re.search("托盘", name):
        return z(ceil(mul(div(apex, mul(mul(pp, sp), xp)), ex)))
    if pkg and re.search("中盒", name):
        return z(ceil(mul(div(apex, mul(mp, sp)), ex)))
    return row.get("BATCH_QTY")  # 保持原值（文本）


def cost_document(master: dict[str, Any], details: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """按依赖顺序逐条手算：先明细 BATCH_QTY、COST_BATCH，再主表汇总和其余字段。"""
    out_details: dict[str, list[dict[str, str]]] = {}
    cb: dict[str, list[tuple[str, Decimal]]] = {}
    for entity, rows in details.items():
        out_details[entity], cb[entity] = [], []
        for row in rows:
            q = batch_qty(row, master)
            cost = z(mul(n(q), n(row.get("PRICE"))))
            out_details[entity].append({"BATCH_QTY": fmt(q) if isinstance(q, Decimal) else q, "COST_BATCH": fmt(cost)})
            cb[entity].append((row.get("DTL_USEFLAG"), cost))

    def total(entity: str, flags: tuple[str, ...]) -> Decimal:
        s = D(0)
        for f, c in cb.get(entity, []):
            if f in flags:
                s = fit(s + c)
        return s

    yl = total("COST_MATERIAL", ("原料",))
    factor = div(D(1), D("1.13")) if yl > 0 else D(1)
    m = {k: n(master.get(k)) for k in ("APEX_PL", "P_PERPACK", "OUT_PRICE_F", "FMRATE", "YIELD", "COST_PERQP", "ANNUAL_QTY")}
    r: dict[str, Decimal] = {}
    r["TOTAL_YL"] = z(mul(yl, factor))
    r["TOTAL_FL"] = z(mul(total("COST_MATERIAL", ("辅料",)), factor))
    r["TOTAL_BC"] = z(mul(total("COST_PACKAGE", ("印字包材", "非印字包材")), factor))
    r["TOTAL_COST"] = z(add(add(r["TOTAL_YL"], r["TOTAL_FL"]), r["TOTAL_BC"]))
    r["OUT_PRICE_RMB"] = z(mul(m["OUT_PRICE_F"], m["FMRATE"]))
    r["SALEMONEY"] = z(mul(mul(div(r["OUT_PRICE_RMB"], m["P_PERPACK"]), m["APEX_PL"]), div(m["YIELD"], D(100))))
    r["JGF_BATCH"] = z(sub(r["SALEMONEY"], r["TOTAL_COST"]))
    r["COST_PERBOX"] = z(mul(div(r["TOTAL_COST"], m["APEX_PL"]), m["P_PERPACK"]))
    r["JGF_PERQP"] = z(mul(div(r["JGF_BATCH"], m["APEX_PL"]), D(1000)))
    r["ML_PERQP"] = z(sub(r["JGF_PERQP"], m["COST_PERQP"]))
    r["Y_JG_RE"] = z(mul(div(r["JGF_PERQP"], D(1000)), m["ANNUAL_QTY"]))
    r["Y_ML"] = z(mul(div(r["ML_PERQP"], D(1000)), m["ANNUAL_QTY"]))
    r["Y_SALE"] = z(mul(div(r["SALEMONEY"], m["APEX_PL"]), m["ANNUAL_QTY"]))
    return {"master": {k: fmt(v) for k, v in r.items()}, "details": out_details}


def demo(values: dict[str, Any], old: dict[str, Any], data: dict[str, Any] | None) -> dict[str, str]:
    """单表演示（DEMO_ORDER）：old 只给出改过的字段，其余等于当前值；NET 只在 commit 时算。"""
    qty, price = n(values.get("QTY")), n(values.get("PRICE"))
    before = {**values, **old}
    third = z(div(qty, D(3)))
    amount = z(mul(qty, price))
    out = {"BACK": fmt(z(mul(third, D(3)))), "THIRD": fmt(third), "AMOUNT": fmt(amount),
           "PRICE_DELTA": fmt(z(sub(price, n(before.get("PRICE"))))), "QTY_DELTA": fmt(z(sub(qty, n(before.get("QTY")))))}
    if data is not None:
        out["NET"] = fmt(z(mul(amount, sub(D(1), n(data["discountRate"])))))
    return out
