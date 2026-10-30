"""`OracleDocumentStore` 和 `ChangeWriter` 生成的 SQL（WP-03、WP-06、WP-09）：只写有变化的列，按列分组批量执行，
新增行用序列和 RETURNING，删除主表行前先删明细。语句在 d_cg 上的执行见 `test_oracle_store.py`。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cost_platform.contracts import types as t
from cost_platform.pipeline.document_store import DetailSource, OracleDocumentStore
from cost_platform.pipeline.writer import ChangeWriter

from .recording import RecordingUnitOfWork
from .support import GOODS, GOODS_ENTITY, MASTER, MASTER_ENTITY, MATERIAL, MATERIAL_ENTITY, TMP_1, TMP_2, Setup

D = Decimal
REF = t.DocumentRef(MASTER, "1001")


def change(entity: str, op: str, key: str | None, values: dict[str, object], client: str | None = None,
           ref: t.DocumentRef = REF) -> t.RowChange:
    return t.RowChange(document=ref, entity=entity, op=op, row_key=key, client_row_id=client, values=values, old={})  # type: ignore[arg-type]


def test_lock_load_one_document_one_statement_with_wait() -> None:
    """只锁一张单据：加锁和读数据一条语句（普通保存的 SQL 条数不变，WP-10）。"""
    uow = RecordingUnitOfWork()
    uow.connection.results = [[(D(1001), "250mg乙酰唑胺片", None, D(100000), D("54.00"), "王五", "草稿", None)]]
    rows = OracleDocumentStore(5).lock_load(uow, MASTER, MASTER_ENTITY, ["1001"])  # type: ignore[arg-type]
    [statement] = uow.connection.statements
    assert statement.sql == ("SELECT DOCID, GOODSNAME, MEMO, APEX_PL, TOTAL_COST, CREATE_BY, USESTATUS, CREATE_TIME "
                             "FROM T_COST_PINGGU WHERE DOCID IN (:k0) ORDER BY DOCID FOR UPDATE WAIT 5")
    assert statement.params == {"k0": D(1001)}
    assert list(rows) == ["1001"] and rows["1001"].values["APEX_PL"] == D(100000)


def test_lock_load_several_documents_one_lock_per_row_in_key_order() -> None:
    """一次锁多行（用户 2026-10-30 规则 7）：按主键顺序每行一条 `SELECT … FOR UPDATE WAIT n`，不依赖一条 SQL 内部的加锁
    顺序；锁完再一条普通查询读出数据。"""
    uow = RecordingUnitOfWork()
    uow.connection.results = [[], [], [(D(1001), "250mg乙酰唑胺片", None, D(100000), D("54.00"), "王五", "草稿", None)]]
    rows = OracleDocumentStore(5).lock_load(uow, MASTER, MASTER_ENTITY, ["1002", "1001"])  # type: ignore[arg-type]
    assert uow.connection.sql == [
        "SELECT DOCID FROM T_COST_PINGGU WHERE DOCID = :k FOR UPDATE WAIT 5",
        "SELECT DOCID FROM T_COST_PINGGU WHERE DOCID = :k FOR UPDATE WAIT 5",
        "SELECT DOCID, GOODSNAME, MEMO, APEX_PL, TOTAL_COST, CREATE_BY, USESTATUS, CREATE_TIME "
        "FROM T_COST_PINGGU WHERE DOCID IN (:k0, :k1) ORDER BY DOCID"]
    assert [s.params for s in uow.connection.statements] == [{"k": D(1001)}, {"k": D(1002)}, {"k0": D(1001), "k1": D(1002)}]
    assert list(rows) == ["1001"]


def test_lock_load_reads_view_by_field_name() -> None:
    uow = RecordingUnitOfWork()
    OracleDocumentStore(5).lock_load(uow, GOODS, GOODS_ENTITY, ["115"])  # type: ignore[arg-type]
    assert uow.connection.sql == ["SELECT GOODSID, NAME, ISERP, PRICE, ZX_PRICE FROM T_COST_GOODS_PRICE_V "
                                  "WHERE GOODSID IN (:k0) ORDER BY GOODSID FOR UPDATE WAIT 5"]


def test_lock_load_row_permission_in_same_statement() -> None:
    """WP-03：行权限条件作为判断列在读数据的同一条 SQL 中查出（锁多行时为锁完后的那条普通查询）；有一行超出就拒绝。"""
    uow = RecordingUnitOfWork()
    uow.connection.results = [[], [], [(D(1001), "a", None, D(1), D(1), "王五", "草稿", None, 1),
                                       (D(1002), "b", None, D(1), D(1), "王五", "草稿", None, 0)]]
    condition = t.SqlCondition(sql="CREATE_BY = :rp_username", binds={"rp_username": "user112"})
    with pytest.raises(t.PlatformError) as caught:
        OracleDocumentStore(5).lock_load(uow, MASTER, MASTER_ENTITY, ["1001", "1002"], row_condition=condition)  # type: ignore[arg-type]
    assert caught.value.code is t.ErrorCode.PERMISSION_DENIED
    assert [(d.entity, d.row_key) for d in caught.value.details] == [(MASTER, "1002")]
    statement = uow.connection.statements[-1]
    assert ", CASE WHEN (CREATE_BY = :rp_username) THEN 1 ELSE 0 END AS WP_ALLOWED FROM T_COST_PINGGU" in statement.sql
    assert statement.params == {"k0": D(1001), "k1": D(1002), "rp_username": "user112"}


def test_lock_load_one_document_row_permission_in_lock_statement() -> None:
    """只锁一张单据时，行权限判断列就在加锁的那条语句里（条数不变）。"""
    uow = RecordingUnitOfWork()
    uow.connection.results = [[(D(1001), "a", None, D(1), D(1), "王五", "草稿", None, 1)]]
    condition = t.SqlCondition(sql="CREATE_BY = :rp_username", binds={"rp_username": "user112"})
    OracleDocumentStore(5).lock_load(uow, MASTER, MASTER_ENTITY, ["1001"], row_condition=condition)  # type: ignore[arg-type]
    [sql] = uow.connection.sql
    assert "AS WP_ALLOWED FROM T_COST_PINGGU WHERE DOCID IN (:k0) ORDER BY DOCID FOR UPDATE WAIT 5" in sql


def test_details_of_several_entities_in_one_statement() -> None:
    package = MATERIAL_ENTITY.model_copy(update={"read_view": "V_COST_PINGGU_PACKAGE"})
    uow = RecordingUnitOfWork()
    width = len(MATERIAL_ENTITY.fields)
    material_row = (D(5001), D(1001), D(115), "硬脂酸镁", D(2), D("3.50"), D("7.00"), None)
    package_row = (D(6001), D(1001), D(300), "铝箔", D(1), D("0.50"), D("0.50"), None)
    uow.connection.results = [[(0, *material_row, *([None] * width)), (1, *([None] * width), *package_row)]]
    found = OracleDocumentStore(5).load_details_many(  # type: ignore[arg-type]
        uow, [DetailSource(MATERIAL, MATERIAL_ENTITY, "DOCID"), DetailSource("COST_PACKAGE", package, "DOCID")], ["1001"])
    [sql] = uow.connection.sql
    assert sql.count("UNION ALL") == 1 and "FOR UPDATE" not in sql
    assert sql.startswith("SELECT 0 AS C0, DTLID AS C1, DOCID AS C2, GOODSID AS C3")
    assert "FROM V_COST_PINGGU_MATERIAL WHERE DOCID IN (:r0_0) UNION ALL SELECT 1, NULL" in sql
    assert sql.endswith(f"FROM V_COST_PINGGU_PACKAGE WHERE DOCID IN (:r1_0) ORDER BY 1, 2, {2 + width}")
    assert [r.row_key for r in found[MATERIAL]["1001"]] == ["5001"]
    assert [r.row_key for r in found["COST_PACKAGE"]["1001"]] == ["6001"]
    assert found["COST_PACKAGE"]["1001"][0].values["GOODSNAME"] == "铝箔"


def test_update_only_changed_columns_grouped() -> None:
    """E05：只写 PRICE 和计算带出的 COST_BATCH，USAGE 不出现在语句中；写同样列的行合成一条批量语句。"""
    uow = RecordingUnitOfWork()
    OracleDocumentStore(5).update(uow, MATERIAL_ENTITY, [  # type: ignore[arg-type]
        change(MATERIAL, "modify", "5001", {"PRICE": D("3.80"), "COST_BATCH": D("7.60")}),
        change(MATERIAL, "modify", "5002", {"COST_BATCH": D("47.50"), "PRICE": D("47.50")}),
        change(MATERIAL, "modify", "5101", {"MEMO": "测试"})])
    assert uow.connection.sql == ["UPDATE T_COST_PINGGU_DTL SET COST_BATCH = :v0, PRICE = :v1 WHERE DTLID = :pk",
                                  "UPDATE T_COST_PINGGU_DTL SET MEMO = :v0 WHERE DTLID = :pk"]
    assert uow.connection.statements[0].params == [{"v0": D("7.60"), "v1": D("3.80"), "pk": D(5001)},
                                                   {"v0": D("47.50"), "v1": D("47.50"), "pk": D(5002)}]


def test_insert_with_sequence_and_returning() -> None:
    uow = RecordingUnitOfWork()
    uow.connection.results = [[(D(7001),), (D(7002),)]]
    rows = [change(MATERIAL, "add", None, {"DOCID": D(1001), "GOODSID": D(115), "PRICE": D("1.20")}, TMP_1),
            change(MATERIAL, "add", None, {"DOCID": D(1001), "GOODSID": D(116), "PRICE": D("2.00")}, TMP_2)]
    OracleDocumentStore(5).insert(uow, MATERIAL_ENTITY, rows)  # type: ignore[arg-type]
    [statement] = uow.connection.statements
    assert statement.sql == ('INSERT INTO "T_COST_PINGGU_DTL" ("DTLID", "DOCID", "GOODSID", "PRICE") '
                             'VALUES (T_COST_PINGGU_DTL_SEQ.NEXTVAL, :DOCID, :GOODSID, :PRICE) '
                             'RETURNING "T_COST_PINGGU_DTL"."DTLID" INTO :ret_0')
    assert [r.row_key for r in rows] == ["7001", "7002"]


def test_insert_with_key_taken_at_approval_submission() -> None:
    """审批通过时写入的新增行使用提交审批时已取得的主键（AP-02）。"""
    uow = RecordingUnitOfWork()
    OracleDocumentStore(5).insert(uow, MATERIAL_ENTITY, [change(MATERIAL, "add", "7005", {"DOCID": D(1001)}, TMP_1)])  # type: ignore[arg-type]
    [statement] = uow.connection.statements
    assert statement.sql == 'INSERT INTO "T_COST_PINGGU_DTL" ("DTLID", "DOCID") VALUES (:DTLID, :DOCID)'
    assert statement.params == [{"DOCID": D(1001), "DTLID": D(7005)}]


def test_boolean_written_as_number() -> None:
    entity = MATERIAL_ENTITY.model_copy(update={"fields": [*MATERIAL_ENTITY.fields, t.EntityField(
        name="CUSTOMER_SPECIFIED", column="CUSTOMER_SPECIFIED", label="客户指定", type="boolean", source="own", role="input")]})
    uow = RecordingUnitOfWork()
    OracleDocumentStore(5).update(uow, entity, [change(MATERIAL, "modify", "5001", {"CUSTOMER_SPECIFIED": True})])  # type: ignore[arg-type]
    assert uow.connection.statements[0].params == [{"v0": 1, "pk": D(5001)}]


def test_writer_statement_counts() -> None:
    """改一条明细并重算汇总：明细 1 条、主表 1 条；删除主表行：每张明细表 1 条、主表 1 条，先删明细。"""
    setup = Setup()
    ctx = setup.context()
    uow = RecordingUnitOfWork()
    writer = ChangeWriter(OracleDocumentStore(5))
    state = t.CommandState(command=t.parse_wire(t.Command, {"requestKey": "00000000-0000-4000-8000-0000000000a1",
                                                            "page": "COST_PINGGU", "operation": "COST_PINGGU.save",
                                                            "documents": [], "params": {}}))
    state.changes.rows = [change(MATERIAL, "modify", "5001", {"PRICE": D("3.80"), "COST_BATCH": D("7.60")}),
                          change(MASTER, "modify", "1001", {"TOTAL_COST": D("54.60")})]
    writer.apply(uow, state, ctx)  # type: ignore[arg-type]
    assert uow.connection.sql == ["UPDATE T_COST_PINGGU_DTL SET COST_BATCH = :v0, PRICE = :v1 WHERE DTLID = :pk",
                                  "UPDATE T_COST_PINGGU SET TOTAL_COST = :v0 WHERE DOCID = :pk"]

    uow = RecordingUnitOfWork()
    gone = t.DocumentRef(MASTER, "1002")
    state.changes.rows = [change(MASTER, "delete", "1002", {}, ref=gone), change(MATERIAL, "delete", "5101", {}, ref=gone)]
    writer.apply(uow, state, ctx)  # type: ignore[arg-type]
    assert uow.connection.sql == ["DELETE FROM T_COST_PINGGU_DTL WHERE DOCID IN (:p0)",
                                  "DELETE FROM T_COST_PINGGU WHERE DOCID = :pk"]
