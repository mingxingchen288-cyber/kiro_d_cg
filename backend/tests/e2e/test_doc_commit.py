"""按单据提交（真实联调，d_cg + Redis；C02 v10 第 1 节，用户 2026-10-31："100个单据 失败了1个，就全部失败"是不可以的）。
后端为 conftest 的进程 A（servers.py）。

1. 一张被规则拒绝：admin 在成本核算页同时改了两张单据后保存：成本单 200680 主表备注改为"按单据提交"，成本单 2550 的
   预胶化淀粉（206324）每片含量改成 0。2550 被规则 R_MAT_PER_HL_GT0 拒绝（RULE_REJECTED），记入 `failed`，主表、明细都
   不变；200680 照常保存，整个请求返回 200。改回 200680 后把第一次的请求原样重发：200680 已提交，按命令记录返回原结果、
   不再写库；2550 重新执行，仍被拒绝。
2. 一张在审批中（AP-06）：chengben01 把 2550 的聚维酮K30（206323）单价 75 改成 90，进入审批 COST_TO_GOODS，2550 被冻结；
   admin 再同时改 2550 和 200680 的主表备注保存：2550 被冻结拒绝（FROZEN_BY_APPROVAL），200680 照常保存。最后驳回审批。

结束时 200680 恢复原值；测试产生的审批、命令记录在结束时删掉（dcg.Cleanup，命令记录按各张单据的子请求键）。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine

from .dcg import PAGE, Cleanup, detail_change, document, save_command
from .servers import Backend, Browser

pytestmark = [pytest.mark.oracle, pytest.mark.redis]

E01, DOCID = 200680, 2550
K30, PREGEL = "206323", "206324"


@pytest.fixture(scope="module")
def admin(servers: list[Backend]) -> Iterator[Browser]:
    browser = Browser(servers[0], "admin", "admin123..")
    yield browser
    browser.close()


@pytest.fixture(scope="module")
def accountant(servers: list[Backend]) -> Iterator[Browser]:
    browser = Browser(servers[0], "chengben01", "Abc123..")
    yield browser
    browser.close()


def memo(docid: int, value: str | None) -> dict[str, Any]:
    return {"entity": PAGE, "master": {"op": "modify", "rowKey": str(docid), "changes": {"MEMO": value}}, "details": []}


def post(browser: Browser, cleanup: Cleanup, command: dict[str, Any]) -> dict[str, Any]:
    response = browser.post("/api/commands", cleanup.split(command))
    assert response.status_code == 200, response.text
    return cleanup.result(response.json())


@pytest.fixture
def restore_e01(admin: Browser, dcg: Engine, cleanup: Cleanup) -> Iterator[dict[str, Any]]:
    master, _ = document(dcg, E01)
    assert master is not None
    yield master
    if document(dcg, E01)[0] != master:
        post(admin, cleanup, save_command(cleanup.key(), [memo(E01, master["memo"])]))
    assert document(dcg, E01)[0] == master


def test_one_rejected_by_rule_the_other_saved(admin: Browser, dcg: Engine, cleanup: Cleanup,
                                              restore_e01: dict[str, Any]) -> None:
    before_2550 = document(dcg, DOCID)
    command = save_command(cleanup.key(), [
        memo(E01, "按单据提交"),
        detail_change(str(DOCID), "COST_MATERIAL", PREGEL, {"PER_HL": "0"}),
    ])
    result = post(admin, cleanup, command)
    assert result["outcome"] == "saved"
    assert [(r["entity"], r["rowKey"]) for r in result["rows"]] == [(PAGE, str(E01))]
    [failure] = result["failed"]
    assert (failure["entity"], failure["rowKey"], failure["error"]["code"]) == (PAGE, str(DOCID), "RULE_REJECTED")
    assert [(d["rowKey"], d["field"]) for d in failure["error"]["details"]] == [(PREGEL, "PER_HL")]
    assert document(dcg, E01)[0]["memo"] == "按单据提交"  # type: ignore[index]
    assert document(dcg, DOCID) == before_2550

    # 改回 200680，再把第一次的请求原样重发：200680 不再执行，2550 重新执行仍被拒绝
    post(admin, cleanup, save_command(cleanup.key(), [memo(E01, restore_e01["memo"])]))
    assert post(admin, cleanup, command) == result
    assert document(dcg, E01)[0] == restore_e01
    assert document(dcg, DOCID) == before_2550


def test_one_frozen_by_approval_the_other_saved(admin: Browser, accountant: Browser, dcg: Engine, cleanup: Cleanup,
                                                restore_e01: dict[str, Any]) -> None:
    before_2550 = document(dcg, DOCID)
    submitted = post(accountant, cleanup, save_command(cleanup.key(), [detail_change(str(DOCID), "COST_MATERIAL", K30, {"PRICE": "90"})]))
    assert submitted["outcome"] == "approvalSubmitted"
    [approval] = submitted["approvals"]
    try:
        result = post(admin, cleanup, save_command(cleanup.key(), [memo(DOCID, "按单据提交"), memo(E01, "按单据提交")]))
        assert result["outcome"] == "saved"
        assert [(r["entity"], r["rowKey"]) for r in result["rows"]] == [(PAGE, str(E01))]
        [failure] = result["failed"]
        assert (failure["rowKey"], failure["error"]["code"]) == (str(DOCID), "FROZEN_BY_APPROVAL")
        assert document(dcg, E01)[0]["memo"] == "按单据提交"  # type: ignore[index]
        assert document(dcg, DOCID) == before_2550
    finally:
        rejected = admin.post(f"/api/approvals/{approval['approvalId']}/reject",
                              {"requestKey": cleanup.key(), "comment": "按单据提交联调：驳回"})
        assert rejected.status_code == 200, rejected.text
    assert document(dcg, DOCID) == before_2550
