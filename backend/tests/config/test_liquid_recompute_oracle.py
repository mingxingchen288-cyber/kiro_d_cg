"""液体成本核算的计算规则对 d_cg 的液体单据重新计算（第 8 批 G2，T-CF-10，config 的 CF-17）。

seed 的液体规则（`rule.R_LQ_*`，由旧 cost-pinggu-lq 的页面规则 604、616、620 转换）经 config 编成规则包，用 rules-core 的真实
wheel 对 d_cg 中全部液体单据求值（只读：主表 T_COST_PINGGU_LQ，明细经两个读取视图；明细表自己的分类列只在 cmx 中，
读 CMX.T_COST_PINGGU_DTL_LQ.DTL_USEFLAG）。

1. 规则包算出的每个计算字段，与按旧计算引擎（`cost-web/src/v3/logic/calc-engine/calculator.ts`：空值按 0、除以 0 得 0、
   分支都不匹配时字段不变）用 Decimal 直接算的结果相同：规则按旧页面规则写对了。
2. 与库里旧系统存下的值比较（两边都按 WP-15 处理到 8 位小数，再按 C01 第 3 节判断）。2026-10-31 的结果：493 张单据中
   11 张全部一致；不一致的每一处都归到下面一类（`explain`），归不了类的只有 `KNOWN_STALE` 里逐条查过的几处：
   - 上游带过来：按库里存的输入值，这一条规则算出的就是库里的值，不一致只因为它用到的字段不一致；
   - 库里为空：旧系统没有算过这一列；
   - 旧存储过程 P_PINGGU_DTL_COMPUTE_LQ（"由BOM生成明细""同步采购价"调用）：包材每批数量按包装规格 P_PERPACK 除；
   - 旧存储过程 P_PINGGU_COMPUTE_LQ：主表合计按明细表自己的分类列求和，含两个视图看不到的明细（物料编号为空或不在物料清单）；
     年销售额少除 100；
   - 成本核算（固体）的页面公式 475：出厂价除包装规格、千片加工费乘 1000、年加工费和年毛利除 1000、年销售额按每批销售额折算，
     其中一部分是导入时保留了 0～2 位小数的旧值；
   - 原辅料每批数量没乘（1 + 额外投料量 / 100）。
   详细数字和例子见 `.reports/batch8-20261031/g2-liquid-cost/报告.md`。d_cg 的液体单据以后被改过，这里的已知清单要随之核对。

运行：`uv run --with <wheel> pytest -m oracle tests/config/test_liquid_recompute_oracle.py -o log_cli=true --log-cli-level=INFO`。
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, getcontext
from typing import Any

import pytest
from sqlalchemy import Engine, text

from cost_platform.assembly.settings import Settings
from cost_platform.config.catalog import Catalog
from cost_platform.config.packs import build_pack, pack_bytes
from cost_platform.contracts.decimal_text import format_decimal, numbers_consistent
from cost_platform.db_core.engine import create_oracle_engine
from cost_platform.pipeline.values import round_decimal

from .support import seed_drafts

pytestmark = pytest.mark.oracle

cost_rules_core = pytest.importorskip("cost_rules_core", reason="需要 rules-core 的 wheel")
from cost_rules_core import RulesEngine  # noqa: E402

getcontext().prec = 60
ENGINE = RulesEngine()
PAGE = "COST_PINGGU_LQ"
MATERIAL, PACKAGE = "COST_MATERIAL_LQ", "COST_PACKAGE_LQ"
VIEWS = {MATERIAL: "V_COST_PINGGU_MATERIAL_LQ", PACKAGE: "V_COST_PINGGU_PACKAGE_LQ"}
CONTEXT = {"userId": "1", "departmentId": "10", "role": "ADMIN", "today": "2026-10-31", "origin": "user"}
ZERO, ONE, TAX = Decimal(0), Decimal(1), Decimal("1.13")
PKG_EACH = re.compile("桶|说明书|小盒|标签|瓶|盖注射器|适配器|量杯|勺|分度器")
KNOWN_STALE = {
    # 主表的批量、合计后来被清空或改过，库里的每批销售额、每批加工费、每盒加工费是改之前算的（q11：2933 的批量为空）
    *{(d, PAGE, f) for d in ("2933", "2934", "2935", "2936", "2937", "2950") for f in ("SALEMONEY", "JGF_BATCH", "JGF_PERQP")},
    ("2931", PAGE, "JGF_BATCH"), ("2932", PAGE, "JGF_BATCH"),  # 每批物料成本为空，每批加工费是按原来的合计算的
    ("2559", PAGE, "TOTAL_FL"), ("2559", PAGE, "TOTAL_BC"),  # 明细单价后来改过（17.2981132075 等），主表合计没有重算
    ("2556", MATERIAL, "COST_BATCH"),  # 玉米淀粉：额外投料量 10 算进了每批数量，每批成本没跟着重算
    # 10007～10009：主表没有产品（不能由 BOM 生成），包材每批数量是手填的整数（9000、6000、12000、4500）
    ("10007", PACKAGE, "BATCH_QTY"), ("10008", PACKAGE, "BATCH_QTY"), ("10009", PACKAGE, "BATCH_QTY"),
}
_log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    s = Settings.load()
    engine = create_oracle_engine(s.db_user, s.db_password, s.db_dsn)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------- 读 d_cg、用规则包求值

@dataclass
class Data:
    masters: dict[str, dict[str, Any]]
    details: dict[str, dict[str, list[dict[str, Any]]]]  # 单据 → 明细实体 → 行（读取视图）
    by_flag: dict[str, dict[str, Decimal]]  # 单据 → 明细表自己的分类 → 每批成本合计（明细表全部行）
    computed: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)  # (实体, 行主键) → 规则包算出的值


def _rows(engine: Engine, sql: str) -> list[dict[str, Any]]:
    with engine.connect() as c:
        return [{k.upper(): v for k, v in r.items()} for r in c.execute(text(sql)).mappings()]


def _wire(value: Any) -> Any:
    return format_decimal(value) if isinstance(value, Decimal) else value


@pytest.fixture(scope="module")
def data(engine: Engine) -> Data:
    catalog = Catalog({}).merged(seed_drafts())
    handle = ENGINE.load_pack(pack_bytes(build_pack(catalog, PAGE, 1, ENGINE.core_version())))
    names = {code: [f.name for f in catalog.entity(code).fields] for code in (PAGE, *VIEWS)}
    masters = {str(m["DOCID"]): m for m in _rows(engine, f"SELECT {', '.join(names[PAGE])} FROM T_COST_PINGGU_LQ ORDER BY DOCID")}
    details: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {e: [] for e in VIEWS})
    for entity, view in VIEWS.items():
        for row in _rows(engine, f"SELECT {', '.join(names[entity])} FROM {view} ORDER BY DOCID, DTLID"):
            details[str(row["DOCID"])][entity].append(row)
    by_flag: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in _rows(engine, "SELECT d.DOCID, c.DTL_USEFLAG, d.COST_BATCH FROM T_COST_PINGGU_DTL_LQ d "
                             "LEFT JOIN CMX.T_COST_PINGGU_DTL_LQ c ON c.DTLID = d.DTLID"):
        by_flag[str(row["DOCID"])][row["DTL_USEFLAG"]] += num(row["COST_BATCH"])
    found = Data(masters, details, by_flag)
    for docid, master in masters.items():
        document = {"entity": PAGE, "master": {"rowKey": docid, "values": {k: _wire(v) for k, v in master.items()}},
                    "details": {e: [{"rowKey": str(r["DTLID"]), "values": {k: _wire(v) for k, v in r.items()}}
                                    for r in details[docid][e]] for e in VIEWS}}
        request = {"purpose": "operation", "operation": f"{PAGE}.save", "page": PAGE, "phase": "commit", "context": CONTEXT,
                   "document": document, "changed": [], "data": {}}
        result = json.loads(ENGINE.evaluate(handle, json.dumps(request, ensure_ascii=False)))
        assert result["ok"] is True, result
        for row in result["rows"]:
            found.computed[(row["entity"], row["rowKey"])] = row["computed"]
    return found


# ---------------------------------------------------------------- 旧计算引擎的算法（Decimal）

def num(value: Any) -> Decimal:
    """空值按 0（旧计算引擎 normalizeScopeValue；rules-core 第 8 节）。"""
    return ZERO if value is None else Decimal(str(value))


def div(a: Any, b: Any) -> Decimal:
    """除以 0 得 0（旧计算引擎 normalizeNumber 把无穷变成 0；rules-core 第 8 节）。"""
    return ZERO if num(b) == 0 else num(a) / num(b)


def package_branch(name: str | None) -> int | None:
    """620 的三个分支按包材名称部分匹配，取第一个；都不匹配为 None。"""
    name = name or ""
    if PKG_EACH.search(name):
        return 0
    return 1 if "大纸箱" in name else 2 if "托盘" in name else None


def package_batch(row: dict[str, Any], master: dict[str, Any], per_pack: Decimal = ONE, extra: bool = True) -> Decimal:
    """包材每批数量（620）；`per_pack` 为包装规格时是旧过程 P_PINGGU_DTL_COMPUTE_LQ 的算法。"""
    factor = 1 + num(row["EXADD_MATER"]) / 100 if extra else ONE
    apex, branch = div(master["APEX_PL"], per_pack), package_branch(row["GOODSNAME"])
    if branch == 0:
        return apex * factor
    if branch == 1:
        return Decimal(math.ceil(div(apex, master["S_PERBACK"]) * factor))
    if branch == 2:
        return Decimal(math.ceil(div(apex, num(master["S_PERBACK"]) * num(master["X_PERBACK"])) * factor))
    return num(row["BATCH_QTY"])


def material_batch(row: dict[str, Any], master: dict[str, Any], extra: bool = True) -> Decimal:
    """原辅料每批数量（616）。"""
    factor = 1 + num(row["EXADD_MATER"]) / 100 if extra else ONE
    return num(row["PER_HL"]) * num(master["APEX_PL"]) * factor / 1000000


def totals(material: list[dict[str, Any]], package: list[dict[str, Any]]) -> dict[str, Decimal]:
    """604 的原料、辅料、包材合计：有原料时三项都除以 1.13。"""
    raw = sum((num(r["COST_BATCH"]) for r in material if r["DTL_USEFLAG"] == "原料"), ZERO)
    tax = ONE / TAX if raw > 0 else ONE
    return {"TOTAL_YL": raw * tax,
            "TOTAL_FL": sum((num(r["COST_BATCH"]) for r in material if r["DTL_USEFLAG"] == "辅料"), ZERO) * tax,
            "TOTAL_BC": sum((num(r["COST_BATCH"]) for r in package
                             if r["DTL_USEFLAG"] in ("印字包材", "非印字包材")), ZERO) * tax}


def master_fields(m: dict[str, Any], sums: dict[str, Decimal]) -> dict[str, Decimal]:
    """604 的主表公式；`sums` 为三项合计，其余输入取 `m`（全部重算时 `m` 为算出的值，局部核对时为库里的值）。"""
    out = dict(sums)
    out["TOTAL_COST"] = num(m["TOTAL_YL"]) + num(m["TOTAL_FL"]) + num(m["TOTAL_BC"])
    out["SALEMONEY"] = num(m["OUT_PRICE_RMB"]) * num(m["APEX_PL"]) * (num(m["YIELD"]) / 100)
    out["JGF_BATCH"] = num(m["SALEMONEY"]) - num(m["TOTAL_COST"])
    out["COST_PERBOX"] = div(m["TOTAL_COST"], m["APEX_PL"])
    out["JGF_PERQP"] = div(m["JGF_BATCH"], m["APEX_PL"])
    out["ML_PERQP"] = num(m["JGF_PERQP"]) - num(m["COST_PERQP"])
    out["Y_JG_RE"] = num(m["JGF_PERQP"]) * num(m["ANNUAL_QTY"])
    out["Y_ML"] = num(m["ML_PERQP"]) * num(m["ANNUAL_QTY"])
    out["Y_SALE"] = num(m["ANNUAL_QTY"]) * num(m["OUT_PRICE_RMB"]) * (num(m["YIELD"]) / 100)
    return out


def reference(data: Data, docid: str) -> dict[tuple[str, str], dict[str, Decimal]]:
    """按旧计算引擎从输入字段算出整张单据的计算字段（多轮求值到不变，相当于按依赖顺序算一遍）。"""
    master, rows = dict(data.masters[docid]), {e: [dict(r) for r in found] for e, found in data.details[docid].items()}
    out: dict[tuple[str, str], dict[str, Decimal]] = {}
    for entity, batch in ((MATERIAL, material_batch), (PACKAGE, package_batch)):
        for row in rows[entity]:
            row["BATCH_QTY"] = batch(row, master)
            row["COST_BATCH"] = row["BATCH_QTY"] * num(row["PRICE"])
            out[(entity, str(row["DTLID"]))] = {"BATCH_QTY": row["BATCH_QTY"], "COST_BATCH": row["COST_BATCH"]}
    sums = totals(rows[MATERIAL], rows[PACKAGE])
    master.update(sums)
    for name in ("TOTAL_COST", "SALEMONEY", "JGF_BATCH", "COST_PERBOX", "JGF_PERQP", "ML_PERQP", "Y_JG_RE", "Y_ML", "Y_SALE"):
        master[name] = master_fields(master, sums)[name]
    out[(PAGE, docid)] = {k: master[k] for k in (*sums, "TOTAL_COST", "SALEMONEY", "JGF_BATCH", "COST_PERBOX", "JGF_PERQP",
                                                  "ML_PERQP", "Y_JG_RE", "Y_ML", "Y_SALE")}
    return out


# ---------------------------------------------------------------- 比较和归类

def round8(value: Any) -> Decimal:
    return round_decimal(num(value), None)


def same(a: Any, b: Any) -> bool:
    """两边都按 WP-15 处理到 8 位小数（库里旧前端用浮点算出的值常有 12 位以上的小数，例如 30055.600000000002），
    再按 C01 第 3 节判断；空值按 0。"""
    return numbers_consistent(format_decimal(round8(a)), format_decimal(round8(b)))


def close(candidate: Decimal, stored: Any) -> bool:
    """候选算法的结果就是库里的值：一致，或相对差小于 1e-9（旧前端的浮点误差），或者库里只有 0～2 位小数、
    等于候选值四舍五入到同样的位数（导入的旧值）。"""
    if same(candidate, stored):
        return True
    value = num(stored)
    if abs(candidate - value) <= Decimal("1e-9") * max(abs(value), ONE):
        return True
    exponent = value.normalize().as_tuple().exponent
    places = max(0, -exponent) if isinstance(exponent, int) else 0
    return places <= 2 and candidate.quantize(ONE.scaleb(-places), ROUND_HALF_UP) == value


def explain(data: Data, docid: str, entity: str, row: dict[str, Any], name: str) -> str | None:
    """库里的值为什么与规则重算的不同；归不了类时为 None。"""
    stored, master = row.get(name), data.masters[docid]
    if stored is None:
        return "库里为空"
    candidates: dict[str, Decimal] = {}
    if entity == PAGE:
        details = data.details[docid]
        candidates["上游带过来"] = master_fields(master, totals(details[MATERIAL], details[PACKAGE]))[name]
        flags = data.by_flag[docid]
        raw = flags.get("原料", ZERO)
        tax = ONE / TAX if raw > 0 else ONE
        by_flag = {"TOTAL_YL": raw * tax, "TOTAL_FL": flags.get("辅料", ZERO) * tax,
                   "TOTAL_BC": (flags.get("印字包材", ZERO) + flags.get("非印字包材", ZERO)) * tax}
        if name in by_flag:
            candidates["旧过程：合计按明细表自己的分类，含页面看不到的行"] = by_flag[name]
        apex, annual = master["APEX_PL"], master["ANNUAL_QTY"]
        solid = {"SALEMONEY": div(master["OUT_PRICE_RMB"], master["P_PERPACK"]) * num(apex) * num(master["YIELD"]) / 100,
                 "JGF_PERQP": div(master["JGF_BATCH"], apex) * 1000,
                 "Y_JG_RE": num(master["JGF_PERQP"]) / 1000 * num(annual),
                 "Y_ML": num(master["ML_PERQP"]) / 1000 * num(annual),
                 "Y_SALE": div(master["SALEMONEY"], apex) * num(annual)}
        if name in solid:
            candidates["成本核算（固体）的公式"] = solid[name]
        if name == "Y_SALE":
            candidates["旧过程：年销售额少除 100"] = num(annual) * num(master["OUT_PRICE_RMB"]) * num(master["YIELD"])
    elif name == "COST_BATCH":
        candidates["上游带过来"] = num(row["BATCH_QTY"]) * num(row["PRICE"])
    elif entity == MATERIAL:
        candidates["上游带过来"] = material_batch(row, master)
        candidates["原辅料每批数量没乘（1+额外投料量）"] = material_batch(row, master, extra=False)
    else:
        candidates["上游带过来"] = package_batch(row, master)
        per_pack = num(master["P_PERPACK"])
        candidates["旧过程：包材按包装规格除"] = package_batch(row, master, per_pack).quantize(Decimal("1e-4"), ROUND_HALF_UP)
        candidates["旧过程：包材按包装规格除、没乘（1+额外投料量）"] = package_batch(row, master, per_pack, extra=False).quantize(
            Decimal("1e-4"), ROUND_HALF_UP)
    return next((label for label, value in candidates.items() if close(value, stored)), None)


# ---------------------------------------------------------------- 测试

def test_seed_liquid_rules_compute_as_old_calc_engine(data: Data) -> None:
    """规则包对每张液体单据算出的计算字段，与按旧计算引擎的算法（604、616、620）直接算的相同。"""
    assert len(data.masters) > 400
    differ = []
    for docid in data.masters:
        for key, values in reference(data, docid).items():
            got = data.computed[key]
            assert set(got) == set(values), key
            differ += [(docid, *key, n, got[n], str(v)) for n, v in values.items() if not same(got[n], v)]
    assert differ == []


def test_old_stored_values_differences_are_explained(data: Data) -> None:
    """与库里旧系统存下的值比较：不一致的每一处都归到一类（见模块说明），归不了类的只有逐条查过的 KNOWN_STALE。"""
    stored_rows: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {(PAGE, d): (d, m) for d, m in data.masters.items()}
    for docid, found in data.details.items():
        for entity, rows in found.items():
            stored_rows |= {(entity, str(r["DTLID"])): (docid, r) for r in rows}
    categories: Counter[tuple[str, str, str]] = Counter()
    unexplained, docs_with_difference, compared = set(), set(), 0
    for (entity, row_key), values in data.computed.items():
        docid, row = stored_rows[(entity, row_key)]
        for name, value in values.items():
            compared += 1
            if same(value, row.get(name)) or row.get(name) is None and round8(value) == 0:
                continue
            docs_with_difference.add(docid)
            label = explain(data, docid, entity, row, name)
            if label is None:
                unexplained.add((docid, entity, name))
                label = "逐条查过的旧数据（KNOWN_STALE）"
            categories[(entity, name, label)] += 1
    _log.info("液体单据 %d 张，比较 %d 个计算值；全部一致的单据 %d 张：%s", len(data.masters), compared,
              len(set(data.masters) - docs_with_difference), sorted(set(data.masters) - docs_with_difference, key=int))
    for key, count in sorted(categories.items()):
        _log.info("不一致 %s %s %s：%d 处", *key, count)
    assert unexplained <= KNOWN_STALE, sorted(unexplained - KNOWN_STALE)
    assert len(set(data.masters) - docs_with_difference) >= 10
