"""T-AS-6 批次 C 真实联调（d_cg + Redis；架构 10.3–10.5）。后端为 conftest 的两个进程 A、B。

用 d_cg 中已发布的审批流 COST_TO_GOODS（C06 7.8 去掉第 2 级：成本核算原辅料、包材的物料或单价有变化，并且单价与
物料清单 NVL(执行价, 参考价格) 不同时进入审批；第 1 级"管理员审批"，或签，角色 ADMIN；冻结物料清单 T_COST_GOODS 中
这个物料；通过后把单价写到物料清单的执行价）。数据为成本单 2550 原辅料 206323 聚维酮K30（物料 25，单价 75，执行价 75）。

1. 从保存触发到最终批准（样例一），两名审批人或签同时通过：chengben01 把单价 75 改成 90 → 进入审批，2550 和物料清单 25
   冻结，单价不写；审批详情按 C06 7.6 显示 75.00 → 90.00；冻结期间 admin 保存 2550 的备注返回 409 FROZEN_BY_APPROVAL，
   这次保存的冻结查询就是可冻结业务多出的 1 条；admin 和另一个 ADMIN 角色的测试账号同时通过，只有一个生效，单价 90、
   每批成本 900、主表汇总重算，物料清单执行价 90，冻结解除；用同一请求键再提交一次通过，返回原结果，不重复执行。
   最后 chengben01 把单价改回 75（再走一次审批，admin 通过），2550 和物料清单 25 与改前相同。
2. 最终批准中任一步失败整体回滚：测试另开一个连接锁住物料清单 25 这一行，admin 通过时写物料清单等锁 5 秒后返回
   409 DOCUMENT_BUSY；审批仍在第 1 级待处理，冻结还在，没有处理记录，单价、执行价都不变。释放锁后驳回。
3. 审批提交与普通保存同时进行：chengben01 改单价（提交审批）和 admin 改 2550 主表备注同时提交，两个命令按 2550 的行锁
   先后执行：先提交审批时，备注的保存返回 FROZEN_BY_APPROVAL；先保存备注时，备注写入，审批照常提交。驳回、改回备注。
4. 两个命令同时为同一张单据发起审批：chengben01 改 206323 的单价、admin 改 206324 的单价同时提交，只有一个提交审批，
   另一个返回 409 FROZEN_BY_APPROVAL（details 给出先提交的审批）。驳回。

样例二（C06 7.9、7.10）在 d_cg 中没有配置，不在本文件中（见任务卡）。测试建的 ADMIN 角色账号、产生的审批、投递、
站内通知和命令记录在结束时删掉（dcg.Cleanup）。
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text

from .dcg import PAGE, Cleanup, detail_change, document, goods, rows, save_command
from .servers import Backend, Browser

pytestmark = [pytest.mark.oracle, pytest.mark.redis]

D = Decimal
ADMIN = ("admin", "admin123..")
ACCOUNTANT = ("chengben01", "Abc123..")
DOCID = 2550
K30 = "206323"
PREGEL = "206324"


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


@pytest.fixture
def before(admin: Browser, accountant: Browser, dcg: Engine, cleanup: Cleanup) -> Iterator[tuple[Any, Any]]:
    """改前的 2550 和物料清单 25；测试结束时核对两者都已恢复。测试在单价已写成 90 之后中途失败时，先驳回本测试还在
    审批中的审批，再经平台把单价改回（再走一次审批、admin 通过）。"""
    snapshot = (document(dcg, DOCID), goods(dcg, 25))
    original = by_key(snapshot[0][1], K30)["price"]
    yield snapshot
    if by_key(document(dcg, DOCID)[1], K30)["price"] != original:
        for approval_id in cleanup.approvals:
            if approval_state(dcg, approval_id)["status"] == "pending":
                reject(admin, cleanup, approval_id)
        approve(admin, cleanup, submitted(save(accountant, cleanup, price(K30, str(original)))))
    assert (document(dcg, DOCID), goods(dcg, 25)) == snapshot


def save(browser: Browser, cleanup: Cleanup, documents: list[dict[str, Any]]) -> httpx.Response:
    response = browser.post("/api/commands", save_command(cleanup.key(), documents))
    if response.status_code == 200:
        cleanup.result(response.json())
    return response


def price(dtlid: str, value: str) -> list[dict[str, Any]]:
    return [detail_change("2550", "COST_MATERIAL", dtlid, {"PRICE": value})]


def memo(value: str | None) -> list[dict[str, Any]]:
    return [{"entity": PAGE, "master": {"op": "modify", "rowKey": "2550", "changes": {"MEMO": value}}, "details": []}]


def submitted(response: httpx.Response) -> str:
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["outcome"] == "approvalSubmitted", result
    [approval] = result["approvals"]
    assert approval["document"] == {"entity": PAGE, "recordKey": "2550"} and approval["flows"] == ["COST_TO_GOODS"]
    return str(approval["approvalId"])


def pass_body(browser: Browser, cleanup: Cleanup, approval_id: str) -> dict[str, Any]:
    """通过请求：指纹取自审批详情；COST_TO_GOODS 的物料清单一块是 selection all，不能改勾选，不用提交 checkedRows。"""
    detail = browser.ok(browser.get(f"/api/approvals/{approval_id}"))
    return {"requestKey": cleanup.key(), "fingerprint": detail["fingerprint"], "checkedRows": [], "comment": "G5 联调通过",
            "params": {}}


def approve(browser: Browser, cleanup: Cleanup, approval_id: str) -> dict[str, Any]:
    result = browser.ok(browser.post(f"/api/approvals/{approval_id}/pass", pass_body(browser, cleanup, approval_id)))
    assert result["outcome"] == "approvalProcessed" and result["approvals"][0]["status"] == "approved", result
    return result


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


PENDING = {"status": "pending", "current_level": 1, "pending_status": "pending",
           "freezes": {("T_COST_PINGGU", "2550"), ("T_COST_GOODS", "25")}, "actions": []}


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
                                                           dcg: Engine, cleanup: Cleanup, before: tuple[Any, Any]) -> None:
    (master0, details0), goods0 = before
    approval_id = submitted(save(accountant, cleanup, price(K30, "90")))
    assert approval_state(dcg, approval_id) == PENDING
    assert (document(dcg, DOCID), goods(dcg, 25)) == before  # 审批结束前不写业务表

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
    frozen = admin.post("/api/commands", save_command(key, memo("G5 冻结中")))
    assert frozen.status_code == 409 and frozen.json()["code"] == "FROZEN_BY_APPROVAL", frozen.text
    assert frozen.json()["details"][0]["approvalId"] == approval_id
    sql = review_sql(admin, key)
    assert [s.split(" ")[0] for s in sql] == ["INSERT", "SELECT", "SELECT"] and "PF_APPROVAL_FREEZE" in sql[2].upper()

    # 或签：两名审批人同时通过，只有一个生效
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
    master1, details1 = document(dcg, DOCID)
    k30 = by_key(details1, K30)
    assert (D(str(k30["price"])), D(str(k30["cost_batch"]))) == (D(90), D(900))
    assert [d for d in details1 if str(d["dtlid"]) != K30] == [d for d in details0 if str(d["dtlid"]) != K30]
    fl = D(str(master0["total_fl"])) + D(150) / D("1.13")  # 辅料合计多 150（750 → 900），有原料时除以 1.13
    assert abs(D(str(master1["total_fl"])) - fl) <= D("0.00000002")
    assert master1["memo"] == master0["memo"]
    goods1 = goods(dcg, 25)
    assert D(str(goods1["zx_price"])) == D(90) and {**goods1, "zx_price": goods0["zx_price"]} == goods0

    # 重复批准：同一请求键再提交，返回原结果，不重复执行
    winner = [admin, second_approver][won]
    replay = winner.post(f"/api/approvals/{approval_id}/pass", bodies[won])
    assert replay.status_code == 200 and replay.json() == result
    assert approval_state(dcg, approval_id)["actions"] == ["pass"]
    assert (document(dcg, DOCID), goods(dcg, 25)) == ((master1, details1), goods1)

    # 改回 75：75 与执行价 90 不同，再走一次审批
    back = submitted(save(accountant, cleanup, price(K30, "75")))
    approve(admin, cleanup, back)


# ---------------------------------------------------------------- 2：最终批准中一步失败，整体回滚

def test_final_approval_step_fails_and_rolls_back(admin: Browser, accountant: Browser, dcg: Engine, cleanup: Cleanup,
                                                  before: tuple[Any, Any]) -> None:
    approval_id = submitted(save(accountant, cleanup, price(K30, "90")))
    body = pass_body(admin, cleanup, approval_id)
    with dcg.connect() as holder:  # 另一个会话锁住物料清单 25，最终批准写执行价时等锁超时
        holder.execute(text("SELECT goodsid FROM t_cost_goods WHERE goodsid = 25 FOR UPDATE"))
        response = admin.post(f"/api/approvals/{approval_id}/pass", body)
        holder.rollback()
    assert response.status_code == 409 and response.json()["code"] == "DOCUMENT_BUSY", response.text
    assert approval_state(dcg, approval_id) == PENDING  # 处理记录、状态、解冻都回滚了
    assert (document(dcg, DOCID), goods(dcg, 25)) == before
    assert rows(dcg, "SELECT 1 FROM pf_command WHERE request_key = :k", k=body["requestKey"]) == []
    reject(admin, cleanup, approval_id)


# ---------------------------------------------------------------- 3：审批提交与普通保存同时进行

def test_submission_and_plain_save_at_the_same_time(admin: Browser, accountant: Browser, dcg: Engine, cleanup: Cleanup,
                                                    before: tuple[Any, Any]) -> None:
    (master0, _), _ = before
    keys = cleanup.key(), cleanup.key()
    submit, plain = together(lambda: accountant.post("/api/commands", save_command(keys[0], price(K30, "90"))),
                             lambda: admin.post("/api/commands", save_command(keys[1], memo("G5 同时保存"))))
    approval_id = submitted(submit)
    cleanup.result(submit.json())
    if plain.status_code == 200:
        print("先执行备注的保存，再提交审批")
        assert plain.json()["outcome"] == "saved"
        assert document(dcg, DOCID)[0]["memo"] == "G5 同时保存"  # type: ignore[index]
    else:
        print("先提交审批，备注的保存被冻结拒绝")
        assert (plain.status_code, plain.json()["code"]) == (409, "FROZEN_BY_APPROVAL"), plain.text
        assert plain.json()["details"][0]["approvalId"] == approval_id
        assert document(dcg, DOCID)[0]["memo"] == master0["memo"]  # type: ignore[index]
    assert approval_state(dcg, approval_id) == PENDING
    assert D(str(by_key(document(dcg, DOCID)[1], K30)["price"])) == D(75)
    reject(admin, cleanup, approval_id)
    if plain.status_code == 200:
        assert save(admin, cleanup, memo(master0["memo"])).json()["outcome"] == "saved"


# ---------------------------------------------------------------- 4：两个命令同时为同一张单据发起审批

def test_two_submissions_for_one_document_only_one_succeeds(admin: Browser, accountant: Browser, dcg: Engine,
                                                            cleanup: Cleanup, before: tuple[Any, Any]) -> None:
    keys = cleanup.key(), cleanup.key()
    responses = together(lambda: accountant.post("/api/commands", save_command(keys[0], price(K30, "90"))),
                         lambda: admin.post("/api/commands", save_command(keys[1], price(PREGEL, "13"))))
    assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
    won = next(i for i, r in enumerate(responses) if r.status_code == 200)
    approval_id = submitted(responses[won])
    cleanup.result(responses[won].json())
    lost = responses[1 - won].json()
    print(f"同时发起审批：{['chengben01 改 206323', 'admin 改 206324'][won]} 提交成功，另一个 {lost['code']}")
    assert lost["code"] == "FROZEN_BY_APPROVAL" and lost["details"][0]["approvalId"] == approval_id
    frozen_goods = ["25", "68"][won]
    assert approval_state(dcg, approval_id) == {**PENDING, "freezes": {("T_COST_PINGGU", "2550"), ("T_COST_GOODS", frozen_goods)}}
    pending = rows(dcg, "SELECT approval_id FROM pf_approval WHERE source_key = '2550' AND status = 'pending'")
    assert [str(r["approval_id"]) for r in pending] == [approval_id]
    assert (document(dcg, DOCID), goods(dcg, 25)) == before
    reject(admin, cleanup, approval_id)
