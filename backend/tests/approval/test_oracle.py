"""approval 的真实验证（d_cg）：审批流 SQL 片段按 C06 7.2 包装后经 `UnitOfWork` 执行，以及审批存储。本次没有运行，由合并后统一运行。

数据按业务例子 E37：成本单 2550（250mg乙酰唑胺片）的原辅料 206323 聚维酮K30（物料 25），单价 75 → 90；
206326 玉米淀粉（310）换成微晶纤维素（13165）、带出单价 40；206325 硬脂酸镁（115）只改备注
（`.reports/modules/approval/01-e37-data.out.txt` 为 2026-10-29 在 d_cg 上查到的值）。

前提：
- 已执行 `platform db upgrade`（含 approval 的 ap_0001：PF_APPROVAL* 表和 PF_APPROVAL_SEQ）；
- d_cg 中有 C06 7.8 的展示视图 T_COST_GOODS_PRICE_V（2026-10-29 查询时还没有，见 contract-gaps.md 第 6 条）。

每个测试只在一个不提交的事务中执行，结束时回滚，不留下数据；取审批编号会消耗 PF_APPROVAL_SEQ 的一个值。
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import ExitStack
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from cost_platform.approval import ApprovalDeps, create_approval
from cost_platform.approval.freeze import ApprovalFreezeReader
from cost_platform.approval.rows import owners
from cost_platform.approval.sql import RowScope, UowSqlRunner, binds_for, display_sql, exists, freeze_sql, key_text, scalar
from cost_platform.approval.store import ApprovalStore
from cost_platform.assembly.settings import Settings
from cost_platform.contracts import types as t
from cost_platform.db_core.engine import OracleUnitOfWorkFactory, create_oracle_engine

from ..contracts.test_freeze_reader import FreezeReaderContract
from .support import ADMIN, YANGNA, Config, c06_flows, directory, schema

pytestmark = pytest.mark.oracle

D = Decimal
FLOWS = {code: t.parse_config_content("approvalFlow", item.content) for code, item in c06_flows().items()}
COST_TO_GOODS: t.ApprovalFlowConfig = FLOWS["COST_TO_GOODS"]  # type: ignore[assignment]
TECH: t.ApprovalFlowConfig = FLOWS["TECH_CUSTOMER_MATERIAL"]  # type: ignore[assignment]
GOODS_TO_COST: t.ApprovalFlowConfig = FLOWS["GOODS_TO_COST"]  # type: ignore[assignment]
MASTER_2550 = {"DOCID": D(2550), "GOODSNAME": "250mg乙酰唑胺片", "USESTATUS": "商业化"}


@pytest.fixture(scope="module")
def engine() -> Engine:
    s = Settings.load()
    return create_oracle_engine(s.db_user, s.db_password, s.db_dsn)


@pytest.fixture
def uow(engine: Engine) -> Iterator[object]:
    with OracleUnitOfWorkFactory(engine).begin() as unit:  # 不提交，退出时回滚
        yield unit


def row(op: str, new: dict, old: dict, master_old: dict | None = None) -> RowScope:
    master = master_old or MASTER_2550
    return RowScope(op, new, old, master, master, D(2550), YANGNA.user_id, YANGNA.department)  # type: ignore[arg-type]


K30 = row("modify", {"DTLID": D(206323), "GOODSID": D(25), "PRICE": D(90)}, {"DTLID": D(206323), "GOODSID": D(25), "PRICE": D(75)})
CORN = row("modify", {"DTLID": D(206326), "GOODSID": D(13165), "PRICE": D(40)}, {"DTLID": D(206326), "GOODSID": D(310), "PRICE": D(22)})
MEMO = row("modify", {"DTLID": D(206325), "GOODSID": D(115), "PRICE": D(63), "MEMO": "改备注"},
           {"DTLID": D(206325), "GOODSID": D(115), "PRICE": D(63), "MEMO": None})


def level(flow: t.ApprovalFlowConfig, k: int) -> str:
    return next(lv for lv in flow.levels if lv.level == k).nodes[0].condition or ""


# ---------------------------------------------------------------- C06 7.8 的片段（E37）

def test_e37_level_one_only_k30_triggers(uow: object) -> None:
    runner = UowSqlRunner()
    condition = level(COST_TO_GOODS, 1)
    assert exists(runner, uow, condition, K30)  # type: ignore[arg-type]
    assert not exists(runner, uow, condition, CORN)  # type: ignore[arg-type]  40 和清单价 40 相同
    assert not exists(runner, uow, condition, MEMO)  # type: ignore[arg-type]


def test_e37_level_two_countersign_only_above_82_5(uow: object) -> None:
    runner = UowSqlRunner()
    condition = level(COST_TO_GOODS, 2)
    assert exists(runner, uow, condition, K30)  # type: ignore[arg-type]  90 > 82.5
    eighty = row("modify", {"GOODSID": D(25), "PRICE": D(80)}, {"GOODSID": D(25), "PRICE": D(75)})
    assert not exists(runner, uow, condition, eighty)  # type: ignore[arg-type]


def test_e37_freeze_and_display_find_goods_25(uow: object) -> None:
    runner = UowSqlRunner()
    item = COST_TO_GOODS.freeze[0]
    statement = freeze_sql(item.table, ["GOODSID"], item.condition)
    assert [key_text(r["GOODSID"]) for r in runner.rows(uow, statement, binds_for(statement, K30))] == ["25"]  # type: ignore[arg-type]
    block = next(b for b in COST_TO_GOODS.display if b.region == "affected")
    statement = display_sql(block.source, block.condition or "")
    [found] = runner.rows(uow, statement, binds_for(statement, K30))  # type: ignore[arg-type]
    assert (key_text(found["GOODSID"]), found["GOODSNAME"], found["ZX_PRICE"]) == ("25", "聚维酮K30", D(75))


def test_e37_value_is_new_price(uow: object) -> None:
    block = next(b for b in COST_TO_GOODS.display if b.region == "affected")
    action = block.actions[0]
    assert isinstance(action, t.UpdateFields)
    assert scalar(UowSqlRunner(), uow, action.fields[0].value, K30) == D(90)  # type: ignore[arg-type]


# ---------------------------------------------------------------- C06 7.9、7.10 的片段

def test_e41_customer_specified_condition(uow: object) -> None:
    condition = level(TECH, 1)
    evaluating = {**MASTER_2550, "USESTATUS": "评估中"}
    deleted = row("delete", {}, {"GOODSID": D(115), "CUSTOMER_SPECIFIED": True}, evaluating)
    changed = row("modify", {"GOODSID": D(13165), "CUSTOMER_SPECIFIED": True}, {"GOODSID": D(115), "CUSTOMER_SPECIFIED": True}, evaluating)
    plain = row("modify", {"GOODSID": D(13165), "CUSTOMER_SPECIFIED": False}, {"GOODSID": D(310), "CUSTOMER_SPECIFIED": False}, evaluating)
    runner = UowSqlRunner()
    assert exists(runner, uow, condition, deleted)  # type: ignore[arg-type]
    assert exists(runner, uow, condition, changed)  # type: ignore[arg-type]
    assert not exists(runner, uow, condition, plain)  # type: ignore[arg-type]
    assert not exists(runner, uow, condition, row("delete", {}, {"GOODSID": D(115), "CUSTOMER_SPECIFIED": True}))  # type: ignore[arg-type]


def test_e39_freeze_finds_99_cost_documents(uow: object) -> None:
    """7.10：物料清单 25 改执行价，冻结节点找到含 25 的成本单（d_cg 中 99 张），明细按 parentKey 归到所属成本单。"""
    goods = RowScope("modify", {"GOODSID": D(25), "ZX_PRICE": D(80), "PRICE": D(75)}, {"GOODSID": D(25), "ZX_PRICE": D(75), "PRICE": D(75)},
                     {}, {}, D(25), YANGNA.user_id, YANGNA.department)
    runner = UowSqlRunner()
    item = GOODS_TO_COST.freeze[0]
    statement = freeze_sql(item.table, ["DTLID"], item.condition)
    keys = [key_text(r["DTLID"]) for r in runner.rows(uow, statement, binds_for(statement, goods))]  # type: ignore[arg-type]
    assert {"206323", "103681"} <= set(keys)
    config = Config(["GOODS_TO_COST"])
    found = owners(runner, uow, config.catalog, "T_COST_PINGGU_DTL", keys)  # type: ignore[arg-type]
    documents = {o.document.record_key for o in found.values()}
    assert {"2550", "2556"} <= documents and len(documents) == 99
    action = next(b for b in GOODS_TO_COST.display if b.key == "costMaterial").actions[0]
    assert isinstance(action, t.UpdateFields)
    assert scalar(runner, uow, action.fields[0].value, goods) == D(80)  # type: ignore[arg-type]


# ---------------------------------------------------------------- 触发审批阶段在 d_cg 上跑 E37 的提交

def test_e37_trigger_stage_on_d_cg(engine: Engine, uow: object) -> None:
    """用 d_cg 中成本单 2550 的当前数据跑触发审批阶段：只有 206323 触发；冻结 2550 和物料清单 25；物料清单一块只有 25。"""
    config = Config(["COST_TO_GOODS"])
    entity = config.entities["COST_MATERIAL"]
    connection = uow.connection  # type: ignore[attr-defined]
    rows = connection.execute(text("SELECT * FROM V_COST_PINGGU_MATERIAL WHERE DOCID = 2550 ORDER BY DTLID")).mappings().all()
    ref = t.DocumentRef("COST_PINGGU", "2550")
    details = [t.Row("COST_MATERIAL", key_text(r["dtlid"]), None,
                     {f.name: (D(r[f.name.lower()]) if isinstance(r[f.name.lower()], int) and not isinstance(r[f.name.lower()], bool)
                               else r[f.name.lower()]) for f in entity.fields if f.name.lower() in r}) for r in rows]
    current = t.DocumentData(ref, t.Row("COST_PINGGU", "2550", None, dict(MASTER_2550)), {"COST_MATERIAL": details, "COST_PACKAGE": []})
    candidate = copy.deepcopy(current)
    edits = {"206323": {"PRICE": D(90)}, "206326": {"GOODSID": D(13165), "PRICE": D(40)}, "206325": {"MEMO": "改备注"}}
    changes = []
    for item in candidate.details["COST_MATERIAL"]:
        if item.row_key in edits:
            old = {k: item.values.get(k) for k in edits[item.row_key]}
            item.values.update(edits[item.row_key])
            changes.append(t.RowChange(ref, "COST_MATERIAL", "modify", item.row_key, None, edits[item.row_key], old))
    command = t.parse_wire(t.Command, {"requestKey": "00000000-0000-4000-8000-0000000000d1", "page": "COST_PINGGU",
                                       "operation": "COST_PINGGU.save", "params": {}, "documents": [{
                                           "entity": "COST_PINGGU", "master": {"op": "none", "rowKey": "2550"},
                                           "details": [{"entity": "COST_MATERIAL", "op": "modify", "rowKey": k,
                                                        "changes": {f: str(v) for f, v in e.items()}} for k, e in edits.items()]}]})
    state = t.CommandState(command=command, involved=[ref], current={ref: current}, candidate={ref: candidate},
                           changes=t.ChangePlan(rows=changes))
    deps = ApprovalDeps(catalog=lambda ctx: config.catalog, schema=schema(), directory=directory(), documents=None)  # type: ignore[arg-type]
    approval = create_approval(deps)
    ctx = config.ctx(YANGNA, now=datetime(2026, 10, 29, 10, 0, 0))
    approval.trigger.run(uow, state, ctx)  # type: ignore[arg-type]
    [submitted] = state.approvals
    assert state.outcome == "approvalSubmitted" and state.pending_documents == {ref}
    store = ApprovalStore()
    record = store.load(uow, submitted.approval_id)  # type: ignore[arg-type]
    assert record is not None
    assert {r.row_key: r.flows for r in record.triggers} == {"206323": ["COST_TO_GOODS"], "206326": [], "206325": []}
    assert {(e.table, e.record_key) for e in store.freezes_of(uow, submitted.approval_id)} == {("T_COST_PINGGU", "2550"),  # type: ignore[arg-type]
                                                                                             ("T_COST_GOODS", "25")}
    assert [(a.block, a.key) for a in store.affected(uow, submitted.approval_id)] == [("goods", "25")]  # type: ignore[arg-type]
    assert state.notifications[0].recipients == (ADMIN.user_id,)


# ---------------------------------------------------------------- 审批存储（PF_APPROVAL*）

class OracleFreezeHarness:
    def __init__(self, engine: Engine) -> None:
        self._stack = ExitStack()
        self.uow = self._stack.enter_context(OracleUnitOfWorkFactory(engine).begin())
        self.store = ApprovalStore()
        self.reader = ApprovalFreezeReader(self.store)

    def freeze(self, entry: t.FreezeEntry) -> None:
        self.store.freeze(self.uow, [entry])

    def close(self) -> None:
        self._stack.close()  # 不提交，回滚


class TestOracleFreezeReader(FreezeReaderContract):
    @pytest.fixture
    def harness(self, engine: Engine) -> Iterator[OracleFreezeHarness]:
        harness = OracleFreezeHarness(engine)
        yield harness
        harness.close()


def test_freeze_unique_on_oracle(engine: Engine) -> None:
    harness = OracleFreezeHarness(engine)
    harness.freeze(t.FreezeEntry("990001", "T_COST_PINGGU", "2550"))
    with pytest.raises(t.PlatformError) as caught:
        harness.freeze(t.FreezeEntry("990002", "T_COST_PINGGU", "2550"))
    harness.close()
    assert caught.value.code is t.ErrorCode.FROZEN_BY_APPROVAL
