"""液体成本核算的真实验证（d_cg，第 8 批 G2：T-OP-6、T-CF-10）：seed 的液体配置在 d_cg 上通过保存校验；"由BOM生成明细"
（`COST_PINGGU_LQ.generateFromBom`，两个 `replaceDetails`，代替旧 P_COST_BOM_INSERT_LQ）和保存（`COST_PINGGU_LQ.save`）
经真实的写入管道执行，写入后按液体的计算规则重算。

组装同 `test_sql_actions_oracle.py`：注册表 boot 真实的 db-core、rules-core、identity 目录、authz、queries 读取、
write-pipeline、operations、approval 插件，配置快照由 `backend/seed/config` 在内存中生成，不写 PF_CONFIG_ITEM。

测试数据：每个测试把液体成本单 2571（产品 8726，2mg地塞米松片，批量 300000，原辅料 4 行、包材 6 行；BOM 9 行：
原辅料 4、包材 5，q14）复制成一张新单据（主键取 T_COST_PINGGU_LQ_SEQ，明细取 T_COST_PINGGU_DTL_LQ_SEQ），结束时删掉它、
它的明细和本测试的命令记录。
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, text

from cost_platform.assembly.settings import Settings
from cost_platform.config.catalog import Catalog
from cost_platform.config.deps import OracleSequences, StaticDepartments
from cost_platform.config.validation import Validator
from cost_platform.contracts import types as t
from cost_platform.db_core.engine import OracleUnitOfWorkFactory, create_oracle_engine
from cost_platform.db_core.schema import OracleSchemaInspector

from .test_sql_actions_oracle import ADMIN, Platform, close_to, dec, fetch, round8, seed_drafts

pytestmark = pytest.mark.oracle

PAGE = "COST_PINGGU_LQ"
BOM = "COST_PINGGU_LQ.generateFromBom"
SAVE = "COST_PINGGU_LQ.save"
SOURCE = 2571
MEMO = "PF_TEST G2 液体成本核算"
VIEWS = {"COST_MATERIAL_LQ": "V_COST_PINGGU_MATERIAL_LQ", "COST_PACKAGE_LQ": "V_COST_PINGGU_PACKAGE_LQ"}
PKG_EACH = re.compile("桶|说明书|小盒|标签|瓶|盖注射器|适配器|量杯|勺|分度器")
# 旧 P_COST_BOM_INSERT_LQ 的查询部分（my-project/sql20260523/03_program_units.sql 第 772–790 行），用来核对新增的行；
# 原辅料的每片含量按旧 P_PINGGU_DTL_COMPUTE_LQ 第一步（per_hl = batch_qty / apex_pl * 1000000）由 BOM 用量反推
OLD_BOM_SQL = """SELECT V.GOODSID AS GOODSID,
       CASE WHEN DECODE(V.USEFLAG, 4, '原料', 2, '辅料', 3, '非印字包材', 5, '印字包材') IN ('原料', '辅料')
            THEN NVL(V.USEQTY, 0) / NULLIF(M.APEX_PL, 0) * 1000000 ELSE NULL END AS PER_HL,
       F.PRICE AS PRICE, V.USEQTY AS USEQTY
  FROM T_COST_PINGGU_LQ M, CMX.T_COST_BOM_GOODS_TREE_V V, CMX.PUB_GOODS_V F
 WHERE M.DOCID = :docid AND V.TREEID LIKE :tree AND V.PID <> '-1' AND V.USEFLAG NOT IN (0, 1) AND V.GOODSID = F.GOODSID(+)"""
_log = logging.getLogger(__name__)


class LiquidPlatform(Platform):
    """同成本核算的组装，命令发到液体成本核算页。"""

    def press_on(self, operation: str, selected: list[tuple[str, str]]) -> t.CommandResult:
        key = str(uuid.uuid4())
        self.request_keys.append(key)
        command = t.parse_wire(t.Command, {
            "requestKey": key, "page": PAGE, "operation": operation, "documents": [],
            "params": {"selectedRows": [{"entity": e, "rowKey": k} for e, k in selected]}})
        return self.runner.execute(command, self.config.context())

    def save(self, documents: list[dict[str, Any]]) -> t.CommandResult:
        key = str(uuid.uuid4())
        self.request_keys.append(key)
        command = t.parse_wire(t.Command, {"requestKey": key, "page": PAGE, "operation": SAVE, "documents": documents, "params": {}})
        return self.runner.execute(command, self.config.context())


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    s = Settings.load()
    engine = create_oracle_engine(s.db_user, s.db_password, s.db_dsn)
    yield engine
    engine.dispose()


def _columns(engine: Engine, table: str, skip: tuple[str, ...]) -> str:
    with engine.connect() as c:
        names = c.execute(text("SELECT COLUMN_NAME FROM USER_TAB_COLUMNS WHERE TABLE_NAME = :t ORDER BY COLUMN_ID"), {"t": table})
        return ", ".join(n for n in names.scalars() if n not in skip)


@pytest.fixture
def document(engine: Engine) -> Iterator[str]:
    """复制液体成本单 2571（主表和明细）为一张新单据；结束时删掉它和它的明细。"""
    master, detail = _columns(engine, "T_COST_PINGGU_LQ", ("DOCID", "MEMO")), _columns(engine, "T_COST_PINGGU_DTL_LQ", ("DTLID", "DOCID"))
    with engine.begin() as c:
        docid = int(c.execute(text("SELECT T_COST_PINGGU_LQ_SEQ.NEXTVAL FROM DUAL")).scalar_one())
        c.execute(text(f"INSERT INTO T_COST_PINGGU_LQ (DOCID, MEMO, {master}) SELECT :d, :memo, {master} FROM T_COST_PINGGU_LQ "
                       "WHERE DOCID = :s"), {"d": docid, "memo": MEMO, "s": SOURCE})
        c.execute(text(f"INSERT INTO T_COST_PINGGU_DTL_LQ (DTLID, DOCID, {detail}) SELECT T_COST_PINGGU_DTL_LQ_SEQ.NEXTVAL, :d, "
                       f"{detail} FROM T_COST_PINGGU_DTL_LQ WHERE DOCID = :s"), {"d": docid, "s": SOURCE})
    yield str(docid)
    with engine.begin() as c:
        c.execute(text("DELETE FROM T_COST_PINGGU_DTL_LQ WHERE DOCID = :d"), {"d": docid})
        c.execute(text("DELETE FROM T_COST_PINGGU_LQ WHERE DOCID = :d"), {"d": docid})


@pytest.fixture
def platform(engine: Engine) -> Iterator[LiquidPlatform]:
    made = LiquidPlatform(seed_drafts())
    yield made
    with engine.begin() as c:
        for key in made.request_keys:
            c.execute(text("DELETE FROM PF_COMMAND WHERE USER_ID = :u AND REQUEST_KEY = :k"), {"u": ADMIN.user_id, "k": key})
    made.close()


def detail_rows(engine: Engine, docid: str) -> dict[str, list[dict[str, Any]]]:
    return {entity: fetch(engine, f"SELECT DTLID, GOODSID, GOODSNAME, DTL_USEFLAG, PER_HL, EXADD_MATER, PRICE, BATCH_QTY, COST_BATCH "
                                  f"FROM {view} WHERE DOCID = :d ORDER BY DTLID", d=int(docid)) for entity, view in VIEWS.items()}


def master_row(engine: Engine, docid: str) -> dict[str, Any]:
    [row] = fetch(engine, "SELECT * FROM T_COST_PINGGU_LQ WHERE DOCID = :d", d=int(docid))
    return row


def div(a: Any, b: Any) -> Decimal:
    return Decimal(0) if dec(b) == 0 else dec(a) / dec(b)


def check_recalculated(engine: Engine, docid: str) -> None:
    """明细的每批数量、每批成本和主表的计算字段都等于 seed 液体规则的结果（R_LQ_*，旧页面规则 604、616、620）。"""
    m, rows = master_row(engine, docid), detail_rows(engine, docid)
    apex = dec(m["apex_pl"])
    for row in rows["COST_MATERIAL_LQ"]:
        assert close_to(row["batch_qty"], dec(row["per_hl"]) * apex * (1 + dec(row["exadd_mater"]) / 100) / 1000000), row
    for row in rows["COST_PACKAGE_LQ"]:
        factor, name = 1 + dec(row["exadd_mater"]) / 100, row["goodsname"] or ""
        if PKG_EACH.search(name):
            expected = apex * factor
        elif "大纸箱" in name:
            expected = Decimal(math.ceil(div(apex, m["s_perback"]) * factor))
        elif "托盘" in name:
            expected = Decimal(math.ceil(div(apex, dec(m["s_perback"]) * dec(m["x_perback"])) * factor))
        else:
            continue  # 分支都不匹配：每批数量不变
        assert close_to(row["batch_qty"], expected), row
    for row in [*rows["COST_MATERIAL_LQ"], *rows["COST_PACKAGE_LQ"]]:
        assert close_to(row["cost_batch"], dec(row["batch_qty"]) * dec(row["price"])), row
    raw = sum((dec(r["cost_batch"]) for r in rows["COST_MATERIAL_LQ"] if r["dtl_useflag"] == "原料"), Decimal(0))
    tax = 1 / Decimal("1.13") if raw > 0 else Decimal(1)
    expected = {"total_yl": raw * tax,
                "total_fl": sum((dec(r["cost_batch"]) for r in rows["COST_MATERIAL_LQ"] if r["dtl_useflag"] == "辅料"), Decimal(0)) * tax,
                "total_bc": sum((dec(r["cost_batch"]) for r in rows["COST_PACKAGE_LQ"]), Decimal(0)) * tax}
    expected["total_cost"] = sum(expected.values(), Decimal(0))
    expected["salemoney"] = dec(m["out_price_rmb"]) * apex * dec(m["yield"]) / 100
    expected["jgf_batch"] = expected["salemoney"] - expected["total_cost"]
    expected["cost_perbox"] = div(expected["total_cost"], apex)
    expected["jgf_perqp"] = div(expected["jgf_batch"], apex)
    expected["ml_perqp"] = expected["jgf_perqp"] - dec(m["cost_perqp"])
    expected["y_jg_re"] = expected["jgf_perqp"] * dec(m["annual_qty"])
    expected["y_ml"] = expected["ml_perqp"] * dec(m["annual_qty"])
    expected["y_sale"] = dec(m["annual_qty"]) * dec(m["out_price_rmb"]) * dec(m["yield"]) / 100
    for name, value in expected.items():
        assert close_to(m[name], value), (name, m[name], value)
    _log.info("单据 %s 主表：%s", docid, {k: str(m[k]) for k in expected})
    for entity, found in rows.items():
        for r in found:
            _log.info("单据 %s %s：%s", docid, entity, {k: str(v) for k, v in r.items()})


# ---------------------------------------------------------------- 测试

def test_seed_liquid_config_passes_validation_on_d_cg(engine: Engine) -> None:
    """C06 第 10 节：seed 的液体配置（3 个实体、页面、两个操作、17 条规则、物料 Lookup、两个角色）在 d_cg 的真实表结构上
    通过保存校验：表、视图、列、序列 T_COST_PINGGU_LQ_SEQ / T_COST_PINGGU_DTL_LQ_SEQ 都在，"由BOM生成明细"的 SQL 交给 Oracle
    解析通过。只读，不写配置。"""
    drafts = seed_drafts()
    liquid = [(d.type, d.key) for d in drafts if "_LQ" in d.key or d.key.startswith("R_LQ_") or d.key == "costMaterial"]
    liquid += [("role", "ADMIN"), ("role", "技术中心"), ("approvalFlow", "GOODS_TO_COST")]
    assert len(liquid) == 27
    from cost_rules_core import RulesEngine

    validator = Validator(OracleSchemaInspector(engine), OracleSequences(), StaticDepartments(["18"]), RulesEngine())
    with OracleUnitOfWorkFactory(engine).begin() as uow:
        assert validator.check(uow, Catalog({}).merged(drafts), liquid) == []


def test_generate_from_bom_replaces_liquid_details_and_recalculates(engine: Engine, document: str,
                                                                    platform: LiquidPlatform) -> None:
    """选中新液体单据点"由BOM生成明细"：原来的明细全部删掉，按产品 8726 的 BOM 新增 9 行（原辅料 4、包材 5），物料、每片含量、
    单价与旧 P_COST_BOM_INSERT_LQ 的查询相同；名称、分类由物料 Lookup 带出；每批数量、每批成本和主表由液体规则算出，
    名称不在包材三个分支里的两行（铝箔、硬片）每批数量为 BOM 用量。"""
    before = {r["dtlid"] for rows in detail_rows(engine, document).values() for r in rows}
    assert len(before) == 10
    result = platform.press_on(BOM, [(PAGE, document)])
    assert result.outcome == "saved"

    rows = detail_rows(engine, document)
    after = [r for found in rows.values() for r in found]
    assert len(rows["COST_MATERIAL_LQ"]) == 4 and len(rows["COST_PACKAGE_LQ"]) == 5
    assert {r["dtlid"] for r in after}.isdisjoint(before)
    assert fetch(engine, "SELECT COUNT(*) AS N FROM T_COST_PINGGU_DTL_LQ WHERE DOCID = :d", d=int(document))[0]["n"] == 9
    old = fetch(engine, OLD_BOM_SQL, docid=int(document), tree=f"-{master_row(engine, document)['goodsid']}-%")
    expected = sorted((int(r["goodsid"]), round8(r["per_hl"]), r["price"]) for r in old)
    assert sorted((int(r["goodsid"]), round8(r["per_hl"]), r["price"]) for r in after) == expected
    assert all(r["goodsname"] and r["dtl_useflag"] for r in after)
    # 名称不在 620 三个分支里的包材（这张单据是铝箔、硬片）：每批数量是 BOM 用量（旧 P_COST_BOM_INSERT_LQ 插入 useqty，
    # 旧计算引擎分支不匹配时不变），每批成本 = BOM 用量 × 单价
    useqty = {int(r["goodsid"]): r["useqty"] for r in old}
    kept = [r for r in rows["COST_PACKAGE_LQ"] if not PKG_EACH.search(r["goodsname"]) and not re.search("大纸箱|托盘", r["goodsname"])]
    assert len(kept) == 2
    assert all(dec(r["batch_qty"]) == dec(useqty[int(r["goodsid"])]) != 0 for r in kept), kept
    check_recalculated(engine, document)
    added = [r for r in result.rows if isinstance(r, t.ResultRow) and r.entity != PAGE]
    assert {r.row_key for r in added} == {str(r["dtlid"]) for r in after}
    assert {r.values["DTL_USEFLAG"] for r in added} == {r["dtl_useflag"] for r in after}  # 由 Lookup 带出（WP-08）
    assert {r.row_key for r in result.rows if isinstance(r, t.DeletedRow)} == {str(k) for k in before}


def test_save_price_change_recalculates_the_liquid_document(engine: Engine, document: str, platform: LiquidPlatform) -> None:
    """改一行原辅料的单价并保存：这一行的每批成本、主表的合计和每盒成本等按液体规则重算，整张单据的计算字段都按规则写入
    （WP-07：保存时整单重算，库里旧过程算的包材每批数量也改成页面规则的值）；重新读出与命令结果相同。"""
    [first, *_] = detail_rows(engine, document)["COST_MATERIAL_LQ"]
    price = dec(first["price"]) + 1
    change = {"entity": PAGE, "master": {"op": "none", "rowKey": document},
              "details": [{"entity": "COST_MATERIAL_LQ", "op": "modify", "rowKey": str(first["dtlid"]),
                           "changes": {"PRICE": format(price, "f")}}]}
    total_before = master_row(engine, document)["total_cost"]
    result = platform.save([change])
    assert result.outcome == "saved"
    row = next(r for r in detail_rows(engine, document)["COST_MATERIAL_LQ"] if r["dtlid"] == first["dtlid"])
    assert dec(row["price"]) == price
    check_recalculated(engine, document)
    master = master_row(engine, document)
    assert master["total_cost"] != total_before
    returned = next(r for r in result.rows if isinstance(r, t.ResultRow) and r.entity == PAGE)
    assert dec(returned.values["TOTAL_COST"]) == dec(master["total_cost"])
    assert dec(returned.values["COST_PERBOX"]) == dec(master["cost_perbox"])
