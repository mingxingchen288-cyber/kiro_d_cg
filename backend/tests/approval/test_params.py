"""SQL 审批人和人工参数（T-AP-4，AP-19、AP-20）：业务例子 E26、E27。"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from cost_platform.contracts import types as t

from .support import ADMIN, BUYER, SEED, YANGNA, Harness, cost, modify


# ---------------------------------------------------------------- E26：审批人为 SQL

MANAGER_SQL = "SELECT USER_ID FROM T_DEPT_MANAGER WHERE DEPT_ID = :dept"


def _sql_flow() -> t.ConfigDraft:
    """第 1 级的审批人按部门查出主管。成本单没有部门字段，这里按发起人员的部门（`user_departmentId`）查，说明用的假设。"""
    return t.ConfigDraft(type="approvalFlow", key="DEPT_MANAGER", name="部门主管审批", content={
        "page": "COST_PINGGU", "order": 1, "operations": {"COST_MATERIAL": ["modify"]},
        "levels": [{"level": 1, "nodes": [{"name": "主管审批", "conditionType": "always", "mode": "or",
                                           "approvers": [{"type": "sql", "sql": MANAGER_SQL, "binds": {"dept": "user_departmentId"}}]}]}],
        "notify": [{"event": "submitted", "to": "levelApprovers"}],
    })


def _managers(h: Harness, table: dict[str, list[str]]) -> None:
    h.sql.queries["FROM T_DEPT_MANAGER"] = lambda b: [{"USER_ID": u} for u in table.get(str(b["dept"]), [])]
    h.directory.add_account(t.AccountRef("9", "u9", "已停用主管", "10", False), ["COST"])


def test_e26_only_enabled_manager_gets_the_task() -> None:
    h = Harness([], extra_flows=[_sql_flow()])
    _managers(h, {"10": ["1", "9"]})
    run = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206325, MEMO="改"))])
    [approval] = run.state.approvals
    [node] = h.record(approval.approval_id).progress.nodes
    assert [(m.kind, m.id) for m in node.members] == [("user", "1")]
    assert [n.recipients for n in run.state.notifications] == [("1",)]
    assert h.service.list(h.config.ctx(ADMIN), "todo", 0, 50).total == 1
    statement, binds = next(s for s in h.sql.statements if "T_DEPT_MANAGER" in s[0])
    assert statement == MANAGER_SQL and binds == {"dept": "10"}


def test_e26_no_manager_rejects_the_save() -> None:
    h = Harness([], extra_flows=[_sql_flow()])
    _managers(h, {"10": ["9"]})
    with pytest.raises(t.PlatformError) as caught:
        h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206325, MEMO="改"))])
    assert caught.value.code is t.ErrorCode.VALIDATION_FAILED
    assert "第 1 级节点“主管审批”" in caught.value.message
    assert h.frozen() == set() and h.world.row("T_COST_PINGGU_DTL", 206325)["MEMO"] is None  # type: ignore[index]


# ---------------------------------------------------------------- E27：第 1 级人工参数，最终批准时写入

def _with_effective_date() -> dict[str, Any]:
    content = json.loads((SEED / "entity.COST_PINGGU.json").read_text(encoding="utf-8"))["content"]
    field = {"name": "EFFECTIVE_DATE", "column": "EFFECTIVE_DATE", "label": "生效日期", "type": "date", "source": "own", "role": "input"}
    return {"fields": [*content["fields"], field]}


def _param_flow() -> t.ConfigDraft:
    """两级审批流；参数 effectiveDate 为第 1 级人工参数；一个 hidden 的块找到来源单据本身，把参数写到生效日期。"""
    return t.ConfigDraft(type="approvalFlow", key="EFFECTIVE", name="生效日期审批", content={
        "page": "COST_PINGGU", "order": 1, "operations": {"COST_MATERIAL": ["modify"]},
        "levels": [{"level": 1, "nodes": [{"name": "管理员审批", "conditionType": "always", "mode": "or",
                                           "approvers": [{"type": "role", "role": "ADMIN"}]}]},
                   {"level": 2, "nodes": [{"name": "采购复核", "conditionType": "always", "mode": "or",
                                           "approvers": [{"type": "role", "role": "008"}]}]}],
        "display": [{"key": "self", "title": "生效日期", "region": "affected", "source": "T_COST_PINGGU", "condition": "DOCID = :billId",
                     "columns": [{"field": "DOCID", "label": "单据号"}], "selection": "hidden",
                     "actions": [{"action": "updateFields", "fields": [{"column": "EFFECTIVE_DATE", "value": ":params_effectiveDate"}]}]}],
        "params": [{"name": "effectiveDate", "label": "生效日期", "type": "date", "source": "manual", "required": True, "level": 1}],
    })


def _e27() -> tuple[Harness, str]:
    h = Harness([], extra_flows=[_param_flow()], entity_overrides={"COST_PINGGU": _with_effective_date()})
    [approval] = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206325, MEMO="随审批"))]).state.approvals
    return h, approval.approval_id


def test_e27_level_one_must_fill_the_parameter() -> None:
    h, approval_id = _e27()
    detail = h.detail(ADMIN, approval_id)
    assert [(p.name, p.required, p.level) for p in detail.params] == [("effectiveDate", True, 1)]
    with pytest.raises(t.PlatformError) as caught:
        h.pass_(ADMIN, approval_id)
    assert caught.value.code is t.ErrorCode.VALIDATION_FAILED
    assert caught.value.details[0].field == "effectiveDate"


def test_e27_written_only_when_approval_ends() -> None:
    h, approval_id = _e27()
    h.pass_(ADMIN, approval_id, params={"effectiveDate": "2026-11-01"})
    master = h.world.row("T_COST_PINGGU", 2550)
    assert master.get("EFFECTIVE_DATE") is None and h.world.row("T_COST_PINGGU_DTL", 206325)["MEMO"] is None  # type: ignore[union-attr,index]
    assert h.record(approval_id).params == {"1": {"effectiveDate": "2026-11-01"}}
    h.pass_(BUYER, approval_id)
    assert h.world.row("T_COST_PINGGU", 2550)["EFFECTIVE_DATE"] == date(2026, 11, 1)  # type: ignore[index]
    assert h.world.row("T_COST_PINGGU_DTL", 206325)["MEMO"] == "随审批"  # type: ignore[index]


def test_e27_second_level_reject_writes_nothing() -> None:
    h, approval_id = _e27()
    h.pass_(ADMIN, approval_id, params={"effectiveDate": "2026-11-01"})
    h.reject(BUYER, approval_id, "不同意")
    assert h.world.row("T_COST_PINGGU", 2550).get("EFFECTIVE_DATE") is None  # type: ignore[union-attr]
    assert h.world.row("T_COST_PINGGU_DTL", 206325)["MEMO"] is None  # type: ignore[index]
    assert h.frozen() == set()
