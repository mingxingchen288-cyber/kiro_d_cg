"""T-AP-9（C09 v14）：全部审批（`box=all`）、一张单据的审批（`box=record`）、审批记录（`history`）、修改内容的列宽（`widths`）。

业务例子同 E37（`test_freeze.e37_save`）：杨娜在成本核算改成本单 2550 的聚维酮K30 单价，提交审批，冻结成本单 2550 和物料 25；
系统管理员（角色 ADMIN）审批。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cost_platform.contracts import types as t

from .support import ADMIN, YANGNA, Harness
from .test_freeze import e37_save
from .test_router import client


def test_all_box_keeps_approvals_the_approver_has_processed() -> None:
    """admin 通过后，审批从"待审批"中消失，仍在"全部审批"中；发起人不是审批人，"全部审批"中没有它。"""
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "80")
    admin = h.ctx(ADMIN)
    assert [r.approval_id for r in h.service.list(admin, "all", 0, 50).rows] == [approval.approval_id]
    h.pass_(ADMIN, approval.approval_id)
    assert h.service.list(admin, "todo", 0, 50).total == 0
    listed = h.service.list(admin, "all", 0, 50)
    assert ([r.approval_id for r in listed.rows], listed.rows[0].status, listed.total) == ([approval.approval_id], "approved", 1)
    assert h.service.list(h.ctx(YANGNA), "all", 0, 50).total == 0
    assert h.service.list(h.ctx(YANGNA), "mine", 0, 50).total == 1


def test_record_box_lists_source_and_locking_approvals() -> None:
    """成本核算的 2550 是来源单据；物料清单的 25 被这个审批冻结：两处都能查到这个审批。通过后 25 解冻，只剩来源单据能查到。"""
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "80")
    ctx = h.ctx(YANGNA)

    def of(page: str, key: str) -> list[tuple[str, str]]:
        return [(r.approval_id, r.status) for r in h.service.list(ctx, "record", 0, 20, page=page, record_key=key).rows]

    assert of("COST_PINGGU", "2550") == [(approval.approval_id, "pending")]
    assert of("GOODS_PRICE_MANAGE", "25") == [(approval.approval_id, "pending")]
    assert of("COST_PINGGU", "2556") == []
    h.pass_(ADMIN, approval.approval_id)
    assert of("COST_PINGGU", "2550") == [(approval.approval_id, "approved")]
    assert of("GOODS_PRICE_MANAGE", "25") == []


def test_record_box_puts_pending_first() -> None:
    """同一张单据先后两个审批：第一个撤回后再提交，进行中的排在前面。"""
    h = Harness(["COST_TO_GOODS"])
    first = e37_save(h, "80")
    h.withdraw(YANGNA, first.approval_id, "录入有误")
    second = e37_save(h, "85")
    rows = h.service.list(h.ctx(YANGNA), "record", 0, 20, page="COST_PINGGU", record_key="2550").rows
    assert [(r.approval_id, r.status) for r in rows] == [(second.approval_id, "pending"), (first.approval_id, "withdrawn")]


def test_history_lists_submit_pass_and_withdraw() -> None:
    """审批记录：提交、通过（带意见）；另一个审批提交、撤回（带撤回原因）。"""
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "80")
    submitted = h.detail(ADMIN, approval.approval_id).history
    assert [(i.action, i.level, i.by.display_name, i.comment) for i in submitted] == [("submit", 1, "杨娜", None)]
    h.service.pass_(h.ctx(ADMIN), approval.approval_id, _pass(h, approval.approval_id, "价格已核对"))
    items = h.detail(YANGNA, approval.approval_id).history
    assert [(i.action, i.level, i.by.user_id, i.comment) for i in items] == [
        ("submit", 1, YANGNA.user_id, None), ("pass", 1, ADMIN.user_id, "价格已核对")]
    assert items[0].at <= items[1].at

    other = e37_save(h, "85")
    h.withdraw(YANGNA, other.approval_id, "录入有误")
    assert [(i.action, i.comment) for i in h.detail(ADMIN, other.approval_id).history] == [
        ("submit", None), ("withdraw", "录入有误")]


def test_view_tables_carry_widths_aligned_with_columns() -> None:
    """修改内容的每张表都带 `widths`，与列一一对应；C06 7.8 的样例没有配宽度，都为 None（前端按 170 显示）。"""
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "80")
    view = h.detail(ADMIN, approval.approval_id).view
    tables = [view.master, *view.details, *view.affected]
    assert tables and all(t.widths is not None and len(t.widths) == len(t.columns) for t in tables)


def test_record_box_over_http_needs_page_and_record_key() -> None:
    h = Harness(["COST_TO_GOODS"], threads=True)
    approval = e37_save(h, "80")
    api: TestClient = client(h)
    headers = {"x-user": YANGNA.user_id}
    found = api.get("/api/approvals", params={"box": "record", "page": "GOODS_PRICE_MANAGE", "recordKey": "25"}, headers=headers)
    assert found.status_code == 200 and [r["approvalId"] for r in found.json()["rows"]] == [approval.approval_id]
    missing = api.get("/api/approvals", params={"box": "record", "page": "COST_PINGGU"}, headers=headers)
    assert missing.status_code == 400 and missing.json()["code"] == "INVALID_REQUEST"
    detail = api.get(f"/api/approvals/{approval.approval_id}", headers=headers).json()
    assert detail["history"][0] == {"action": "submit", "level": 1, "by": {"userId": YANGNA.user_id, "displayName": "杨娜"},
                                    "at": detail["submittedAt"], "comment": None}
    assert len(detail["view"]["affected"][0]["widths"]) == len(detail["view"]["affected"][0]["columns"])


def _pass(h: Harness, approval_id: str, comment: str) -> t.PassRequest:
    """带意见的通过请求（`Harness.pass_` 不带意见）。"""
    fingerprint = h.preview(ADMIN, approval_id, []).fingerprint
    return t.PassRequest(request_key=h.request_key(), fingerprint=fingerprint, checked_rows=[], comment=comment, params={})
