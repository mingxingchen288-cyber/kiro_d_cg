"""强制审批检查（T-AP-4，AP-18）：业务例子 E25。

物料表规则"ISERP=1 时修改 ZX_PRICE 必须审批"，只允许从物料清单页（GOODS_PRICE_MANAGE）提交审批。
"""

from __future__ import annotations

import pytest

from cost_platform.contracts import types as t

from .support import ADMIN, YANGNA, D, Harness, goods
from .test_freeze import e37_save

RULE = {"approvalRequired": [{"fields": ["ZX_PRICE"], "when": {"logic": "AND", "conditions": [{"field": "ISERP", "op": "eq", "value": "1"}]},
                              "sourcePages": ["GOODS_PRICE_MANAGE"]}]}


def test_e25_goods_page_with_hit_flow_enters_approval() -> None:
    h = Harness(["GOODS_TO_COST"], entity_overrides={"COST_GOODS_PRICE": RULE})
    run = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")])
    assert run.state.outcome == "approvalSubmitted"


def test_e25_no_entry_satisfied_returns_approval_required() -> None:
    """所有审批流的第 1 级入口都不满足（这里没有审批流命中）时，保存返回 APPROVAL_REQUIRED，什么都不写。"""
    h = Harness([], register_goods=True, entity_overrides={"COST_GOODS_PRICE": RULE})
    with pytest.raises(t.PlatformError) as caught:
        h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")])
    assert caught.value.code is t.ErrorCode.APPROVAL_REQUIRED
    [detail] = caught.value.details
    assert (detail.entity, detail.row_key, detail.field) == ("COST_GOODS_PRICE", "25", "ZX_PRICE")
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] is None  # type: ignore[index]


def test_e25_local_goods_row_is_not_required() -> None:
    """ISERP 不为 1 的本地物料行不命中规则，照常保存。"""
    h = Harness([], register_goods=True, entity_overrides={"COST_GOODS_PRICE": RULE})
    h.world.tables["T_COST_GOODS"]["115"]["ISERP"] = "0"
    run = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(115, ZX_PRICE="60")])
    assert run.state.outcome == "saved" and h.world.row("T_COST_GOODS", 115)["ZX_PRICE"] == 60  # type: ignore[index]


def test_e25_other_page_writing_the_field_is_rejected() -> None:
    """从成本核算页的按钮直接改这个字段（命令来自别的页面、没有进入审批），同样返回 APPROVAL_REQUIRED。"""
    h = Harness([], register_goods=True, entity_overrides={"COST_GOODS_PRICE": RULE})
    ref = t.DocumentRef("COST_GOODS_PRICE", "25")
    command = t.parse_wire(t.Command, {"requestKey": "00000000-0000-4000-8000-0000000000b1", "page": "COST_PINGGU",
                                       "operation": "COST_PINGGU.syncPrice", "documents": [], "params": {}})
    state = t.CommandState(command=command)
    state.changes = t.ChangePlan(rows=[t.RowChange(ref, "COST_GOODS_PRICE", "modify", "25", None, {"ZX_PRICE": D("80")},
                                                   {"ZX_PRICE": D("75")})])
    current = h.world.load(ref)
    assert current is not None
    state.current[ref] = current
    with h.uow.begin() as uow, pytest.raises(t.PlatformError) as caught:
        h.approval.required.run(uow, state, h.ctx(ADMIN))
    assert caught.value.code is t.ErrorCode.APPROVAL_REQUIRED


def test_e25_approved_write_is_not_blocked() -> None:
    """场景一批准后，审批流的操作写物料 25 的 ZX_PRICE 不被拦（执行上下文的来源为审批）。"""
    h = Harness(["COST_TO_GOODS"], register_goods=True, entity_overrides={"COST_GOODS_PRICE": RULE})
    approval = e37_save(h, "80")
    h.pass_(ADMIN, approval.approval_id)
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] == 80  # type: ignore[index]
