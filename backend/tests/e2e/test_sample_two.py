"""T-AS-6 样例二真实联调（d_cg + Redis）：C06 7.9 TECH_CUSTOMER_MATERIAL、7.10 GOODS_TO_COST，从保存触发到最终批准。
后端为 conftest 的两个进程 A、B：审批人 admin 在 A，发起人 jishu01（部门 18 技术中心，角色"技术中心"）在 B。

1. 7.9：jishu01 把"评估中"成本单里客户指定的硬脂酸镁改成不是客户指定 → 进入 TECH_CUSTOMER_MATERIAL，只冻结这张成本单，
   没有受影响单据，业务表不变；admin 通过后这一行写成不是客户指定，冻结解除。
2. 7.10：jishu01 在物料清单把 ERP 物料的单价（执行价）10 改成 12 → 进入 GOODS_TO_COST（这一行 ISERP = 1，ZX_PRICE 必须
   审批：approvalRequired 因单据进入了审批、且从 GOODS_PRICE_MANAGE 保存而放行）；含这个物料的成本单 D1、D2 和液体明细冻结，
   列给审批人勾选。admin 取消 D2 那一行，预览中 D2 恢复为修改前；通过后物料清单执行价 12，D1 单价 12、金额和主表按计算规则
   重算，D2 不变，液体明细单价 12（液体成本没有注册实体，按 C06 7.5 只改写入的列、不重算）。

测试数据由 sample_two.CreatedData 新建、结束时删掉（docstring 见 sample_two.py）；测试产生的审批、投递、站内通知、命令记录
由 dcg.Cleanup 删掉。结束时核对几张业务表的行数与开始时相同。
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine

from .dcg import Cleanup, rows
from .sample_two import (
    GOODS_ENTITY,
    GOODS_PAGE,
    GOODS_SAVE,
    PAGE,
    SAVE,
    CreatedData,
    command,
    detail_rows,
    freezes,
    goods_row,
    liquid_row,
    list_price,
    master_row,
    new_document,
)
from .servers import Backend, Browser

pytestmark = [pytest.mark.oracle, pytest.mark.redis]

D = Decimal
ADMIN = ("admin", "admin123..")
TECH = ("jishu01", "Jishu123..")


@pytest.fixture(scope="module")
def admin(servers: list[Backend]) -> Iterator[Browser]:
    browser = Browser(servers[0], *ADMIN)
    yield browser
    browser.close()


@pytest.fixture(scope="module")
def tech(servers: list[Backend]) -> Iterator[Browser]:
    browser = Browser(servers[1], *TECH)
    assert browser.login["selectedRole"]["code"] == "技术中心" and browser.login["user"]["departmentId"] == "18"
    yield browser
    browser.close()


@pytest.fixture
def data(dcg: Engine, admin: Browser, cleanup: Cleanup) -> Iterator[CreatedData]:
    """本测试建的数据；结束时先删掉审批记录（cleanup 在它之后执行，这里先删冻结，免得平台删除被冻结挡住），再删数据，
    最后核对几张业务表的行数与开始时相同。"""
    created = CreatedData(dcg)
    counts = created.counts()
    yield created
    pending = [a for a in cleanup.approvals if rows(dcg, "SELECT 1 FROM pf_approval WHERE approval_id = :a AND status = 'pending'",
                                                     a=int(a))]
    for approval_id in pending:  # 中途失败留下的审批：驳回，单据恢复为可修改
        admin.post(f"/api/approvals/{approval_id}/reject", {"requestKey": cleanup.key(), "comment": "H5 联调：驳回"})
    created.drop_all()
    assert created.counts() == counts


def run(browser: Browser, cleanup: Cleanup, page: str, operation: str, documents: list[dict[str, Any]]) -> dict[str, Any]:
    response = browser.post("/api/commands", command(cleanup.key(), page, operation, documents))
    assert response.status_code == 200, response.text
    return cleanup.result(response.json())


def create_documents(admin: Browser, cleanup: Cleanup, data: CreatedData, docs: list[tuple[dict[str, Any], str, list[str]]]
                     ) -> list[tuple[str, list[str]]]:
    """admin 经平台新建成本单，返回每张单据的主键和明细主键。"""
    result = run(admin, cleanup, PAGE, SAVE, [doc for doc, _, _ in docs])
    assert result["outcome"] == "saved", result
    found = []
    for _, master_id, detail_ids in docs:
        docid = result["idMap"][master_id]
        data.docids.append(docid)
        found.append((docid, [result["idMap"][i] for i in detail_ids]))
    return found


def delete_documents(admin: Browser, cleanup: Cleanup, docids: list[str]) -> None:
    result = run(admin, cleanup, PAGE, SAVE, [{"entity": PAGE, "master": {"op": "delete", "rowKey": d}, "details": []} for d in docids])
    assert result["outcome"] == "saved", result


def submitted(result: dict[str, Any], entity: str, record_key: str, flow: str) -> str:
    assert result["outcome"] == "approvalSubmitted", result
    [approval] = result["approvals"]
    assert approval["document"] == {"entity": entity, "recordKey": record_key} and approval["flows"] == [flow], approval
    return str(approval["approvalId"])


def column(block: dict[str, Any], label: str) -> list[tuple[Any, Any]]:
    index = block["columns"].index(label)
    return [(r["cells"][index]["before"], r["cells"][index]["after"]) for r in block["rows"]]


def approval_row(dcg: Engine, approval_id: str) -> dict[str, Any]:
    return rows(dcg, "SELECT status, current_level, pending_status FROM pf_approval WHERE approval_id = :a", a=int(approval_id))[0]


def actions(dcg: Engine, approval_id: str) -> list[str]:
    return [r["action"] for r in rows(dcg, "SELECT action FROM pf_approval_record WHERE approval_id = :a ORDER BY seq",
                                      a=int(approval_id))]


# ---------------------------------------------------------------- 1：C06 7.9 技术中心客指物料变更审批

def test_tech_center_customer_material_change_to_final_approval(admin: Browser, tech: Browser, dcg: Engine, cleanup: Cleanup,
                                                               data: CreatedData) -> None:
    stearate, starch = list_price(dcg, 115), list_price(dcg, 310)
    doc = new_document("H5 联调样例二", [{"GOODSID": "115", "PER_HL": "2.5", "PRICE": stearate, "CUSTOMER_SPECIFIED": True},
                                        {"GOODSID": "310", "PER_HL": "42.5", "PRICE": starch}], USESTATUS="评估中")
    [(docid, [specified, other])] = create_documents(admin, cleanup, data, [doc])
    before = (master_row(dcg, docid), detail_rows(dcg, docid))
    assert [int(d["customer_specified"] or 0) for d in before[1]] == [1, 0]

    # jishu01 把客户指定的硬脂酸镁改成不是客户指定
    change = {"entity": PAGE, "master": {"op": "none", "rowKey": docid},
              "details": [{"entity": "COST_MATERIAL", "op": "modify", "rowKey": specified, "changes": {"CUSTOMER_SPECIFIED": False}}]}
    approval_id = submitted(run(tech, cleanup, PAGE, SAVE, [change]), PAGE, docid, "TECH_CUSTOMER_MATERIAL")
    assert approval_row(dcg, approval_id) == {"status": "pending", "current_level": 1, "pending_status": "pending"}
    assert freezes(dcg, approval_id) == {("T_COST_PINGGU", docid)}  # 只冻结这张成本单
    assert (master_row(dcg, docid), detail_rows(dcg, docid)) == before  # 审批结束前不写业务表

    detail = admin.ok(admin.get(f"/api/approvals/{approval_id}"))
    [step] = detail["steps"]
    assert (step["flow"], step["node"], step["mode"], step["status"]) == ("TECH_CUSTOMER_MATERIAL", "管理员审批", "or", "pending")
    assert detail["applicant"]["userId"] == tech.login["user"]["userId"] and detail["view"]["affected"] == []
    material = next(b for b in detail["view"]["details"] if b["key"] == "material")
    print("原辅料块：", material["columns"], [r["cells"] for r in material["rows"]])
    [(was, now)] = column(material, "客户指定")
    assert was != now and column(material, "物料") == [("115", "115")]

    passed = admin.ok(admin.post(f"/api/approvals/{approval_id}/pass", {
        "requestKey": cleanup.key(), "fingerprint": detail["fingerprint"], "checkedRows": [], "comment": "H5 联调通过", "params": {}}))
    assert passed["outcome"] == "approvalProcessed" and passed["approvals"][0]["status"] == "approved", passed
    assert approval_row(dcg, approval_id) == {"status": "approved", "current_level": 1, "pending_status": "applied"}
    assert freezes(dcg, approval_id) == set() and actions(dcg, approval_id) == ["pass"]
    after = detail_rows(dcg, docid)
    assert [int(d["customer_specified"] or 0) for d in after] == [0, 0]
    unchanged = {"customer_specified"}
    assert [{k: v for k, v in d.items() if k not in unchanged} for d in after] == [
        {k: v for k, v in d.items() if k not in unchanged} for d in before[1]]
    assert str(other) == str(after[1]["dtlid"])

    delete_documents(admin, cleanup, [docid])
    assert master_row(dcg, docid) is None and detail_rows(dcg, docid) == []


# ---------------------------------------------------------------- 2：C06 7.10 物料清单改价审批，审批人取消勾选部分成本单

def test_goods_price_change_updates_only_checked_documents(admin: Browser, tech: Browser, dcg: Engine, cleanup: Cleanup,
                                                           data: CreatedData) -> None:
    goodsid = data.add_erp_goods("10")
    assert list_price(dcg, goodsid) == "10"
    created = create_documents(admin, cleanup, data, [new_document("H5 联调样例三 D1", [{"GOODSID": goodsid, "PER_HL": "10", "PRICE": "10"}]),
                                                      new_document("H5 联调样例三 D2", [{"GOODSID": goodsid, "PER_HL": "10", "PRICE": "10"}])])
    (d1, [d1_row]), (d2, [d2_row]) = created
    _, lq_row = data.add_liquid(goodsid, per_hl="5", price="10", batch_qty="5", cost_batch="50")
    d1_before, d2_before = (master_row(dcg, d1), detail_rows(dcg, d1)), (master_row(dcg, d2), detail_rows(dcg, d2))
    assert [D(str(d["cost_batch"])) for d in d1_before[1]] == [D(100)]  # 每批数量 10 × 单价 10
    goods_before, lq_before = goods_row(dcg, goodsid), liquid_row(dcg, lq_row)

    # 物料清单：jishu01 看得到这一行（ERP 行，执行价为空时单价显示参考价格 10），把单价改成 12
    record = tech.ok(tech.get(f"/api/pages/{GOODS_PAGE}/records/{goodsid}"))["master"]["values"]
    assert (record["ISERP"], record["ROW_CLASS_FLAG"], D(record["ZX_PRICE"])) == ("1", "erp", D(10))
    change = {"entity": GOODS_ENTITY, "master": {"op": "modify", "rowKey": goodsid, "changes": {"ZX_PRICE": "12"}}, "details": []}
    approval_id = submitted(run(tech, cleanup, GOODS_PAGE, GOODS_SAVE, [change]), GOODS_ENTITY, goodsid, "GOODS_TO_COST")
    assert freezes(dcg, approval_id) == {("T_COST_GOODS", goodsid), ("T_COST_PINGGU", d1), ("T_COST_PINGGU", d2),
                                         ("T_COST_PINGGU_DTL_LQ", lq_row)}
    assert goods_row(dcg, goodsid) == goods_before and liquid_row(dcg, lq_row) == lq_before
    assert (master_row(dcg, d1), detail_rows(dcg, d1)) == d1_before

    detail = admin.ok(admin.get(f"/api/approvals/{approval_id}"))
    assert detail["page"] == GOODS_PAGE and detail["source"]["recordKey"] == goodsid
    print("审批详情：", detail["pageTitle"], detail["operationLabel"], detail["source"], detail["steps"][0]["members"])
    master = detail["view"]["master"]
    assert column(master, "单价") == [("10.00", "12.00")] and column(master, "参考价格") == [("10.00", "10.00")]
    blocks = {b["key"]: b for b in detail["view"]["affected"]}
    assert set(blocks) == {"costMaterial", "costPackage", "lqMaterial", "lqPackage"}
    cost = blocks["costMaterial"]
    assert [r["ref"]["key"] for r in cost["rows"]] == [d1_row, d2_row] and all(r["checked"] for r in cost["rows"])
    assert column(cost, "单据号") == [(d1, d1), (d2, d2)] and column(cost, "单价") == [("10.00", "12.00")] * 2
    assert column(cost, "金额") == [("100.00", "120.00")] * 2
    assert blocks["costPackage"]["rows"] == [] and blocks["lqPackage"]["rows"] == []
    assert [r["ref"]["key"] for r in blocks["lqMaterial"]["rows"]] == [lq_row]
    assert column(blocks["lqMaterial"], "单价") == [("10.00", "12.00")]

    # 取消 D2 那一行：预览中 D2 恢复为修改前
    checked = [{"flow": "GOODS_TO_COST", "block": "costMaterial", "key": d1_row},
               {"flow": "GOODS_TO_COST", "block": "lqMaterial", "key": lq_row}]
    preview = admin.ok(admin.post(f"/api/approvals/{approval_id}/preview", {"checkedRows": checked}))
    cost = next(b for b in preview["view"]["affected"] if b["key"] == "costMaterial")
    assert [(r["ref"]["key"], r["checked"], r["op"]) for r in cost["rows"]] == [(d1_row, True, "modify"), (d2_row, False, "none")]
    assert column(cost, "单价") == [("10.00", "12.00"), ("10.00", "10.00")]
    assert column(cost, "每盒成本")[1][0] == column(cost, "每盒成本")[1][1]
    assert column(cost, "每盒成本")[0][0] != column(cost, "每盒成本")[0][1]
    print("取消勾选 D2 后的预览：", cost["columns"], [[c for c in r["cells"]] for r in cost["rows"]])

    passed = admin.ok(admin.post(f"/api/approvals/{approval_id}/pass", {
        "requestKey": cleanup.key(), "fingerprint": preview["fingerprint"], "checkedRows": checked, "comment": "H5 联调：只改 D1",
        "params": {}}))
    assert passed["outcome"] == "approvalProcessed" and passed["approvals"][0]["status"] == "approved", passed
    assert approval_row(dcg, approval_id) == {"status": "approved", "current_level": 1, "pending_status": "applied"}
    assert freezes(dcg, approval_id) == set() and actions(dcg, approval_id) == ["pass"]
    checked_in_db = {(r["block"], r["row_key"], int(r["checked"])) for r in rows(
        dcg, "SELECT block, row_key, checked FROM pf_approval_affected WHERE approval_id = :a", a=int(approval_id))}
    assert checked_in_db == {("costMaterial", d1_row, 1), ("costMaterial", d2_row, 0), ("lqMaterial", lq_row, 1)}

    # 物料清单执行价 12，修改人为通过的审批人 admin（WP-20），其他列不变
    goods_after = goods_row(dcg, goodsid)
    assert (D(str(goods_after["zx_price"])), goods_after["update_by"]) == (D(12), "admin")
    assert {**goods_after, "zx_price": None, "update_by": goods_before["update_by"]} == goods_before
    # D1：单价 12，金额重算 120，主表辅料合计 120（没有原料，不除以 1.13）
    d1_master, d1_details = master_row(dcg, d1), detail_rows(dcg, d1)
    assert (D(str(d1_details[0]["price"])), D(str(d1_details[0]["cost_batch"]))) == (D(12), D(120))
    assert D(str(d1_master["total_fl"])) == D(120) and d1_master["total_cost"] != d1_before[0]["total_cost"]  # type: ignore[index]
    # D2：没有勾选，不变
    assert (master_row(dcg, d2), detail_rows(dcg, d2)) == d2_before
    # 液体明细：单价写成 12；液体成本没有注册实体，不重算，金额仍为 50
    lq_after = liquid_row(dcg, lq_row)
    assert D(str(lq_after["price"])) == D(12) and {**lq_after, "price": None} == {**lq_before, "price": None}

    delete_documents(admin, cleanup, [d1, d2])
    assert [master_row(dcg, d) for d in (d1, d2)] == [None, None]
