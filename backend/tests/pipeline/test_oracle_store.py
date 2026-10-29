"""T-WP-2、T-WP-3 的真实验证（d_cg）：加锁读取、合并、写入、审计、行权限、TableWriter。

等锁超时、死锁返回 DOCUMENT_BUSY 属于用户没有点名的异常情况，任务卡标为上线后再补（工程约定第 5 节）。
前提：已执行 `platform db upgrade`（PF_COMMAND）。测试表由 `oracle_support` 建立和删除。
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine

from cost_platform.contracts import types as t
from cost_platform.db_core.engine import OracleUnitOfWorkFactory
from cost_platform.pipeline.document_store import DetailSource, OracleDocumentStore
from cost_platform.pipeline.table_writer import OracleTableWriter

from .oracle_support import (  # noqa: F401  fixtures
    DOC,
    ENTITIES,
    GOODS,
    GOODS_PAGE,
    GOODS_SAVE,
    MATERIAL,
    PACKAGE,
    PAGE,
    SAVE,
    USERS,
    WpSetup,
    engine,
    fetch,
    inspector,
    master_modify,
    master_none,
    rows,
)
from .support import TMP_1, TMP_2, Pipeline, command

pytestmark = pytest.mark.oracle
D = Decimal


def pipeline(engine: Engine, setup: WpSetup | None = None) -> Pipeline:
    return Pipeline(setup=setup or WpSetup(), store=OracleDocumentStore(5), factory=OracleUnitOfWorkFactory(engine),  # type: ignore[arg-type]
                    inspector=inspector())


def save(documents: list[dict[str, Any]], page: str = PAGE, operation: str = SAVE) -> t.Command:
    import uuid

    return command(documents, request_key=str(uuid.uuid4()), page=page, operation=operation)


def row_result(entity: str, row_key: str | None = None, client_row_id: str | None = None, **computed: str) -> t.EvalRowResult:
    return t.EvalRowResult(entity=entity, row_key=row_key, client_row_id=client_row_id, computed=computed, fields={},
                           style=t.RowStyle(row=None, cells={}))


def dtl(engine: Engine, key: int) -> dict[str, Any]:
    found = fetch(engine, "SELECT * FROM T_WP_DTL WHERE DTLID = :k", k=key)
    return found[0] if found else {}


def test_lock_and_read_details_through_views(rows: Engine) -> None:
    store = OracleDocumentStore(5)
    with OracleUnitOfWorkFactory(rows).begin() as uow:
        masters = store.lock_load(uow, DOC, ENTITIES[DOC], ["1002", "1001"])
        details = store.load_details_many(uow, [DetailSource(MATERIAL, ENTITIES[MATERIAL], "DOCID"),
                                                DetailSource(PACKAGE, ENTITIES[PACKAGE], "DOCID")], ["1001", "1002"])
    assert list(masters) == ["1001", "1002"] and masters["1002"].values["MEMO"] == "旧备注"
    assert [r.row_key for r in details[MATERIAL]["1001"]] == ["5001", "5002"]
    assert [r.row_key for r in details[PACKAGE]["1001"]] == ["6001"]
    assert details[MATERIAL]["1001"][0].values["PRICE"] == D("3.5")


def test_e05_writes_changed_and_calculated_columns(rows: Engine) -> None:
    p = pipeline(rows)
    p.setup.engine.respond(t.EvalComputed(ok=True, rows=[row_result(MATERIAL, "5001", COST_BATCH="7.6"),
                                                         row_result(DOC, "1001", TOTAL_COST="54.6")], effects=[]))
    result = p.execute(save([master_none("1001", [
        {"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {"PRICE": "3.80", "USAGE": "2"}}])]), p.setup.context())
    assert result.outcome == "saved"
    row = dtl(rows, 5001)
    assert (row["price"], row["cost_batch"], row["usage"]) == (D("3.8"), D("7.6"), 2)
    assert fetch(rows, "SELECT TOTAL_COST FROM T_WP_DOC WHERE DOCID = 1001")[0]["total_cost"] == D("54.6")
    values = {r.row_key: r.values for r in result.rows if isinstance(r, t.ResultRow)}
    assert values["5001"]["PRICE"] == "3.80" and values["1001"]["TOTAL_COST"] == "54.6"


def test_e04_rounded_values_equal_database(rows: Engine) -> None:
    p = pipeline(rows)
    p.setup.engine.respond(t.EvalComputed(ok=True, rows=[row_result(MATERIAL, "5001", COST_BATCH="1.234567885"),
                                                         row_result(DOC, "1001", TOTAL_COST="-1.234567885")], effects=[]))
    # 改规则读取的用量才会求值（WP-08，用户 2026-10-29 选乙）；求值结果由替代的规则引擎给出
    result = p.execute(save([master_none("1001", [
        {"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {"USAGE": "0.5"}}])]), p.setup.context())
    assert dtl(rows, 5001)["cost_batch"] == D("1.23456789")
    assert fetch(rows, "SELECT TOTAL_COST FROM T_WP_DOC WHERE DOCID = 1001")[0]["total_cost"] == D("-1.23456789")
    values = {r.row_key: r.values for r in result.rows if isinstance(r, t.ResultRow)}
    assert values["5001"]["COST_BATCH"] == "1.23456789" and values["1001"]["TOTAL_COST"] == "-1.23456789"


def test_add_and_delete_details_with_id_map(rows: Engine) -> None:
    p = pipeline(rows)
    result = p.execute(save([master_none("1001", [
        {"entity": MATERIAL, "op": "add", "clientRowId": TMP_1, "values": {"GOODSID": "117", "USAGE": "1", "PRICE": "1.205"}},
        {"entity": MATERIAL, "op": "delete", "rowKey": "5002"}])]), p.setup.context())
    key = int(result.id_map[TMP_1])
    assert key >= 900001
    added = dtl(rows, key)
    assert (added["docid"], added["kind"], added["goodsid"], added["price"]) == (1001, "M", 117, D("1.21"))  # NUMBER(18,2)
    assert dtl(rows, 5002) == {}


def test_new_document_with_details(rows: Engine) -> None:
    p = pipeline(rows)
    result = p.execute(save([{"entity": DOC, "master": {"op": "add", "clientRowId": TMP_1, "values": {"MEMO": "新单"}},
                              "details": [{"entity": PACKAGE, "op": "add", "clientRowId": TMP_2,
                                           "values": {"GOODSID": "300", "USAGE": "2"}}]}]), p.setup.context())
    doc, line = int(result.id_map[TMP_1]), int(result.id_map[TMP_2])
    assert dtl(rows, line)["docid"] == doc and dtl(rows, line)["kind"] == "P"


def test_delete_master_deletes_all_details_and_audits(rows: Engine) -> None:
    p = pipeline(rows)
    p.execute(save([{"entity": DOC, "master": {"op": "delete", "rowKey": "1001"}, "details": []}]), p.setup.context())
    assert fetch(rows, "SELECT DTLID FROM T_WP_DTL WHERE DOCID = 1001") == []
    assert fetch(rows, "SELECT DOCID FROM T_WP_DOC WHERE DOCID = 1001") == []
    [record] = fetch(rows, "SELECT audit_diff FROM pf_command WHERE user_id = :u", u=USERS[0])
    audit = json.loads(record["audit_diff"])
    assert [(a["entity"], a["rowKey"], a["op"]) for a in audit] == [
        (DOC, "1001", "delete"), (MATERIAL, "5001", "delete"), (MATERIAL, "5002", "delete"), (PACKAGE, "6001", "delete")]


def test_e08_erp_row(rows: Engine) -> None:
    p = pipeline(rows)
    ctx = p.setup.context()
    with pytest.raises(t.PlatformError) as caught:
        p.execute(save([master_modify("115", {"PRICE": "3.80"}, entity=GOODS)], GOODS_PAGE, GOODS_SAVE), ctx)
    assert caught.value.code is t.ErrorCode.FIELD_NOT_WRITABLE
    p.execute(save([master_modify("116", {"PRICE": "48"}, entity=GOODS)], GOODS_PAGE, GOODS_SAVE), ctx)
    result = p.execute(save([{"entity": GOODS, "master": {"op": "add", "clientRowId": TMP_1,
                                                          "values": {"NAME": "复制的物料", "PRICE": "3.5"}}, "details": []}],
                            GOODS_PAGE, GOODS_SAVE), ctx)
    goods = {r["goodsid"]: r for r in fetch(rows, "SELECT * FROM T_WP_GOODS")}
    assert goods[115]["price"] == D("3.5") and goods[116]["price"] == 48
    assert goods[int(result.id_map[TMP_1])]["iserp"] == 0


def test_e28_builtin_default(rows: Engine) -> None:
    p = pipeline(rows)
    result = p.execute(save([{"entity": DOC, "master": {"op": "add", "clientRowId": TMP_1, "values": {"CREATE_BY": "李四"}},
                              "details": []}]), p.setup.context())
    [row] = fetch(rows, "SELECT CREATE_BY, USESTATUS FROM T_WP_DOC WHERE DOCID = :k", k=int(result.id_map[TMP_1]))
    assert row == {"create_by": "张三", "usestatus": "草稿"}


def test_row_permission_in_lock_statement(rows: Engine) -> None:
    setup = WpSetup()
    setup.permission.set_rows(PAGE, DOC, t.SqlCondition(sql="OWNER = :rp_username", binds={"rp_username": f"user{USERS[0]}"}))
    p = pipeline(rows, setup)
    p.execute(save([master_modify("1001", {"MEMO": "可以"})]), setup.context())
    with pytest.raises(t.PlatformError) as caught:
        p.execute(save([master_modify("1002", {"MEMO": "不行"})]), setup.context())
    assert caught.value.code is t.ErrorCode.PERMISSION_DENIED
    assert fetch(rows, "SELECT MEMO FROM T_WP_DOC WHERE DOCID = 1002")[0]["memo"] == "旧备注"


def test_table_writer_on_unregistered_table(rows: Engine) -> None:
    writer = OracleTableWriter(5, inspector())
    with OracleUnitOfWorkFactory(rows).begin() as uow:
        assert writer.lock_row(uow, "T_WP_GOODS", "GOODSID", "115")["ZX_PRICE"] == D("3.5")
        writer.update(uow, "T_WP_GOODS", "GOODSID", "115", {"ZX_PRICE": D("90.123456")})
        key = writer.insert(uow, "T_WP_GOODS", {"NAME": "新物料", "ISERP": D(0), "ZX_PRICE": D("1")})
        writer.lock_row(uow, "T_WP_GOODS", "GOODSID", "116")
        writer.delete(uow, "T_WP_GOODS", "GOODSID", "116")
        changes = writer.changes(uow)
        uow.commit()
    goods = {r["goodsid"]: r for r in fetch(rows, "SELECT * FROM T_WP_GOODS")}
    assert goods[115]["zx_price"] == D("90.1235") and int(key) in goods and 116 not in goods
    assert [(c.op, c.row_key) for c in changes] == [("modify", "115"), ("add", key), ("delete", "116")]
    assert changes[0].old == {"ZX_PRICE": D("3.5")} and changes[2].old["NAME"] == "聚维酮K30"


def test_same_values_unchanged_and_rolled_back(rows: Engine) -> None:
    p = pipeline(rows)
    result = p.execute(save([master_none("1001", [
        {"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {"PRICE": "3.5", "USAGE": "2"}}])]), p.setup.context())
    assert result.outcome == "unchanged"
    assert fetch(rows, "SELECT * FROM pf_command WHERE user_id = :u", u=USERS[0]) == []
