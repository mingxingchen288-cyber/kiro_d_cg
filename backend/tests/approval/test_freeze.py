"""冻结判断和"单据只属于一个审批"（工程约定第 5 节，T-AP-2）：AP-03、AP-06，C06 7.4，业务例子 E16、E21、E22、E35、E37。

冻结记录按（根表、主键）登记；注册过的表冻结所属的整张单据（明细按 parentKey 归到主单），没注册的表只冻结查到的那一行。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack

import pytest

from cost_platform.approval.freeze import ApprovalFreezeReader, FreezeCheckStage
from cost_platform.approval.store import ApprovalStore
from cost_platform.approval.tables import metadata
from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeUnitOfWorkFactory

from ..contracts.test_freeze_reader import FreezeReaderContract
from .support import ADMIN, TECH, YANGNA, Config, Harness, cost, goods, modify


# ---------------------------------------------------------------- FreezeReader 的契约测试（C08 第 13 节）

class StoreFreezeHarness:
    def __init__(self) -> None:
        self._stack = ExitStack()
        factory = FakeUnitOfWorkFactory()
        metadata.create_all(factory.engine)
        self.uow = self._stack.enter_context(factory.begin())
        self.store = ApprovalStore()
        self.reader = ApprovalFreezeReader(self.store)

    def freeze(self, entry: t.FreezeEntry) -> None:
        self.store.freeze(self.uow, [entry])

    def close(self) -> None:
        self._stack.close()


class TestApprovalFreezeReader(FreezeReaderContract):
    @pytest.fixture
    def harness(self) -> Iterator[StoreFreezeHarness]:
        harness = StoreFreezeHarness()
        yield harness
        harness.close()


def test_same_data_cannot_be_frozen_twice() -> None:
    """冻结记录按（根表、主键）唯一：后写入的命令因唯一约束失败，返回 409 FROZEN_BY_APPROVAL（AP-06）。"""
    harness = StoreFreezeHarness()
    harness.freeze(t.FreezeEntry("203", "T_COST_PINGGU", "2550"))
    with pytest.raises(t.PlatformError) as caught:
        harness.freeze(t.FreezeEntry("204", "T_COST_PINGGU", "2550"))
    harness.close()
    assert caught.value.code is t.ErrorCode.FROZEN_BY_APPROVAL


# ---------------------------------------------------------------- 冻结检查阶段

def _stage_case(origin: t.Origin | None = None) -> tuple[StoreFreezeHarness, FreezeCheckStage, t.CommandState, t.ExecutionContext]:
    harness = StoreFreezeHarness()
    harness.freeze(t.FreezeEntry("203", "T_COST_PINGGU", "2550"))
    harness.freeze(t.FreezeEntry("203", "T_COST_GOODS", "25"))
    command = t.parse_wire(t.Command, {"requestKey": "00000000-0000-4000-8000-000000000001", "page": "COST_PINGGU",
                                       "operation": "COST_PINGGU.save", "documents": [], "params": {}})
    state = t.CommandState(command=command)
    ctx = Config().ctx(TECH, origin=origin)
    return harness, FreezeCheckStage(harness.store), state, ctx


def test_frozen_document_is_rejected_with_approval() -> None:
    harness, stage, state, ctx = _stage_case()
    state.involved = [t.DocumentRef("COST_PINGGU", "2556"), t.DocumentRef("COST_PINGGU", "2550")]
    with pytest.raises(t.PlatformError) as caught:
        stage.run(harness.uow, state, ctx)
    harness.close()
    assert caught.value.code is t.ErrorCode.FROZEN_BY_APPROVAL
    [detail] = caught.value.details
    assert (detail.entity, detail.row_key, detail.approval_id) == ("COST_PINGGU", "2550", "203")


def test_single_table_row_is_checked_by_its_table() -> None:
    """物料清单是单表页：冻结的是 T_COST_GOODS 的这一行。"""
    harness, stage, state, ctx = _stage_case()
    state.involved = [t.DocumentRef("COST_GOODS_PRICE", "25")]
    with pytest.raises(t.PlatformError) as caught:
        stage.run(harness.uow, state, ctx)
    state.involved = [t.DocumentRef("COST_GOODS_PRICE", "115")]
    stage.run(harness.uow, state, ctx)
    harness.close()
    assert caught.value.details[0].approval_id == "203"


def test_own_approval_may_write_its_frozen_data() -> None:
    """来源为本审批的命令可以写本审批冻结的数据（AP-03）。"""
    harness, stage, state, ctx = _stage_case(t.Origin(kind="approval", approval_id="203"))
    state.involved = [t.DocumentRef("COST_PINGGU", "2550"), t.DocumentRef("COST_GOODS_PRICE", "25")]
    stage.run(harness.uow, state, ctx)
    harness.close()


def test_other_approval_origin_is_still_rejected() -> None:
    harness, stage, state, ctx = _stage_case(t.Origin(kind="approval", approval_id="999"))
    state.involved = [t.DocumentRef("COST_PINGGU", "2550")]
    with pytest.raises(t.PlatformError):
        stage.run(harness.uow, state, ctx)
    harness.close()


# ---------------------------------------------------------------- 提交时登记冻结（E37、E35）

def e37_save(h: Harness, price: str = "90") -> t.ApprovalRef:
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206323, PRICE=price),
                                              modify("COST_MATERIAL", 206326, GOODSID="13165", PRICE="40"),
                                              modify("COST_MATERIAL", 206325, MEMO="改备注"))])
    [approval] = run.state.approvals
    return approval


def test_e37_freezes_cost_2550_and_goods_25_only() -> None:
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h)
    assert h.frozen() == {("T_COST_PINGGU", "2550"), ("T_COST_GOODS", "25")}
    assert approval.document == t.RecordRef(entity="COST_PINGGU", record_key="2550")


def test_e37_frozen_data_rejects_other_users_but_not_unfrozen() -> None:
    """审批期间：修改 2550 的任何一行、物料清单 25 都返回 FROZEN_BY_APPROVAL；物料清单 13165、115 照常可以修改。"""
    h = Harness(["COST_TO_GOODS"], register_goods=True)
    approval = e37_save(h)
    for documents in ([cost(2550, master={"MEMO": "随便改"})], [cost(2550, modify("COST_MATERIAL", 206325, MEMO="再改"))]):
        with pytest.raises(t.PlatformError) as caught:
            h.save(ADMIN, "COST_PINGGU", documents)
        assert caught.value.code is t.ErrorCode.FROZEN_BY_APPROVAL
        assert caught.value.details[0].approval_id == approval.approval_id
    with pytest.raises(t.PlatformError) as caught:
        h.save(ADMIN, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="70")])
    assert caught.value.details[0].approval_id == approval.approval_id
    h.save(ADMIN, "GOODS_PRICE_MANAGE", [goods(13165, ZX_PRICE="41")])
    h.save(ADMIN, "GOODS_PRICE_MANAGE", [goods(115, ZX_PRICE="64")])
    assert h.world.row("T_COST_GOODS", 13165)["ZX_PRICE"] == 41  # type: ignore[index]


def test_e22_new_detail_on_frozen_document_is_rejected() -> None:
    """审批结束前，另一个用户在冻结的单据上新增或删除明细，都返回 FROZEN_BY_APPROVAL。"""
    h = Harness(["COST_TO_GOODS"])
    e37_save(h)
    add = {"entity": "COST_MATERIAL", "op": "add", "clientRowId": "tmp-00000000-0000-4000-8000-0000000000f1",
           "values": {"GOODSID": "116", "PRICE": "12", "BATCH_QTY": "1"}}
    delete = {"entity": "COST_MATERIAL", "op": "delete", "rowKey": "206325"}
    for detail in (add, delete):
        with pytest.raises(t.PlatformError) as caught:
            h.save(ADMIN, "COST_PINGGU", [cost(2550, detail)])
        assert caught.value.code is t.ErrorCode.FROZEN_BY_APPROVAL


def test_e35_goods_price_change_freezes_goods_and_cost_documents() -> None:
    """7.10：物料清单 25 改执行价，冻结节点找到含 25 的成本单 2550、2556，都在保存的同一个事务中整单冻结。"""
    h = Harness(["GOODS_TO_COST"])
    run = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")])
    [approval] = run.state.approvals
    assert h.frozen() == {("T_COST_GOODS", "25"), ("T_COST_PINGGU", "2550"), ("T_COST_PINGGU", "2556")}
    with pytest.raises(t.PlatformError) as caught:
        h.save(ADMIN, "COST_PINGGU", [cost(2556, modify("COST_MATERIAL", 103681, MEMO="改"))])
    assert caught.value.details[0].approval_id == approval.approval_id


def test_freeze_released_after_reject() -> None:
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h)
    h.reject(ADMIN, approval.approval_id, "价格偏高")
    assert h.frozen() == set()
    h.save(ADMIN, "COST_PINGGU", [cost(2550, master={"MEMO": "驳回后可以改"})])


# ---------------------------------------------------------------- 同一份数据只属于一个审批（AP-06、E16）

def _second_cost_with_two_goods(h: Harness) -> None:
    """成本单 2601 同时含物料 115、116（说明用的假设数据）。"""
    from .support import _dtl
    h.world.add_cost(2601, "说明用成本单", [_dtl(260101, 2601, 115, "63", "1"), _dtl(260102, 2601, 116, "12", "1")])


def test_e16_document_frozen_by_other_approval_blocks_new_approval() -> None:
    """115 的改价审批 X 冻结了成本单 2601；另一个用户改 116，冻结节点也找到 2601：保存返回 FROZEN_BY_APPROVAL，指出 2601 被 X
    冻结，116 不变，不生成审批；X 结束后再保存可以发起审批。"""
    h = Harness(["GOODS_TO_COST"])
    _second_cost_with_two_goods(h)
    [x] = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(115, ZX_PRICE="60")]).state.approvals
    with pytest.raises(t.PlatformError) as caught:
        h.save(ADMIN, "GOODS_PRICE_MANAGE", [goods(116, ZX_PRICE="13")])
    assert caught.value.code is t.ErrorCode.FROZEN_BY_APPROVAL
    assert [(d.row_key, d.approval_id) for d in caught.value.details] == [("2601", x.approval_id)]
    assert h.world.row("T_COST_GOODS", 116)["ZX_PRICE"] is None  # type: ignore[index]
    assert h.frozen() == {("T_COST_GOODS", "115"), ("T_COST_PINGGU", "2601"), ("T_COST_PINGGU", "2550")}
    h.reject(ADMIN, x.approval_id, "价格偏高")
    [y] = h.save(ADMIN, "GOODS_PRICE_MANAGE", [goods(116, ZX_PRICE="13")]).state.approvals
    assert y.approval_id != x.approval_id


def test_e16_two_approvals_in_one_save_freezing_same_document() -> None:
    """没有未结束的审批时，物料清单页一次保存同时修改 115 和 116，两者都找到 2601：整次保存返回 FROZEN_BY_APPROVAL，不生成审批。"""
    h = Harness(["GOODS_TO_COST"])
    _second_cost_with_two_goods(h)
    with pytest.raises(t.PlatformError) as caught:
        h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(115, ZX_PRICE="60"), goods(116, ZX_PRICE="13")])
    assert caught.value.code is t.ErrorCode.FROZEN_BY_APPROVAL
    assert [d.row_key for d in caught.value.details] == ["2601"]
    assert h.frozen() == set()
    assert h.world.row("T_COST_GOODS", 115)["ZX_PRICE"] is None  # type: ignore[index]
    with h.uow.begin() as uow:
        assert h.store.pending(uow) == []


def test_e21_two_goods_without_shared_cost_make_two_approvals() -> None:
    """物料清单页一次保存修改 115 和 116（两者没有共用的成本单）：生成两个审批，来源单据号分别为 115 和 116；修改 115 的任何字段
    返回 FROZEN_BY_APPROVAL，其他物料照常修改；驳回 115 的审批后，116 的审批照常处理。"""
    h = Harness(["GOODS_TO_COST"])
    run = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(115, ZX_PRICE="60"), goods(116, ZX_PRICE="13")])
    first, second = run.state.approvals
    assert (first.document.record_key, second.document.record_key) == ("115", "116")
    assert run.state.outcome == "approvalSubmitted"
    with pytest.raises(t.PlatformError) as caught:
        h.save(ADMIN, "GOODS_PRICE_MANAGE", [goods(115, GOODSNAME="改名")])
    assert caught.value.details[0].approval_id == first.approval_id
    h.save(ADMIN, "GOODS_PRICE_MANAGE", [goods(13165, ZX_PRICE="41")])
    h.reject(ADMIN, first.approval_id, "价格偏高")
    h.pass_(ADMIN, second.approval_id)
    assert h.world.row("T_COST_GOODS", 116)["ZX_PRICE"] == 13  # type: ignore[index]
    assert h.world.row("T_COST_GOODS", 115)["ZX_PRICE"] is None  # type: ignore[index]
