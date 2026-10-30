"""按 SQL 的两个按钮动作的真实验证（d_cg，OP-09、OP-10）：成本核算的"由BOM生成明细"（seed 的操作）和 `updateRows`
（本测试自己定义的操作）经真实的写入管道执行。

组装：注册表 boot 真实的 db-core、rules-core、identity 目录、authz、queries 读取、write-pipeline、operations、approval
插件，命令经 orchestration 的 `CommandRunner` 执行（一个命令一个事务）。配置快照由 `backend/seed/config` 在内存中生成
（config 的 `derive`、`Snapshot`），不写 PF_CONFIG_ITEM；实体目录、执行上下文、命令审查和投递用 contracts 的替代实现，
不连 Redis。

测试数据：每个测试把成本单 200721（产品 392，500mg对乙酰氨基酚片，12 行明细）复制成一张新成本单（主键取
T_COST_PINGGU_SEQ，明细主键取 T_COST_PINGGU_DTL_SEQ），结束时删掉这张单据、它的明细和本测试的命令记录。
用户 2026-10-30 不要"同步采购价"按钮，seed 中已删除它的操作和按钮；`updateRows` 是通用动作（OP-10），这里用一个只给
测试用的操作和按钮（`UPDATE_ROWS`，只在内存配置中）验证它：SQL 同原来的"同步采购价"，加上 `D.DOCID = <新单据>`，只改这张单据。
"""

from __future__ import annotations

import asyncio
import copy
import logging
import math
import uuid
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text

from cost_platform.approval.plugin import ApprovalPlugin
from cost_platform.assembly.plugins import RulesCorePlugin, SystemPlugin
from cost_platform.assembly.settings import Settings
from cost_platform.authz.plugin import AuthzPlugin
from cost_platform.config.catalog import Catalog
from cost_platform.config.deps import OracleSequences, StaticDepartments
from cost_platform.config.records import ItemRecord, content_text
from cost_platform.config.seed import read_seed
from cost_platform.config.service import derive
from cost_platform.config.snapshot import ParsedCache, Snapshot
from cost_platform.config.validation import Validator
from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import (
    FakeCommandMonitor,
    FakeContextProvider,
    FakeDeliveryDispatcher,
    FakeEntityDirectory,
)
from cost_platform.contracts.ports import (
    CommandRecorder,
    ConfigSnapshotReader,
    ContextProvider,
    EntityDirectory,
    PipelineStage,
    RulesEngine,
    UnitOfWorkFactory,
)
from cost_platform.contracts.registry import PluginView, Registry
from cost_platform.db_core.engine import OracleUnitOfWorkFactory, create_oracle_engine
from cost_platform.db_core.plugin import DbCorePlugin
from cost_platform.db_core.schema import OracleSchemaInspector
from cost_platform.identity.plugin import IdentityDirectoryPlugin
from cost_platform.operations.plugin import OperationsPlugin
from cost_platform.orchestration.runner import CommandRunner
from cost_platform.pipeline.plugin import PipelinePlugin
from cost_platform.queries.plugin import QueryReadersPlugin

pytestmark = pytest.mark.oracle

SEED = Path(__file__).resolve().parents[2] / "seed" / "config"
PAGE = "COST_PINGGU"
BOM = "COST_PINGGU.generateFromBom"
UPDATE_ROWS = "COST_PINGGU.pfTestUpdateRows"
"""只给测试用的 `updateRows` 操作（`update_rows_for`），不在 seed 中。"""
SOURCE = 200721
"""复制来源：产品 392（500mg对乙酰氨基酚片），BOM 11 行（原辅料 5 行、包材 6 行，.reports/batch1-20261029/bom-price/05）。"""
MEMO = "PF_TEST 戊组 由BOM生成明细/updateRows"
VIEWS = {"COST_MATERIAL": "V_COST_PINGGU_MATERIAL", "COST_PACKAGE": "V_COST_PINGGU_PACKAGE"}
ADMIN = t.Identity(user_id="1", username="admin", display_name="系统管理员", department_id=None, role_code="ADMIN",
                   session_id="s-test-bom-price")

# 旧 P_COST_BOM_INSERT 的查询部分（my-project/docs/cost-pinggu-virtual-columns-after-save.sql 第 515–549 行），用来核对新增的行
OLD_BOM_SQL = """SELECT V.GOODSID AS GOODSID,
       CASE WHEN DECODE(V.USEFLAG, 4, '原料', 2, '辅料', 3, '非印字包材', 5, '印字包材') IN ('原料', '辅料')
            THEN NVL(V.USEQTY, 0) / NULLIF(M.APEX_PL, 0) * 1000000 ELSE NULL END AS PER_HL,
       F.PRICE AS PRICE,
       DECODE(V.USEFLAG, 4, '原料', 2, '辅料', 3, '非印字包材', 5, '印字包材') AS DTL_USEFLAG
  FROM T_COST_PINGGU M, CMX.T_COST_BOM_GOODS_TREE_V V, CMX.PUB_GOODS_V F
 WHERE M.DOCID = :docid AND V.TREEID LIKE :tree AND V.PID <> '-1' AND V.USEFLAG NOT IN (0, 1) AND V.GOODSID = F.GOODSID(+)"""

TOLERANCE = Decimal("0.000001")
_log = logging.getLogger(__name__)
"""核对过的数据记日志（`pytest -o log_cli=true --log-cli-level=INFO` 可以看到），测试数据结束时就删掉了。"""


# ---------------------------------------------------------------- 组装

class _Config:
    """内存中的已发布配置：seed 加本测试的操作，经 config 的 `derive` 生成页面视图和规则包。"""

    name = "test.config"
    provides = (EntityDirectory, ContextProvider, ConfigSnapshotReader)
    requires = (RulesEngine,)

    def __init__(self, drafts: Sequence[t.ConfigDraft]) -> None:
        self._drafts = list(drafts)

    def setup(self, reg: PluginView) -> None:
        self.rules = reg.get(RulesEngine)
        catalog = Catalog({}).merged(self._drafts)
        now = datetime.now().replace(microsecond=0)
        base = [ItemRecord(type=d.type, key=d.key, name=d.name, content_json=content_text(d.content), version=1, generation=1,
                           updated_by=ADMIN.user_id, updated_at=now) for d in self._drafts]
        derived, _ = derive(catalog, {}, 1, now, ADMIN.user_id, self.rules.core_version())
        self.snapshot = Snapshot(1, ADMIN.role_code, {r.id: r for r in [*base, *derived]}, ParsedCache(self.rules))
        reg.provide(EntityDirectory, FakeEntityDirectory(catalog.entities()))
        reg.provide(ContextProvider, FakeContextProvider(self.context()))
        reg.provide(ConfigSnapshotReader, self)  # approval 取角色名称（AP 审批进度）

    def read(self, role_code: str) -> Snapshot:
        return self.snapshot

    def current_version(self) -> int:
        return 1

    def context(self) -> t.ExecutionContext:
        return t.ExecutionContext(request_id=str(uuid.uuid4()), identity=ADMIN, config=self.snapshot, config_version=1,
                                  origin=t.Origin("user", None), now=datetime.now().replace(microsecond=0))


class _Collect:
    """取出组装好的命令事务、命令记录和全部管道阶段。"""

    name = "test.collect"
    provides = ()
    requires = (UnitOfWorkFactory, CommandRecorder, PipelineStage)

    def setup(self, reg: PluginView) -> None:
        self.uow = reg.get(UnitOfWorkFactory)
        self.recorder = reg.get(CommandRecorder)
        self.stages = reg.all(PipelineStage)


class Platform:
    def __init__(self, drafts: Sequence[t.ConfigDraft]) -> None:
        s = Settings.load()
        self._db = DbCorePlugin(s.db_user, s.db_password, s.db_dsn)
        self.config = _Config(drafts)
        collect = _Collect()
        Registry().boot([self._db, SystemPlugin(), RulesCorePlugin(), IdentityDirectoryPlugin(), AuthzPlugin(), QueryReadersPlugin(),
                         PipelinePlugin(s.lock_wait_seconds, s.request_wait_seconds, s.redis_url, s.redis_namespace),
                         OperationsPlugin(), ApprovalPlugin(), self.config, collect])
        self.runner = CommandRunner(collect.uow, collect.recorder, FakeCommandMonitor(), FakeDeliveryDispatcher(), collect.stages)
        self.request_keys: list[str] = []

    def press(self, operation: str, selected: Sequence[tuple[str, str]] = ()) -> t.CommandResult:
        """点页面上引用 `operation` 的按钮：命令只带选中行的主键（C02 第 1 节）。"""
        key = str(uuid.uuid4())
        self.request_keys.append(key)
        command = t.parse_wire(t.Command, {
            "requestKey": key, "page": PAGE, "operation": operation, "documents": [],
            "params": {"selectedRows": [{"entity": e, "rowKey": k} for e, k in selected]}})
        return self.runner.execute(command, self.config.context())

    def close(self) -> None:
        asyncio.run(self._db.stop())


def seed_drafts() -> list[t.ConfigDraft]:
    return read_seed(SEED)


def _update_rows_sql(view: str, docid: str | None) -> str:
    """原来"同步采购价"的 SQL：单价和物料清单参考价不同的明细改成参考价；`docid` 不为空时只查这张单据。"""
    only = f"D.DOCID = {int(docid)} AND " if docid is not None else ""
    return (f"SELECT D.DOCID AS DOC_ID, D.DTLID AS DTL_ID, G.PRICE AS PRICE FROM {view} D JOIN T_COST_GOODS G "
            f"ON G.GOODSID = D.GOODSID WHERE {only}G.USEFLAG NOT IN ('产成品', '半成品') AND DECODE(D.PRICE, G.PRICE, 0, 1) = 1 "
            "ORDER BY D.DOCID, D.DTLID")


def update_rows_for(docid: str | None) -> list[t.ConfigDraft]:
    """seed 加上只给测试用的 `updateRows` 操作 `UPDATE_ROWS` 和主表上引用它、不需要选中行的按钮。"""
    operation = t.ConfigDraft(type="operation", key=UPDATE_ROWS, name="PF_TEST 按 SQL 改单价", content={
        "label": "PF_TEST 按 SQL 改单价", "kind": "action",
        "writableFields": {"COST_MATERIAL": ["PRICE"], "COST_PACKAGE": ["PRICE"]},
        "impact": ["COST_PINGGU", "COST_MATERIAL", "COST_PACKAGE"],
        "actions": [{"action": "updateRows", "entity": entity, "sql": _update_rows_sql(view, docid),
                     "recordKeyColumn": "DOC_ID", "rowKeyColumns": ["DTL_ID"]} for entity, view in VIEWS.items()],
        "propagation": "end"})
    drafts = seed_drafts()
    for i, draft in enumerate(drafts):
        if (draft.type, draft.key) == ("page", PAGE):
            content = copy.deepcopy(draft.content)
            content["master"]["buttons"].append({"action": "pfTestUpdateRows", "label": "PF_TEST 按 SQL 改单价",
                                                 "operation": UPDATE_ROWS, "requiresSelection": False})
            drafts[i] = draft.model_copy(update={"content": content})
    return [*drafts, operation]


# ---------------------------------------------------------------- 测试数据

@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    s = Settings.load()
    engine = create_oracle_engine(s.db_user, s.db_password, s.db_dsn)
    yield engine
    engine.dispose()


def _columns(c: Connection, table: str, skip: Sequence[str]) -> str:
    names = c.execute(text("SELECT COLUMN_NAME FROM USER_TAB_COLUMNS WHERE TABLE_NAME = :t ORDER BY COLUMN_ID"), {"t": table}).scalars()
    return ", ".join(n for n in names if n not in skip)


@pytest.fixture
def document(engine: Engine) -> Iterator[str]:
    """复制成本单 200721（主表和 12 行明细）为一张新成本单；结束时删掉它和它的明细。"""
    with engine.begin() as c:
        docid = int(c.execute(text("SELECT T_COST_PINGGU_SEQ.NEXTVAL FROM DUAL")).scalar_one())
        master = _columns(c, "T_COST_PINGGU", ("DOCID", "MEMO"))
        c.execute(text(f"INSERT INTO T_COST_PINGGU (DOCID, MEMO, {master}) SELECT :d, :memo, {master} FROM T_COST_PINGGU "
                       "WHERE DOCID = :s"), {"d": docid, "memo": MEMO, "s": SOURCE})
        detail = _columns(c, "T_COST_PINGGU_DTL", ("DTLID", "DOCID"))
        c.execute(text(f"INSERT INTO T_COST_PINGGU_DTL (DTLID, DOCID, {detail}) SELECT T_COST_PINGGU_DTL_SEQ.NEXTVAL, :d, {detail} "
                       "FROM T_COST_PINGGU_DTL WHERE DOCID = :s"), {"d": docid, "s": SOURCE})
    yield str(docid)
    with engine.begin() as c:
        c.execute(text("DELETE FROM T_COST_PINGGU_DTL WHERE DOCID = :d"), {"d": docid})
        c.execute(text("DELETE FROM T_COST_PINGGU WHERE DOCID = :d"), {"d": docid})


@pytest.fixture
def platform_for(engine: Engine) -> Iterator[Callable[[list[t.ConfigDraft]], Platform]]:
    """按给定的配置组装平台；结束时删掉这些平台写的命令记录（PF_COMMAND）。"""
    made: list[Platform] = []

    def make(drafts: list[t.ConfigDraft]) -> Platform:
        made.append(Platform(drafts))
        return made[-1]

    yield make
    with engine.begin() as c:
        for platform in made:
            for key in platform.request_keys:
                c.execute(text("DELETE FROM PF_COMMAND WHERE USER_ID = :u AND REQUEST_KEY = :k"), {"u": ADMIN.user_id, "k": key})
    for platform in made:
        platform.close()


# ---------------------------------------------------------------- 读数据库、按计算规则算期望值

def fetch(engine: Engine, sql: str, **binds: Any) -> list[dict[str, Any]]:
    with engine.connect() as c:
        return [dict(r) for r in c.execute(text(sql), binds).mappings()]


def detail_rows(engine: Engine, docid: str) -> dict[str, list[dict[str, Any]]]:
    """这张单据的原辅料、包材（经两个读取视图，与页面相同）。"""
    return {entity: fetch(engine, f"SELECT DTLID, GOODSID, PER_HL, EXADD_MATER, PRICE, BATCH_QTY, COST_BATCH, DTL_USEFLAG, GOODSNAME "
                                  f"FROM {view} WHERE DOCID = :d ORDER BY DTLID", d=int(docid))
            for entity, view in VIEWS.items()}


def master_row(engine: Engine, docid: str) -> dict[str, Any]:
    [row] = fetch(engine, "SELECT * FROM T_COST_PINGGU WHERE DOCID = :d", d=int(docid))
    return row


def dec(value: Any) -> Decimal:
    """数据库的值转成 Decimal，空值按 0（与规则内核相同，rules-core 第 8 节）。"""
    return Decimal(0) if value is None else Decimal(str(value))


def round8(value: Any) -> Decimal | None:
    """WP-15：写入时最多保留 8 位小数。"""
    return None if value is None else dec(value).quantize(Decimal("0.00000001"), ROUND_HALF_UP)


def close_to(actual: Any, expected: Decimal) -> bool:
    return abs(dec(actual) - expected) <= TOLERANCE * max(Decimal(1), abs(expected))


def check_recalculated(engine: Engine, docid: str) -> None:
    """明细的每批数量、每批成本和主表的合计都等于 seed 计算规则的结果（R_MAT_*、R_PKG_*、R_MASTER_TOTAL_*）。"""
    master = master_row(engine, docid)
    rows = detail_rows(engine, docid)
    apex, per_pack = dec(master["apex_pl"]), dec(master["p_perpack"])
    per_box, per_pallet = per_pack * dec(master["s_perback"]), per_pack * dec(master["s_perback"]) * dec(master["x_perback"])
    for row in rows["COST_MATERIAL"]:  # 392 的原辅料名称都不含"胶囊"
        expected = dec(row["per_hl"]) * apex * (1 + dec(row["exadd_mater"]) / 100) / 1000000
        assert close_to(row["batch_qty"], expected), row
    for row in rows["COST_PACKAGE"]:  # 392 的包材：说明书、瓶盖、瓶签、小盒、瓶按每盒；大纸箱按每箱、托盘按每托取整
        factor = 1 + dec(row["exadd_mater"]) / 100
        if "大纸箱" in row["goodsname"]:
            expected = Decimal(math.ceil(apex / per_box * factor))
        elif "托盘" in row["goodsname"]:
            expected = Decimal(math.ceil(apex / per_pallet * factor))
        else:
            expected = apex / per_pack * factor
        assert close_to(row["batch_qty"], expected), row
    for row in [*rows["COST_MATERIAL"], *rows["COST_PACKAGE"]]:
        assert close_to(row["cost_batch"], dec(row["batch_qty"]) * dec(row["price"])), row
    raw = sum((dec(r["cost_batch"]) for r in rows["COST_MATERIAL"] if r["dtl_useflag"] == "原料"), Decimal(0))
    tax = 1 / Decimal("1.13") if raw > 0 else Decimal(1)
    fl = sum((dec(r["cost_batch"]) for r in rows["COST_MATERIAL"] if r["dtl_useflag"] == "辅料"), Decimal(0))
    bc = sum((dec(r["cost_batch"]) for r in rows["COST_PACKAGE"]), Decimal(0))
    expected = {"total_yl": raw * tax, "total_fl": fl * tax, "total_bc": bc * tax}
    expected["total_cost"] = sum(expected.values(), Decimal(0))
    for name, value in expected.items():
        assert close_to(master[name], value), (name, master[name], value)
    for entity, entity_rows in rows.items():
        for r in entity_rows:
            _log.info("单据 %s %s：DTLID %s 物料 %s %s 分类 %s 每片含量 %s 单价 %s 每批数量 %s 每批成本 %s", docid, entity, r["dtlid"],
                      r["goodsid"], r["goodsname"], r["dtl_useflag"], r["per_hl"], r["price"], r["batch_qty"], r["cost_batch"])
    _log.info("单据 %s 主表：TOTAL_YL %s TOTAL_FL %s TOTAL_BC %s TOTAL_COST %s（按规则算出 %s）", docid, master["total_yl"],
              master["total_fl"], master["total_bc"], master["total_cost"], {k: str(v) for k, v in expected.items()})


def command_record(engine: Engine, key: str) -> dict[str, Any]:
    [row] = fetch(engine, "SELECT STATUS, OPERATION, PAGE, AUDIT_DIFF FROM PF_COMMAND WHERE USER_ID = :u AND REQUEST_KEY = :k",
                  u=ADMIN.user_id, k=key)
    return row


# ---------------------------------------------------------------- 测试

def test_seed_operations_pass_validation_on_d_cg(engine: Engine, platform_for: Callable[[list[t.ConfigDraft]], Platform]) -> None:
    """C06 第 10 节：seed 的"由BOM生成明细"和测试的 `updateRows` 操作在 d_cg 的真实表结构上通过保存校验（SQL 交给 Oracle 解析，
    参数全部绑空值）。只读，不写配置。"""
    drafts = update_rows_for(None)
    rules = platform_for(drafts).config.rules
    validator = Validator(OracleSchemaInspector(engine), OracleSequences(), StaticDepartments([]), rules)
    with OracleUnitOfWorkFactory(engine).begin() as uow:
        problems = validator.check(uow, Catalog({}).merged(drafts), [("operation", BOM), ("operation", UPDATE_ROWS)])
    assert problems == []


def test_generate_from_bom_replaces_the_details_and_recalculates(
        engine: Engine, document: str, platform_for: Callable[[list[t.ConfigDraft]], Platform]) -> None:
    """选中新成本单点"由BOM生成明细"：原来的 12 行明细全部删掉；按产品 392 的 BOM 新增 11 行，物料、每片含量、单价、分类
    与旧 P_COST_BOM_INSERT 的查询相同（每片含量按 WP-15 保留 8 位小数）；名称由 Lookup 带出；每批数量、每批成本和主表合计
    由计算规则算出。命令一次提交，命令记录为 done、带审计差异。"""
    before = {r["dtlid"] for rows in detail_rows(engine, document).values() for r in rows}
    assert len(before) == 12
    platform = platform_for(seed_drafts())
    result = platform.press(BOM, [(PAGE, document)])
    assert result.outcome == "saved"

    rows = detail_rows(engine, document)
    after = [r for entity_rows in rows.values() for r in entity_rows]
    assert {r["dtlid"] for r in after}.isdisjoint(before)
    assert fetch(engine, "SELECT COUNT(*) AS N FROM T_COST_PINGGU_DTL WHERE DOCID = :d", d=int(document))[0]["n"] == 11
    assert len(rows["COST_MATERIAL"]) == 5 and len(rows["COST_PACKAGE"]) == 6

    old = fetch(engine, OLD_BOM_SQL, docid=int(document), tree=f"-{master_row(engine, document)['goodsid']}-%")
    expected = sorted(((int(r["goodsid"]), round8(r["per_hl"]), r["price"], r["dtl_useflag"]) for r in old), key=lambda x: x[0])
    actual = sorted(((int(r["goodsid"]), round8(r["per_hl"]), r["price"], r["dtl_useflag"]) for r in after), key=lambda x: x[0])
    assert actual == expected
    assert all(r["goodsname"] for r in after)
    check_recalculated(engine, document)

    written = {r.row_key: r for r in result.rows if isinstance(r, t.ResultRow)}
    assert written[document].entity == PAGE
    added = [r for r in result.rows if isinstance(r, t.ResultRow) and r.entity != PAGE]
    assert {r.row_key for r in added} == {str(r["dtlid"]) for r in after}
    assert {r.values["GOODSNAME"] for r in added} == {r["goodsname"] for r in after}  # 求值前按 Lookup 带出（WP-08）
    assert {r.row_key for r in result.rows if isinstance(r, t.DeletedRow)} == {str(k) for k in before}
    record = command_record(engine, platform.request_keys[-1])
    assert (record["status"], record["operation"], record["page"]) == ("done", BOM, PAGE)
    assert record["audit_diff"]


def test_update_rows_without_selection_sets_goods_price_and_recalculates(
        engine: Engine, document: str, platform_for: Callable[[list[t.ConfigDraft]], Platform]) -> None:
    """不选行点测试的 `updateRows` 按钮（SQL 只查这张新单据）：单价和物料清单参考价（T_COST_GOODS.PRICE）不同的明细改成参考价，
    这张单据按计算规则重算；来源单据 200721 不变。"""
    differ = ("SELECT D.DTLID, D.PRICE, G.PRICE AS GOODS_PRICE FROM {view} D JOIN T_COST_GOODS G ON G.GOODSID = D.GOODSID "
              "WHERE D.DOCID = :d AND G.USEFLAG NOT IN ('产成品', '半成品') AND DECODE(D.PRICE, G.PRICE, 0, 1) = 1")
    changed = [r for view in VIEWS.values() for r in fetch(engine, differ.format(view=view), d=int(document))]
    assert changed  # 200721 的明细单价有几行和参考价不同（例如硬脂酸镁 63 → 75）
    _log.info("单据 %s 单价与参考价不同的明细：%s", document,
              [(r["dtlid"], str(r["price"]), str(r["goods_price"])) for r in changed])
    total_before = master_row(engine, document)["total_cost"]
    source_before = fetch(engine, "SELECT DTLID, PRICE FROM T_COST_PINGGU_DTL WHERE DOCID = :d ORDER BY DTLID", d=SOURCE)

    platform = platform_for(update_rows_for(document))
    result = platform.press(UPDATE_ROWS)
    assert result.outcome == "saved"

    assert [r for view in VIEWS.values() for r in fetch(engine, differ.format(view=view), d=int(document))] == []
    prices = {r["dtlid"]: r["price"] for rows in detail_rows(engine, document).values() for r in rows}
    assert all(prices[r["dtlid"]] == r["goods_price"] for r in changed)
    check_recalculated(engine, document)
    assert master_row(engine, document)["total_cost"] != total_before
    assert {r.values["DOCID"] for r in result.rows if isinstance(r, t.ResultRow)} == {document}
    assert fetch(engine, "SELECT DTLID, PRICE FROM T_COST_PINGGU_DTL WHERE DOCID = :d ORDER BY DTLID", d=SOURCE) == source_before
    assert command_record(engine, platform.request_keys[-1])["status"] == "done"
