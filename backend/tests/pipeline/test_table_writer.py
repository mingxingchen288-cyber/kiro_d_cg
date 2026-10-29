"""`TableWriter`（WP-19）：按主键加锁读出整行、只写指定且有变化的列、数值按列的小数位处理、改前改后记入审计差异。

场景取 C06 7.5 的物料清单改价审批：最终批准时把 ZX_PRICE 写到没注册的表 T_COST_GOODS。语句在 d_cg 上的执行见
`test_oracle_store.py`。"""

from __future__ import annotations

from decimal import Decimal

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeSchemaInspector
from cost_platform.pipeline.command_log import audit_rows
from cost_platform.pipeline.table_writer import OracleTableWriter

from .recording import RecordingUnitOfWork

D = Decimal


def inspector() -> FakeSchemaInspector:
    found = FakeSchemaInspector()
    found.add_table("T_COST_GOODS", [
        t.ColumnInfo(name="GOODSID", data_type="NUMBER", nullable=False, length=None, precision=None, scale=None),
        t.ColumnInfo(name="ZX_PRICE", data_type="NUMBER", nullable=True, length=None, precision=18, scale=4),
        t.ColumnInfo(name="MEMO", data_type="VARCHAR2", nullable=True, length=200, precision=None, scale=None),
    ], primary_key="GOODSID")
    return found


def test_lock_then_update_changed_columns_and_audit() -> None:
    uow = RecordingUnitOfWork()
    uow.connection.results = [[{"GOODSID": 25, "ZX_PRICE": D("75"), "MEMO": "原备注"}]]
    writer = OracleTableWriter(5, inspector())
    row = writer.lock_row(uow, "T_COST_GOODS", "GOODSID", "25")  # type: ignore[arg-type]
    assert row == {"GOODSID": D(25), "ZX_PRICE": D("75"), "MEMO": "原备注"}
    writer.update(uow, "T_COST_GOODS", "GOODSID", "25", {"ZX_PRICE": D("90.123456"), "MEMO": "原备注"})  # type: ignore[arg-type]
    assert uow.connection.sql == ["SELECT * FROM T_COST_GOODS WHERE GOODSID = :k FOR UPDATE WAIT 5",
                                  "UPDATE T_COST_GOODS SET ZX_PRICE = :v0 WHERE GOODSID = :k"]
    assert uow.connection.statements[1].params == {"v0": D("90.1235"), "k": "25"}  # NUMBER(18,4)
    [change] = writer.changes(uow)  # type: ignore[arg-type]
    assert audit_rows([change]) == [{"entity": "T_COST_GOODS", "rowKey": "25", "op": "modify",
                                     "fields": {"ZX_PRICE": {"old": "75", "new": "90.1235"}}}]


def test_update_with_same_values_writes_nothing() -> None:
    uow = RecordingUnitOfWork()
    uow.connection.results = [[{"GOODSID": 25, "ZX_PRICE": D("75.0000"), "MEMO": None}]]
    writer = OracleTableWriter(5, inspector())
    writer.lock_row(uow, "T_COST_GOODS", "GOODSID", "25")  # type: ignore[arg-type]
    writer.update(uow, "T_COST_GOODS", "GOODSID", "25", {"ZX_PRICE": D("75")})  # type: ignore[arg-type]
    assert len(uow.connection.statements) == 1 and writer.changes(uow) == []  # type: ignore[arg-type]


def test_insert_takes_key_from_sequence() -> None:
    uow = RecordingUnitOfWork()
    uow.connection.results = [[(D(8801),)]]
    writer = OracleTableWriter(5, inspector())
    key = writer.insert(uow, "T_COST_GOODS", {"ZX_PRICE": D("80"), "MEMO": "新增"})  # type: ignore[arg-type]
    assert key == "8801"
    assert uow.connection.sql == ['INSERT INTO "T_COST_GOODS" ("GOODSID", "ZX_PRICE", "MEMO") '
                                  'VALUES (T_COST_GOODS_SEQ.NEXTVAL, :ZX_PRICE, :MEMO) RETURNING "T_COST_GOODS"."GOODSID" INTO :ret_0']
    [change] = writer.changes(uow)  # type: ignore[arg-type]
    assert (change.op, change.row_key, change.values) == ("add", "8801", {"ZX_PRICE": D("80"), "MEMO": "新增"})


def test_delete_records_row_before_delete() -> None:
    uow = RecordingUnitOfWork()
    uow.connection.results = [[{"GOODSID": 25, "ZX_PRICE": D("75"), "MEMO": None}]]
    writer = OracleTableWriter(5, inspector())
    writer.lock_row(uow, "T_COST_GOODS", "GOODSID", "25")  # type: ignore[arg-type]
    writer.delete(uow, "T_COST_GOODS", "GOODSID", "25")  # type: ignore[arg-type]
    assert uow.connection.sql[1] == "DELETE FROM T_COST_GOODS WHERE GOODSID = :k"
    [change] = writer.changes(uow)  # type: ignore[arg-type]
    assert change.op == "delete" and change.old == {"GOODSID": D(25), "ZX_PRICE": D("75"), "MEMO": None}


def test_missing_row_is_none() -> None:
    uow = RecordingUnitOfWork()
    uow.connection.results = [[]]
    assert OracleTableWriter(5, inspector()).lock_row(uow, "T_COST_GOODS", "GOODSID", "404") is None  # type: ignore[arg-type]


def test_changes_are_per_transaction() -> None:
    writer = OracleTableWriter(5, inspector())
    first, second = RecordingUnitOfWork(), RecordingUnitOfWork()
    first.connection.results = [[(D(1),)]]
    writer.insert(first, "T_COST_GOODS", {"MEMO": "a"})  # type: ignore[arg-type]
    assert len(writer.changes(first)) == 1 and writer.changes(second) == []  # type: ignore[arg-type]
