"""`OracleDocumentStore` 和 `ChangeWriter` 生成的 SQL（WP-03、WP-06、WP-09）：只写有变化的列，按列分组批量执行，
新增行用序列和 RETURNING，删除主表行前先删明细。语句在 d_cg 上的执行见 `test_oracle_store.py`。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cost_platform.contracts import types as t
from cost_platform.pipeline.document_store import DetailSource, OracleDocumentStore
from cost_platform.contracts.fakes import FakeSchemaInspector
from cost_platform.pipeline.locks import LockBook, PipelineLocks, ReadViews
from cost_platform.pipeline.writer import ChangeWriter

from .recording import RecordingUnitOfWork
from .support import (
    GOODS,
    GOODS_ENTITY,
    MASTER,
    MASTER_ENTITY,
    MATERIAL,
    MATERIAL_ENTITY,
    TMP_1,
    TMP_2,
    Setup,
    scales_inspector,
)

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


def goods_views(*sources: str) -> ReadViews:
    """物料清单的读取视图 T_COST_GOODS_PRICE_V 读取的表（d_cg 中它只读 T_COST_GOODS）。"""
    inspector = FakeSchemaInspector()
    inspector.add_view("T_COST_GOODS_PRICE_V", [], sources=sources)
    return ReadViews(inspector)


def test_lock_load_reads_view_by_field_name() -> None:
    """读取视图只读本表（物料清单的 T_COST_GOODS_PRICE_V 只读 T_COST_GOODS）：只锁一行时一条语句经视图按字段名加锁并读出。"""
    uow = RecordingUnitOfWork()
    OracleDocumentStore(5, goods_views("T_COST_GOODS")).lock_load(uow, GOODS, GOODS_ENTITY, ["115"])  # type: ignore[arg-type]
    assert uow.connection.sql == ["SELECT GOODSID, NAME, ISERP, PRICE, ZX_PRICE FROM T_COST_GOODS_PRICE_V "
                                  "WHERE GOODSID IN (:k0) ORDER BY GOODSID FOR UPDATE WAIT 5"]


@pytest.mark.parametrize("sources", [("T_COST_CUSTOMER", "T_COST_GOODS"), ("CMX.ERP_FORMONEY_V", "T_COST_GOODS"), None])
def test_lock_load_view_joining_other_tables_locks_table_then_reads(sources: tuple[str, ...] | None) -> None:
    """读取视图关联了别的表或经数据库链接读的视图（产品信息维护的 T_COST_GOODS_V 关联客户、分销商表，外币管理的
    T_COST_FORMONEY_V 关联 cmx 经 ERP 链接读的视图），或不知道视图读取哪些表（`views` 为 None）时：只锁表的这一行，
    再普通读视图，FOR UPDATE 不落到关联的行和链接上（WP-03）。"""
    uow = RecordingUnitOfWork()
    views = None if sources is None else goods_views(*sources)
    OracleDocumentStore(5, views).lock_load(uow, GOODS, GOODS_ENTITY, ["115"])  # type: ignore[arg-type]
    assert uow.connection.sql == ["SELECT GOODSID FROM T_COST_GOODS WHERE GOODSID = :k FOR UPDATE WAIT 5",
                                  "SELECT GOODSID, NAME, ISERP, PRICE, ZX_PRICE FROM T_COST_GOODS_PRICE_V "
                                  "WHERE GOODSID IN (:k0) ORDER BY GOODSID"]


def test_deferred_lock_reads_the_own_document_in_the_lock_statement() -> None:
    """往前冻结的页面推迟加锁（用户 2026-10-30 规则 3、4）：物料 115 是本命令的单据，加锁前已普通读到；成本单 1002 是要冻结的。
    按统一顺序先锁 1002（只锁），再锁 115 并读出数据（与普通保存的加锁读取同一条：物料清单的读取视图只读本表），用它核对，
    不另外重读。"""
    ctx = Setup().context()
    goods_row = (D(115), "硬脂酸镁", D(1), D("3.50"), D("3.50"))
    uow = RecordingUnitOfWork()
    uow.connection.results = [[goods_row], [], [goods_row]]
    locks = PipelineLocks(LockBook(), OracleDocumentStore(5, goods_views("T_COST_GOODS")), scales_inspector())
    goods, doc = t.DocumentRef(GOODS, "115"), t.DocumentRef(MASTER, "1002")
    expected = locks.read(uow, ctx, [goods])  # type: ignore[arg-type]
    locks.lock(uow, ctx, [locks.document(ctx, goods), locks.document(ctx, doc)], expected)  # type: ignore[arg-type]
    assert uow.connection.sql == [
        "SELECT GOODSID, NAME, ISERP, PRICE, ZX_PRICE FROM T_COST_GOODS_PRICE_V WHERE GOODSID IN (:k0) ORDER BY GOODSID",
        "SELECT DOCID FROM T_COST_PINGGU WHERE DOCID = :k FOR UPDATE WAIT 5",
        "SELECT GOODSID, NAME, ISERP, PRICE, ZX_PRICE FROM T_COST_GOODS_PRICE_V "
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


def test_lock_details_one_statement_per_detail_table() -> None:
    """主从单据连明细一起锁（用户 2026-10-31，`locks.py` 规则 5）：物料、包材两个明细实体都在 T_COST_PINGGU_DTL、都按 DOCID
    关联，成本单 1002、1001 的明细一条语句锁住，按物理表的主键列和关联列，不读数据。"""
    package = MATERIAL_ENTITY.model_copy(update={"read_view": "V_COST_PINGGU_PACKAGE"})
    uow = RecordingUnitOfWork()
    OracleDocumentStore(5).lock_details(  # type: ignore[arg-type]
        uow, [DetailSource(MATERIAL, MATERIAL_ENTITY, "DOCID"), DetailSource("COST_PACKAGE", package, "DOCID")], ["1002", "1001"])
    [statement] = uow.connection.statements
    assert statement.sql == ("SELECT DTLID FROM T_COST_PINGGU_DTL WHERE DOCID IN (:p0, :p1) "
                             "ORDER BY DTLID FOR UPDATE WAIT 5")
    assert statement.params == {"p0": D(1001), "p1": D(1002)}


def test_lock_document_locks_details_before_reading_them() -> None:
    """推迟加锁的成本单锁住后核对（`lock_document`）：锁主表行并读出 → 锁明细 → 普通读明细。"""
    ctx = Setup().context()
    uow = RecordingUnitOfWork()
    uow.connection.results = [[(D(1001), "250mg乙酰唑胺片", None, D(100000), D("54.00"), "王五", "草稿", None)], [], []]
    found = OracleDocumentStore(5).lock_document(uow, ctx, REF, [MATERIAL])  # type: ignore[arg-type]
    assert found is not None and found.details == {MATERIAL: []}
    sql = uow.connection.sql
    assert len(sql) == 3 and sql[0].endswith("FROM T_COST_PINGGU WHERE DOCID IN (:k0) ORDER BY DOCID FOR UPDATE WAIT 5")
    assert sql[1] == "SELECT DTLID FROM T_COST_PINGGU_DTL WHERE DOCID IN (:p0) ORDER BY DTLID FOR UPDATE WAIT 5"
    assert "UNION ALL" not in sql[2] and "FOR UPDATE" not in sql[2] and "FROM V_COST_PINGGU_MATERIAL" in sql[2]


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
