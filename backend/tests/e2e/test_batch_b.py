"""T-AS-5 批次 B 真实联调（d_cg + Redis；架构 10.2、10.8、10.9）。后端为 conftest 的两个进程 A、B（servers.py）。

1. 改一格（成本单 2550）：主表备注改了再改回；原辅料 206324 预胶化淀粉的每片含量 15 → 16，后端按计算规则重算
   每批数量、每批成本和主表汇总后写入，再改回 15，主表和明细全部列与改前相同。
2. 新增和删除明细、删除主表：admin 新建一张成本单（主表 + 两行原辅料），再在一次保存里新增一行、删除一行，
   最后删除主表，明细一起删除。
3. SQL 条数（WP-10）：用命令审查（WP-17，`/api/admin/command-review`，在命令事务内用 SqlTracer 计数）读取上面各次
   保存的语句。成本核算是可冻结业务，每次多 1 条冻结查询；改原辅料的行时，审批流 COST_TO_GOODS 的入口条件对这一行
   执行 1 条（approval AP-01），WP-10 没有计这一条，单独列出；进程启动后第一次写某张表的命令，另有 1 条读取列定义
   （user_tab_columns，WP-15 的小数位，每个进程每张表只读一次），也单独列出。
4. 规则拒绝时整笔回滚：同一次保存改了主表备注、206323 的备注，又把 206324 的每片含量改成 0，规则 R_MAT_PER_HL_GT0
   拒绝（422 RULE_REJECTED），主表、明细都不变，没有命令记录。
5. 通知在提交后送达：chengben01 在 B 把 206323 聚维酮K30 的单价 75 改成 90，进入审批 COST_TO_GOODS；连在 A 上的 admin
   的 WebSocket 收到 notification 时，审批已经提交、投递记录已是 sent，站内通知中有这一条。最后驳回（单价不变）。
6. 发送失败不影响业务：在测试进程内组装后端（create_app），把写站内通知替换成抛错（模拟，只对本测试的投递），
   chengben01 提交审批照常成功，审批和冻结已提交，投递记录为 failed、发送次数 1、记下错误，没有站内通知。
7. 列表和导出符合行权限：测试角色 COST_ACCOUNTANT 临时加行权限 `DOCID IN (2550, 2556)`，chengben01 的列表、按主键取行、
   单据加载和默认导出都只有这两张；admin 不受影响。最后改回角色配置。

测试产生的审批、投递、站内通知和命令记录在结束时删掉（dcg.Cleanup）。
"""

from __future__ import annotations

import copy
import io
import time
import uuid
import zipfile
from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from cost_platform.assembly.app import create_app
from cost_platform.delivery.store import DeliveryStore

from .dcg import PAGE, Cleanup, detail_change, document, rows, save_command
from .servers import ORIGIN, Backend, Browser, redis_namespace

pytestmark = [pytest.mark.oracle, pytest.mark.redis]

D = Decimal
ADMIN = ("admin", "admin123..")
ACCOUNTANT = ("chengben01", "Abc123..")
DOCID = 2550
K30 = "206323"         # 聚维酮K30，物料 25，单价 75，与物料清单执行价相同
PREGEL = "206324"      # 预胶化淀粉，物料 68，每片含量 15，单价 12.5
NOTICE_TITLE = "您有来自于成本核算页面，业务单据为2550的审批"


@pytest.fixture(scope="module")
def admin(servers: list[Backend]) -> Iterator[Browser]:
    browser = Browser(servers[0], *ADMIN)
    browser.ok(browser.put("/api/admin/command-review", {"enabled": True}))
    yield browser
    browser.ok(browser.put("/api/admin/command-review", {"enabled": False}))  # 关闭时删除本命名空间的审查记录
    browser.close()


@pytest.fixture(scope="module")
def accountant(servers: list[Backend]) -> Iterator[Browser]:
    browser = Browser(servers[1], *ACCOUNTANT)
    yield browser
    browser.close()


def save(browser: Browser, cleanup: Cleanup, documents: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    key = cleanup.key()
    response = browser.post("/api/commands", save_command(key, documents))
    assert response.status_code == 200, response.text
    return key, cleanup.result(response.json())


def sql_of(admin: Browser, key: str, label: str) -> list[str]:
    """命令审查中这个请求键的语句（SQL 追踪：一次 execute 或 executemany 计 1 条，提交、回滚不计）。
    输出到标准输出作为证据（`pytest -rP` 显示）。"""
    logs = admin.ok(admin.get("/api/admin/command-review", params={"startRow": 0, "endRow": 200}))["rows"]
    [log] = [entry for entry in logs if entry["requestKey"] == key]
    assert log["sqlCount"] == len(log["sql"])
    texts = [s["text"] for s in log["sql"]]
    print(f"== {label}：{log['sqlCount']} 条")
    print("\n".join(f"  {i}. {s[:160]}" for i, s in enumerate(texts, start=1)))
    return texts


def is_freeze_query(sql: str) -> bool:
    return "PF_APPROVAL_FREEZE" in sql.upper() and sql.upper().startswith("SELECT")


def is_entry_condition(sql: str) -> bool:
    """审批流的入口条件（approval 的 `SELECT 1 FROM DUAL WHERE (<条件>)`）。"""
    return sql.upper().startswith("SELECT 1 FROM DUAL WHERE")


def is_schema_query(sql: str) -> bool:
    """读取列定义（db-core 的 SchemaInspector，WP-15 取列的小数位）：每个进程每张表只读一次，进程启动后第一次写这张表的
    命令多这 1 条，之后的命令没有。"""
    return "USER_TAB_COLUMNS" in sql.upper()


def is_config_refresh(sql: str) -> bool:
    """重读配置（config 的 pf_config_item）：同一次运行中别的测试刚发布过配置、代次变了，这个进程之后的第一个命令先重读
    一次；单独运行本文件时没有。"""
    return "FROM PF_CONFIG_ITEM" in sql.upper()


def once(sql: list[str]) -> int:
    """进程内只在某个命令中出现一次、不计入 WP-10 的语句条数：列定义、重读配置。"""
    return sum(map(is_schema_query, sql)) + sum(map(is_config_refresh, sql))


def counted(sql: list[str]) -> list[str]:
    """WP-10 计数的语句：去掉冻结查询、审批入口条件和进程内只读一次的列定义、重读配置。"""
    return [s for s in sql
            if not (is_freeze_query(s) or is_entry_condition(s) or is_schema_query(s) or is_config_refresh(s))]


def kinds(sql: list[str]) -> list[str]:
    return [s.split(" ")[0].upper() for s in sql]


def master_memo(docid: str, memo: str | None) -> dict[str, Any]:
    return {"entity": PAGE, "master": {"op": "modify", "rowKey": docid, "changes": {"MEMO": memo}}, "details": []}


def by_key(details: list[dict[str, Any]], dtlid: str) -> dict[str, Any]:
    return next(d for d in details if str(d["dtlid"]) == dtlid)


def q8(value: Decimal) -> Decimal:
    """WP-15：最多保留 8 位小数，按第 9 位四舍五入。"""
    return value.quantize(D("0.00000001"), rounding=ROUND_HALF_UP)


def material_total(details: list[dict[str, Any]], useflag: str, engine: Engine) -> Decimal:
    found = rows(engine, "SELECT dtlid FROM v_cost_pinggu_material WHERE docid = :d AND dtl_useflag = :u", d=DOCID, u=useflag)
    keys = {str(r["dtlid"]) for r in found}
    return sum((D(str(d["cost_batch"])) for d in details if str(d["dtlid"]) in keys), D(0))


# ---------------------------------------------------------------- 1、3：改一格和 SQL 条数

@pytest.fixture
def restore_2550(admin: Browser, dcg: Engine, cleanup: Cleanup) -> Iterator[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """测试中途失败时，经平台把 2550 的主表备注和 206324 的每片含量改回改前的值。"""
    before = document(dcg, DOCID)
    yield before  # type: ignore[misc]
    if document(dcg, DOCID) != before:
        master, details = before
        pregel = str(by_key(details, PREGEL)["per_hl"])
        save(admin, cleanup, [{"entity": PAGE, "master": {"op": "modify", "rowKey": "2550", "changes": {"MEMO": master["memo"]}},
                               "details": [{"entity": "COST_MATERIAL", "op": "modify", "rowKey": PREGEL,
                                            "changes": {"PER_HL": pregel}}]}])
        assert document(dcg, DOCID) == before


def test_one_cell_saves_and_sql_counts(admin: Browser, dcg: Engine, cleanup: Cleanup,
                                       restore_2550: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    master_before, details_before = restore_2550
    memo = master_before["memo"]

    # 改主表一个字段：WP-10 的 4 条，加冻结查询 1 条
    key, result = save(admin, cleanup, [master_memo("2550", "G5 联调备注")])
    assert result["outcome"] == "saved"
    sql = sql_of(admin, key, "改主表一个字段（MEMO）")
    assert sum(map(is_freeze_query, sql)) == 1 and sum(map(is_schema_query, sql)) <= 1, "\n".join(sql)
    assert kinds(counted(sql)) == ["INSERT", "SELECT", "UPDATE", "UPDATE"], "\n".join(sql)
    assert len(sql) == 5 + once(sql)
    master_after, details_after = document(dcg, DOCID)
    assert master_after == {**master_before, "memo": "G5 联调备注"}
    assert details_after == details_before

    # 提交的值与当前值相同：WP-10 的 2 条（插入命令记录、加锁读取，然后回滚），加冻结查询 1 条
    key, result = save(admin, cleanup, [master_memo("2550", "G5 联调备注")])
    assert result["outcome"] == "unchanged"
    sql = sql_of(admin, key, "提交相同的值")
    assert len(sql) == 3 and sum(map(is_freeze_query, sql)) == 1, "\n".join(sql)
    assert kinds(counted(sql)) == ["INSERT", "SELECT"], "\n".join(sql)
    assert rows(dcg, "SELECT 1 FROM pf_command WHERE request_key = :k", k=key) == []

    _, result = save(admin, cleanup, [master_memo("2550", memo)])
    assert result["outcome"] == "saved"
    assert document(dcg, DOCID) == (master_before, details_before)

    # 改一条明细并重算汇总：WP-10 的 6 条，加冻结查询 1 条、COST_TO_GOODS 对这一行的入口条件 1 条
    key, result = save(admin, cleanup, [detail_change("2550", "COST_MATERIAL", PREGEL, {"PER_HL": "16"})])
    assert result["outcome"] == "saved"
    sql = sql_of(admin, key, "改一条明细并重算汇总（206324 每片含量 15→16）")
    core = counted(sql)
    assert sum(map(is_freeze_query, sql)) == 1 and sum(map(is_entry_condition, sql)) == 1, "\n".join(sql)
    assert sum(map(is_schema_query, sql)) <= 1, "\n".join(sql)
    assert kinds(core) == ["INSERT", "SELECT", "SELECT", "UPDATE", "UPDATE", "UPDATE"], "\n".join(sql)
    assert "FOR UPDATE" in core[1].upper() and "UNION ALL" in core[2].upper(), "\n".join(sql)
    assert len(sql) == 8 + once(sql)

    master_after, details_after = document(dcg, DOCID)
    changed = by_key(details_after, PREGEL)
    assert (D(str(changed["per_hl"])), D(str(changed["batch_qty"])), D(str(changed["cost_batch"]))) == (D(16), D(16), D(200))
    assert [d for d in details_after if str(d["dtlid"]) != PREGEL] == [d for d in details_before if str(d["dtlid"]) != PREGEL]
    fl, yl = material_total(details_after, "辅料", dcg), material_total(details_after, "原料", dcg)
    assert yl > 0 and abs(D(str(master_after["total_fl"])) - q8(fl / D("1.13"))) <= D("0.00000001")
    assert D(str(master_after["total_fl"])) != D(str(master_before["total_fl"]))
    parts = sum((D(str(master_after[c])) for c in ("total_yl", "total_fl", "total_bc")), D(0))
    assert abs(D(str(master_after["total_cost"])) - parts) <= D("0.00000002")
    returned = {(r["entity"], r["rowKey"]): r["values"] for r in result["rows"]}
    assert D(returned[("COST_MATERIAL", PREGEL)]["COST_BATCH"]) == D(200)
    assert D(returned[(PAGE, "2550")]["TOTAL_FL"]) == D(str(master_after["total_fl"]))  # 命令结果与数据库相同

    _, result = save(admin, cleanup, [detail_change("2550", "COST_MATERIAL", PREGEL, {"PER_HL": "15"})])
    assert result["outcome"] == "saved"
    assert document(dcg, DOCID) == (master_before, details_before)


# ---------------------------------------------------------------- 2：新增和删除明细、删除主表

def test_new_document_add_delete_details_then_delete_master(admin: Browser, dcg: Engine, cleanup: Cleanup) -> None:
    m, d1, d2, d3 = (f"tmp-{uuid.uuid4()}" for _ in range(4))
    values = {"MEMO": "G5 联调新单据", "APEX_PL": "1000000", "P_PERPACK": "112", "S_PERBACK": "80", "YIELD": "93.94"}
    # 物料清单执行价：25 为 75、68 为 12.5、310 为 22；单价与执行价相同，不进入审批
    adds = [{"entity": "COST_MATERIAL", "op": "add", "clientRowId": d1, "values": {"GOODSID": "25", "PER_HL": "10", "PRICE": "75"}},
            {"entity": "COST_MATERIAL", "op": "add", "clientRowId": d2, "values": {"GOODSID": "68", "PER_HL": "15", "PRICE": "12.5"}}]
    _, result = save(admin, cleanup, [{"entity": PAGE, "master": {"op": "add", "clientRowId": m, "values": values}, "details": adds}])
    assert result["outcome"] == "saved" and set(result["idMap"]) == {m, d1, d2}, result
    docid = int(result["idMap"][m])
    try:
        head, lines = document(dcg, docid)
        assert head is not None and head["memo"] == "G5 联调新单据" and D(str(head["apex_pl"])) == D(1000000)
        assert [(int(x["goodsid"]), D(str(x["per_hl"])), D(str(x["batch_qty"])), D(str(x["cost_batch"]))) for x in lines] == [
            (25, D(10), D(10), D(750)), (68, D(15), D(15), D("187.5"))]
        assert [str(x["dtlid"]) for x in lines] == [result["idMap"][d1], result["idMap"][d2]]
        assert D(str(head["total_fl"])) == D("937.5")  # 没有原料，辅料合计不除以 1.13

        # 一次保存里新增一行、删除一行
        changes = [{"entity": "COST_MATERIAL", "op": "add", "clientRowId": d3, "values": {"GOODSID": "310", "PER_HL": "42.5", "PRICE": "22"}},
                   {"entity": "COST_MATERIAL", "op": "delete", "rowKey": result["idMap"][d2]}]
        _, second = save(admin, cleanup, [{"entity": PAGE, "master": {"op": "none", "rowKey": str(docid)}, "details": changes}])
        assert second["outcome"] == "saved" and set(second["idMap"]) == {d3}
        assert {"entity": "COST_MATERIAL", "rowKey": result["idMap"][d2], "deleted": True} in second["rows"]
        head, lines = document(dcg, docid)
        assert [(int(x["goodsid"]), D(str(x["cost_batch"]))) for x in lines] == [(25, D(750)), (310, D(935))]
        assert D(str(head["total_fl"])) == D(1685)

        # 删除主表：明细一起删除（WP-06）
        _, third = save(admin, cleanup, [{"entity": PAGE, "master": {"op": "delete", "rowKey": str(docid)}, "details": []}])
        assert third["outcome"] == "saved"
        assert {"entity": PAGE, "rowKey": str(docid), "deleted": True} in third["rows"]
        assert document(dcg, docid) == (None, [])
    finally:
        with dcg.begin() as conn:  # 中途失败时删掉建的单据
            conn.execute(text("DELETE FROM t_cost_pinggu_dtl WHERE docid = :d"), {"d": docid})
            conn.execute(text("DELETE FROM t_cost_pinggu WHERE docid = :d"), {"d": docid})


# ---------------------------------------------------------------- 4：规则拒绝时整笔回滚

def test_rule_rejection_rolls_back_whole_save(admin: Browser, dcg: Engine, cleanup: Cleanup) -> None:
    before = document(dcg, DOCID)
    key = cleanup.key()
    doc = {"entity": PAGE, "master": {"op": "modify", "rowKey": "2550", "changes": {"MEMO": "G5 规则拒绝"}},
           "details": [{"entity": "COST_MATERIAL", "op": "modify", "rowKey": K30, "changes": {"MEMO": "G5 规则拒绝"}},
                       {"entity": "COST_MATERIAL", "op": "modify", "rowKey": PREGEL, "changes": {"PER_HL": "0"}}]}
    response = admin.post("/api/commands", save_command(key, [doc]))
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "RULE_REJECTED"
    assert [(d["message"], d["rowKey"], d["field"]) for d in body["details"]] == [("每片含量必填且必须大于0", PREGEL, "PER_HL")]
    assert document(dcg, DOCID) == before
    assert rows(dcg, "SELECT 1 FROM pf_command WHERE request_key = :k", k=key) == []
    logs = admin.ok(admin.get("/api/admin/command-review", params={"startRow": 0, "endRow": 200}))["rows"]
    [log] = [entry for entry in logs if entry["requestKey"] == key]
    assert (log["result"], log["errorCode"]) == ("rejected", "RULE_REJECTED")


# ---------------------------------------------------------------- 5、6：通知

def reject(admin: Browser, cleanup: Cleanup, approval_id: str, comment: str) -> dict[str, Any]:
    response = admin.post(f"/api/approvals/{approval_id}/reject", {"requestKey": cleanup.key(), "comment": comment})
    assert response.status_code == 200, response.text
    return response.json()


def test_notification_reaches_approver_after_commit(admin: Browser, accountant: Browser, dcg: Engine,
                                                    cleanup: Cleanup) -> None:
    before = document(dcg, DOCID)
    with admin.ws() as ws:
        key, result = save(accountant, cleanup, [detail_change("2550", "COST_MATERIAL", K30, {"PRICE": "90"})])
        assert result["outcome"] == "approvalSubmitted"
        [approval] = result["approvals"]
        notice = ws.wait(lambda m: m.get("topic") == "notification" and m["payload"]["title"] == NOTICE_TITLE)
        # 收到推送时：审批已提交，投递记录已标为 sent（发送在提交之后，各自一个事务）
        [delivery] = rows(dcg, "SELECT request_key, recipient, status, attempts FROM pf_delivery WHERE delivery_id = :d",
                          d=notice["payload"]["deliveryId"])
        assert delivery == {"request_key": key, "recipient": "1", "status": "sent", "attempts": 1}
        [record] = rows(dcg, "SELECT status, current_level FROM pf_approval WHERE approval_id = :a", a=int(approval["approvalId"]))
        assert record == {"status": "pending", "current_level": 1}
    inbox = admin.ok(admin.get("/api/inbox", params={"unread": "true", "startRow": 0, "endRow": 100}))
    assert notice["payload"]["deliveryId"] in [r["deliveryId"] for r in inbox["rows"]]
    assert document(dcg, DOCID) == before  # 审批中，单价没有写入

    rejected = reject(admin, cleanup, approval["approvalId"], "G5 联调：通知已送达，驳回")
    assert rejected["outcome"] == "approvalProcessed"
    assert document(dcg, DOCID) == before
    assert rows(dcg, "SELECT 1 FROM pf_approval_freeze WHERE approval_id = :a", a=int(approval["approvalId"])) == []


@pytest.fixture
def in_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """在测试进程内按 `.env` 组装后端（create_app），命名空间和允许的来源与 servers.py 相同（只改本测试进程的环境，
    monkeypatch 结束时还原）。"""
    monkeypatch.setenv("PLATFORM_REDIS_NAMESPACE", redis_namespace())
    monkeypatch.setenv("PLATFORM_ALLOWED_ORIGINS", ORIGIN)
    with TestClient(create_app(), base_url="http://localhost:9534", headers={"Origin": ORIGIN}) as client:
        deadline = time.monotonic() + 120
        while client.get("/health").status_code != 200:
            assert time.monotonic() < deadline, "进程内的后端 120 秒内没有就绪"
            time.sleep(0.2)
        yield client


def test_delivery_failure_does_not_affect_business(monkeypatch: pytest.MonkeyPatch, in_process: TestClient, dcg: Engine,
                                                   cleanup: Cleanup) -> None:
    """模拟发送失败：本测试命令的投递在写站内通知时抛错（只替换测试进程内的 `DeliveryStore.write_inbox`）。"""
    key = cleanup.key()
    original = DeliveryStore.write_inbox

    def failing(uow: Any, record: Any, now: Any) -> None:
        owner = uow.connection.execute(text("SELECT request_key FROM pf_delivery WHERE delivery_id = :d"),
                                       {"d": record.delivery_id}).scalar_one()
        if owner == key:
            raise RuntimeError("模拟：写站内通知失败")
        original(uow, record, now)

    monkeypatch.setattr(DeliveryStore, "write_inbox", staticmethod(failing))
    before = document(dcg, DOCID)
    login = in_process.post("/api/auth/login", json={"username": ACCOUNTANT[0], "password": ACCOUNTANT[1]})
    assert login.status_code == 200, login.text
    command = save_command(key, [detail_change("2550", "COST_MATERIAL", K30, {"PRICE": "90"})])
    response = in_process.post("/api/commands", json=command, headers={"X-CSRF-Token": login.json()["csrfToken"]})
    assert response.status_code == 200, response.text
    result = cleanup.result(response.json())
    assert result["outcome"] == "approvalSubmitted"
    [approval] = result["approvals"]
    approval_id = int(approval["approvalId"])
    # 业务照常提交：审批、冻结都在
    assert rows(dcg, "SELECT status FROM pf_approval WHERE approval_id = :a", a=approval_id) == [{"status": "pending"}]
    assert {(r["root_table"], r["record_key"]) for r in rows(dcg, "SELECT root_table, record_key FROM pf_approval_freeze "
                                                             "WHERE approval_id = :a", a=approval_id)} == {
        ("T_COST_PINGGU", "2550"), ("T_COST_GOODS", "25")}
    [delivery] = rows(dcg, "SELECT delivery_id, status, attempts, last_error, next_retry_at FROM pf_delivery "
                           "WHERE request_key = :k", k=key)
    assert (delivery["status"], delivery["attempts"]) == ("failed", 1)
    assert "模拟：写站内通知失败" in delivery["last_error"] and delivery["next_retry_at"] is not None
    assert rows(dcg, "SELECT 1 FROM pf_inbox WHERE delivery_id = :d", d=delivery["delivery_id"]) == []
    assert document(dcg, DOCID) == before


# ---------------------------------------------------------------- 7：列表和导出符合行权限

def xlsx_rows(content: bytes) -> list[list[str]]:
    """第一张工作表的各行：文本为共享字符串，数值单元格取 `<v>` 的原文（QE-06）。"""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(content)) as book:
        strings = ["".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t"))
                   for si in ElementTree.fromstring(book.read("xl/sharedStrings.xml")).findall("m:si", ns)]
        sheet = ElementTree.fromstring(book.read("xl/worksheets/sheet1.xml"))
    return [[strings[int(c.findtext("m:v", "", ns))] if c.get("t") == "s" else c.findtext("m:v", "", ns)
             for c in row.findall("m:c", ns)] for row in sheet.iter(f"{{{ns['m']}}}row")]


LIST = {"startRow": 0, "endRow": 100, "sortModel": [{"colId": "DOCID", "sort": "asc"}], "filterModel": {}}


def test_list_and_export_follow_row_permission(admin: Browser, accountant: Browser, dcg: Engine) -> None:
    role = admin.ok(admin.get("/api/config/items/role/COST_ACCOUNTANT"))
    assert "rows" not in role["content"]["pages"]["COST_PINGGU"]
    limited = copy.deepcopy(role)
    limited["content"]["pages"]["COST_PINGGU"]["rows"] = "DOCID IN (2550, 2556)"
    total = rows(dcg, "SELECT COUNT(*) AS n FROM t_cost_pinggu")[0]["n"]
    admin.ok(admin.put("/api/config/items/role/COST_ACCOUNTANT", {"name": role["name"], "content": limited["content"]}))
    try:
        listed = accountant.ok(accountant.post(f"/api/pages/{PAGE}/rows", LIST))
        assert listed["total"] == 2 and [r["rowKey"] for r in listed["rows"]] == ["2550", "2556"]
        found = accountant.ok(accountant.post(f"/api/pages/{PAGE}/rows/by-keys", {"entity": PAGE, "rowKeys": ["2550", "200680"]}))
        assert [r["rowKey"] for r in found["rows"]] == ["2550"]
        assert accountant.get(f"/api/pages/{PAGE}/records/2550").status_code == 200
        assert accountant.get(f"/api/pages/{PAGE}/records/200680").status_code == 404
        exported = accountant.post(f"/api/pages/{PAGE}/export", {"mode": "page", "request": LIST, "columns": ["DOCID", "GOODSNAME"]})
        assert exported.status_code == 200, exported.text
        sheet = xlsx_rows(exported.content)
        assert [r[0] for r in sheet[1:]] == ["2550", "2556"], sheet
        assert admin.ok(admin.post(f"/api/pages/{PAGE}/rows", LIST))["total"] == total
    finally:
        admin.ok(admin.put("/api/config/items/role/COST_ACCOUNTANT", {"name": role["name"], "content": role["content"]}))
    assert admin.ok(admin.get("/api/config/items/role/COST_ACCOUNTANT"))["content"] == role["content"]
    assert accountant.ok(accountant.post(f"/api/pages/{PAGE}/rows", LIST))["total"] == total
