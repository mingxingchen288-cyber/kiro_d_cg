"""T-AS-6 批次 C 真实联调（d_cg + Redis；架构 10.3–10.5）。后端为 conftest 的两个进程 A、B。

用 d_cg 中已发布的审批流 COST_TO_GOODS（C06 7.8 去掉第 2 级：成本核算原辅料、包材的物料或单价有变化，并且单价与
物料清单 NVL(执行价, 参考价格) 不同时进入审批；第 1 级"管理员审批"，或签，角色 ADMIN；冻结物料清单 T_COST_GOODS 中
这个物料；通过后把单价写到物料清单的执行价，修改人写成通过的审批人，WP-20）。

数据自己建、自己删（sample_two.CreatedData）：两个测试 ERP 物料 A（参考价格 75、执行价为空，代替聚维酮K30）、B（参考
价格 12.5，代替预胶化淀粉）；admin 经平台新建一张成本单，原辅料两行：A（每片含量 10、单价 75、金额 750）、B（每片含量 15、
单价 12.5）。单价等于物料清单的单价，新建时不触发审批。不用 d_cg 已有的成本单 2550 和物料 25：通过时物料清单的修改人
写成审批人，经平台改不回。

1. 从保存触发到最终批准（样例一），两名审批人或签同时通过：chengben01 把 A 那一行的单价 75 改成 90 → 进入审批，
   测试成本单和物料 A 冻结，单价不写；审批详情按 C06 7.6 显示 75.00 → 90.00；冻结期间 admin 保存这张单据的备注返回
   409 FROZEN_BY_APPROVAL，这次保存的冻结查询就是可冻结业务多出的 1 条；admin 和另一个 ADMIN 角色的测试账号同时通过，
   只有一个生效，单价 90、每批成本 900、主表汇总重算，物料 A 执行价 90、修改人为生效的审批人，冻结解除；用同一请求键
   再提交一次通过，返回原结果，不重复执行。
2. 最终批准中任一步失败整体回滚：测试另开一个连接锁住物料 A 这一行，admin 通过时写物料清单等锁 5 秒后返回
   409 DOCUMENT_BUSY；审批仍在第 1 级待处理，冻结还在，没有处理记录，单价、执行价都不变。释放锁后驳回。
3. 审批提交与普通保存同时进行：chengben01 改单价（提交审批）和 admin 改这张单据的主表备注同时提交，两个命令按单据的
   行锁先后执行：先提交审批时，备注的保存返回 FROZEN_BY_APPROVAL；先保存备注时，备注写入，审批照常提交。驳回。
4. 两个命令同时为同一张单据发起审批：chengben01 改 A 那一行的单价、admin 改 B 那一行的单价同时提交，只有一个提交审批，
   另一个返回 409 FROZEN_BY_APPROVAL（details 给出先提交的审批）。驳回。

样例二（C06 7.9、7.10）见 test_sample_two.py。测试建的 ADMIN 角色账号、产生的审批、投递、站内通知和命令记录在结束时
删掉（dcg.Cleanup）；测试成本单经平台删除，测试物料和中途失败没删掉的单据直接按主键删，结束时核对几张业务表的行数
与开始时相同。
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text

from .dcg import PAGE, Cleanup, detail_change, document, goods, rows, save_command
from .sample_two import CreatedData, new_document
from .servers import Backend, Browser

pytestmark = [pytest.mark.oracle, pytest.mark.redis]

D = Decimal
ADMIN = ("admin", "admin123..")
ACCOUNTANT = ("chengben01", "Abc123..")
MARKER = "PF_TEST test_batch_c"


@pytest.fixture(scope="module")
def admin(servers: list[Backend]) -> Iterator[Browser]:
    browser = Browser(servers[0], *ADMIN)
    browser.ok(browser.put("/api/admin/command-review", {"enabled": True}))
    yield browser
    browser.ok(browser.put("/api/admin/command-review", {"enabled": False}))
    browser.close()


@pytest.fixture(scope="module")
def accountant(servers: list[Backend]) -> Iterator[Browser]:
    browser = Browser(servers[1], *ACCOUNTANT)
    yield browser
    browser.close()


@dataclass(frozen=True)
class Doc:
    """测试成本单：主键、A、B 两行明细的主键和两个测试物料。"""

    docid: str
    row_a: str
    row_b: str
    goods_a: str
    goods_b: str

    def snapshot(self, dcg: Engine) -> tuple[Any, Any]:
        """成本单（主表、明细）和物料 A 的当前行。"""
        return document(dcg, int(self.docid)), goods(dcg, int(self.goods_a))


@pytest.fixture
def doc(admin: Browser, dcg: Engine, cleanup: Cleanup) -> Iterator[Doc]:
    """建测试物料 A、B 和测试成本单；结束时先驳回本测试还在审批中的审批（解冻），再经平台删成本单，最后直接删测试物料
    和没删掉的单据，核对业务表行数与开始时相同。"""
    created = CreatedData(dcg)
    counts = created.counts()
    goods_a, goods_b = created.add_erp_goods("75"), created.add_erp_goods("12.5")
    new, master_id, (id_a, id_b) = new_document(MARKER, [{"GOODSID": goods_a, "PER_HL": "10", "PRICE": "75"},
                                                         {"GOODSID": goods_b, "PER_HL": "15", "PRICE": "12.5"}])
    result = save(admin, cleanup, [new]).json()
    assert result["outcome"] == "saved", result
    docid = str(result["idMap"][master_id])
    created.docids.append(docid)
    yield Doc(docid, str(result["idMap"][id_a]), str(result["idMap"][id_b]), goods_a, goods_b)
    for approval_id in cleanup.approvals:
        if approval_state(dcg, approval_id)["status"] == "pending":
            reject(admin, cleanup, approval_id)
    deleted = save(admin, cleanup, [{"entity": PAGE, "master": {"op": "delete", "rowKey": docid}, "details": []}])
    assert deleted.status_code == 200 and deleted.json()["outcome"] == "saved", deleted.text
    created.drop_all()
    assert created.counts() == counts


def save(browser: Browser, cleanup: Cleanup, documents: list[dict[str, Any]]) -> httpx.Response:
    response = browser.post("/api/commands", save_command(cleanup.key(), documents))
    if response.status_code == 200:
        cleanup.result(response.json())
    return response


def price(doc: Doc, dtlid: str, value: str) -> list[dict[str, Any]]:
    return [detail_change(doc.docid, "COST_MATERIAL", dtlid, {"PRICE": value})]


def memo(doc: Doc, value: str | None) -> list[dict[str, Any]]:
    return [{"entity": PAGE, "master": {"op": "modify", "rowKey": doc.docid, "changes": {"MEMO": value}}, "details": []}]


def submitted(doc: Doc, response: httpx.Response) -> str:
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["outcome"] == "approvalSubmitted", result
    [approval] = result["approvals"]
    assert approval["document"] == {"entity": PAGE, "recordKey": doc.docid} and approval["flows"] == ["COST_TO_GOODS"]
    return str(approval["approvalId"])


def pass_body(browser: Browser, cleanup: Cleanup, approval_id: str) -> dict[str, Any]:
    """通过请求：指纹取自审批详情；COST_TO_GOODS 的物料清单一块是 selection all，不能改勾选，不用提交 checkedRows。"""
    detail = browser.ok(browser.get(f"/api/approvals/{approval_id}"))
    return {"requestKey": cleanup.key(), "fingerprint": detail["fingerprint"], "checkedRows": [], "comment": "G5 联调通过",
            "params": {}}


def reject(browser: Browser, cleanup: Cleanup, approval_id: str) -> None:
    response = browser.post(f"/api/approvals/{approval_id}/reject", {"requestKey": cleanup.key(), "comment": "G5 联调：驳回"})
    assert response.status_code == 200, response.text


def approval_state(dcg: Engine, approval_id: str) -> dict[str, Any]:
    record = rows(dcg, "SELECT status, current_level, pending_status FROM pf_approval WHERE approval_id = :a", a=int(approval_id))[0]
    freezes = {(r["root_table"], r["record_key"]) for r in rows(dcg, "SELECT root_table, record_key FROM pf_approval_freeze "
                                                                "WHERE approval_id = :a", a=int(approval_id))}
    actions = [r["action"] for r in rows(dcg, "SELECT action FROM pf_approval_record WHERE approval_id = :a ORDER BY seq",
                                         a=int(approval_id))]
    return {**record, "freezes": freezes, "actions": actions}


def pending(doc: Doc, goodsid: str) -> dict[str, Any]:
    """第 1 级待处理：冻结测试成本单和这个物料，还没有处理记录。"""
    return {"status": "pending", "current_level": 1, "pending_status": "pending",
            "freezes": {("T_COST_PINGGU", doc.docid), ("T_COST_GOODS", goodsid)}, "actions": []}


def together(*calls: Callable[[], httpx.Response]) -> list[httpx.Response]:
    """几个请求同时发出（各自的线程、各自的会话，等全部线程就绪后一起开始）。"""
    barrier = threading.Barrier(len(calls))
    results: list[httpx.Response | None] = [None] * len(calls)

    def run(index: int, call: Callable[[], httpx.Response]) -> None:
        barrier.wait()
        results[index] = call()

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert all(r is not None for r in results)
    return results  # type: ignore[return-value]


def by_key(details: list[dict[str, Any]], dtlid: str) -> dict[str, Any]:
    return next(d for d in details if str(d["dtlid"]) == dtlid)


def cells(block: dict[str, Any], column: str) -> list[tuple[Any, Any]]:
    index = block["columns"].index(column)
    return [(r["cells"][index]["before"], r["cells"][index]["after"]) for r in block["rows"]]


def review_sql(admin: Browser, key: str) -> list[str]:
    """命令审查（WP-17）中这个请求键的语句。"""
    logs = admin.ok(admin.get("/api/admin/command-review", params={"startRow": 0, "endRow": 200}))["rows"]
    [log] = [entry for entry in logs if entry["requestKey"] == key]
    texts = [s["text"] for s in log["sql"]]
    print(f"== {key}：{log['sqlCount']} 条，{log['result']} {log['errorCode']}")
    print("\n".join(f"  {i}. {s[:160]}" for i, s in enumerate(texts, start=1)))
    return texts


@pytest.fixture
def second_approver(admin: Browser, servers: list[Backend], cleanup: Cleanup) -> Iterator[Browser]:
    """另一个 ADMIN 角色的测试账号（或签的第二个审批人），密码每次随机，结束时连同角色分配删掉。"""
    username, password = f"g5_or_{secrets.token_hex(3)}", f"G5_{secrets.token_hex(6)}"
    account = admin.ok(admin.post("/api/admin/accounts", {"username": username, "displayName": "G5 联调审批人",
                                                          "departmentId": None, "password": password, "roleCodes": ["ADMIN"]}))
    cleanup.users.append(account["userId"])
    browser = Browser(servers[1], username, password)
    yield browser
    browser.close()


# ---------------------------------------------------------------- 1：从保存到最终批准、或签同时通过、重复批准

def test_save_to_final_approval_or_sign_at_once_and_replay(admin: Browser, accountant: Browser, second_approver: Browser,
                                                           dcg: Engine, cleanup: Cleanup, doc: Doc) -> None:
    before = doc.snapshot(dcg)
    (master0, details0), goods0 = before
    approval_id = submitted(doc, save(accountant, cleanup, price(doc, doc.row_a, "90")))
    assert approval_state(dcg, approval_id) == pending(doc, doc.goods_a)
    assert doc.snapshot(dcg) == before  # 审批结束前不写业务表

    detail = admin.ok(admin.get(f"/api/approvals/{approval_id}"))
    [step] = detail["steps"]
    assert (step["level"], step["flow"], step["node"], step["mode"], step["status"]) == (1, "COST_TO_GOODS", "管理员审批", "or", "pending")
    assert [(m["type"], m["id"], m["name"]) for m in step["members"]] == [("role", "ADMIN", "系统管理员")]
    material = next(b for b in detail["view"]["details"] if b["key"] == "material")
    assert cells(material, "单价") == [("75.00", "90.00")] and cells(material, "金额") == [("750.00", "900.00")]
    [listed] = detail["view"]["affected"]
    assert listed["key"] == "goods" and cells(listed, "单价") == [("75.00", "90.00")]
    assert detail["actions"]["canPass"] is True

    # 冻结期间的普通保存：加锁读取之后的冻结查询（可冻结业务多出的 1 条）查到本审批，整笔拒绝
    key = cleanup.key()
    frozen = admin.post("/api/commands", save_command(key, memo(doc, "G5 冻结中")))
    assert frozen.status_code == 409 and frozen.json()["code"] == "FROZEN_BY_APPROVAL", frozen.text
    assert frozen.json()["details"][0]["approvalId"] == approval_id
    sql = review_sql(admin, key)
    assert [s.split(" ")[0] for s in sql] == ["INSERT", "SELECT", "SELECT"] and "PF_APPROVAL_FREEZE" in sql[2].upper()

    # 或签：两名审批人同时通过，只有一个生效
    approvers = [admin, second_approver]
    bodies = [pass_body(admin, cleanup, approval_id), pass_body(second_approver, cleanup, approval_id)]
    responses = together(lambda: admin.post(f"/api/approvals/{approval_id}/pass", bodies[0]),
                         lambda: second_approver.post(f"/api/approvals/{approval_id}/pass", bodies[1]))
    assert sorted(r.status_code for r in responses) == [200, 403], [r.text for r in responses]
    won = next(i for i, r in enumerate(responses) if r.status_code == 200)
    lost = responses[1 - won].json()
    assert lost["code"] == "PERMISSION_DENIED"
    result = responses[won].json()
    assert result["outcome"] == "approvalProcessed" and result["approvals"][0]["status"] == "approved"
    print(f"或签同时通过：{['admin', '测试审批人'][won]} 生效，另一人 403 {lost['message']}")
    assert approval_state(dcg, approval_id) == {"status": "approved", "current_level": 1, "pending_status": "applied",
                                                "freezes": set(), "actions": ["pass"]}
    master1, details1 = document(dcg, int(doc.docid))
    row_a = by_key(details1, doc.row_a)
    assert (D(str(row_a["price"])), D(str(row_a["cost_batch"]))) == (D(90), D(900))
    assert [d for d in details1 if str(d["dtlid"]) != doc.row_a] == [d for d in details0 if str(d["dtlid"]) != doc.row_a]
    # 辅料合计多 150（750 → 900）；这张单据没有原料，不除以 1.13
    assert D(str(master1["total_fl"])) == D(str(master0["total_fl"])) + D(150)  # type: ignore[index]
    assert master1["memo"] == master0["memo"]  # type: ignore[index]
    # 物料 A：执行价 90，修改人为生效的审批人（WP-20），其余列不变
    goods1 = goods(dcg, int(doc.goods_a))
    assert (D(str(goods1["zx_price"])), goods1["update_by"]) == (D(90), approvers[won].login["user"]["username"])
    assert {**goods1, "zx_price": goods0["zx_price"], "update_by": goods0["update_by"]} == goods0

    # 重复批准：同一请求键再提交，返回原结果，不重复执行
    replay = approvers[won].post(f"/api/approvals/{approval_id}/pass", bodies[won])
    assert replay.status_code == 200 and replay.json() == result
    assert approval_state(dcg, approval_id)["actions"] == ["pass"]
    assert doc.snapshot(dcg) == ((master1, details1), goods1)


# ---------------------------------------------------------------- 2：最终批准中一步失败，整体回滚

def test_final_approval_step_fails_and_rolls_back(admin: Browser, accountant: Browser, dcg: Engine, cleanup: Cleanup,
                                                  doc: Doc) -> None:
    before = doc.snapshot(dcg)
    approval_id = submitted(doc, save(accountant, cleanup, price(doc, doc.row_a, "90")))
    body = pass_body(admin, cleanup, approval_id)
    with dcg.connect() as holder:  # 另一个会话锁住物料 A，最终批准写执行价时等锁超时
        holder.execute(text("SELECT goodsid FROM t_cost_goods WHERE goodsid = :g FOR UPDATE"), {"g": int(doc.goods_a)})
        response = admin.post(f"/api/approvals/{approval_id}/pass", body)
        holder.rollback()
    assert response.status_code == 409 and response.json()["code"] == "DOCUMENT_BUSY", response.text
    assert approval_state(dcg, approval_id) == pending(doc, doc.goods_a)  # 处理记录、状态、解冻都回滚了
    assert doc.snapshot(dcg) == before
    assert rows(dcg, "SELECT 1 FROM pf_command WHERE request_key = :k", k=body["requestKey"]) == []
    reject(admin, cleanup, approval_id)


# ---------------------------------------------------------------- 3：审批提交与普通保存同时进行

def test_submission_and_plain_save_at_the_same_time(admin: Browser, accountant: Browser, dcg: Engine, cleanup: Cleanup,
                                                    doc: Doc) -> None:
    (master0, _), _ = doc.snapshot(dcg)
    keys = cleanup.key(), cleanup.key()
    submit, plain = together(lambda: accountant.post("/api/commands", save_command(keys[0], price(doc, doc.row_a, "90"))),
                             lambda: admin.post("/api/commands", save_command(keys[1], memo(doc, "G5 同时保存"))))
    approval_id = submitted(doc, submit)
    cleanup.result(submit.json())
    if plain.status_code == 200:
        print("先执行备注的保存，再提交审批")
        assert plain.json()["outcome"] == "saved"
        assert document(dcg, int(doc.docid))[0]["memo"] == "G5 同时保存"  # type: ignore[index]
    else:
        print("先提交审批，备注的保存被冻结拒绝")
        assert (plain.status_code, plain.json()["code"]) == (409, "FROZEN_BY_APPROVAL"), plain.text
        assert plain.json()["details"][0]["approvalId"] == approval_id
        assert document(dcg, int(doc.docid))[0]["memo"] == master0["memo"]  # type: ignore[index]
    assert approval_state(dcg, approval_id) == pending(doc, doc.goods_a)
    assert D(str(by_key(document(dcg, int(doc.docid))[1], doc.row_a)["price"])) == D(75)
    reject(admin, cleanup, approval_id)


# ---------------------------------------------------------------- 4：两个命令同时为同一张单据发起审批

def test_two_submissions_for_one_document_only_one_succeeds(admin: Browser, accountant: Browser, dcg: Engine,
                                                            cleanup: Cleanup, doc: Doc) -> None:
    before = doc.snapshot(dcg)
    keys = cleanup.key(), cleanup.key()
    responses = together(lambda: accountant.post("/api/commands", save_command(keys[0], price(doc, doc.row_a, "90"))),
                         lambda: admin.post("/api/commands", save_command(keys[1], price(doc, doc.row_b, "13"))))
    assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
    won = next(i for i, r in enumerate(responses) if r.status_code == 200)
    approval_id = submitted(doc, responses[won])
    cleanup.result(responses[won].json())
    lost = responses[1 - won].json()
    print(f"同时发起审批：{['chengben01 改物料 A 那一行', 'admin 改物料 B 那一行'][won]} 提交成功，另一个 {lost['code']}")
    assert lost["code"] == "FROZEN_BY_APPROVAL" and lost["details"][0]["approvalId"] == approval_id
    assert approval_state(dcg, approval_id) == pending(doc, [doc.goods_a, doc.goods_b][won])
    waiting = rows(dcg, "SELECT approval_id FROM pf_approval WHERE source_key = :d AND status = 'pending'", d=doc.docid)
    assert [str(r["approval_id"]) for r in waiting] == [approval_id]
    assert doc.snapshot(dcg) == before
    reject(admin, cleanup, approval_id)
