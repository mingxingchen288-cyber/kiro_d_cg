"""T-QE-2：`RelatedQuery`（C08 第 9 节、QE-08）。

真实实现 `OracleRelatedQuery` 在 contracts 的 SQLite 替代事务上运行 contracts 的契约测试（`RelatedQueryContract`），
关联 SQL 和关联键查找都真实执行。d_cg 上的真实验证见 test_oracle.py。
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import ExitStack
from decimal import Decimal

import pytest
from sqlalchemy import text

from cost_platform.contracts.fakes import FakeEntityDirectory, FakeUnitOfWorkFactory
from cost_platform.contracts.types import (
    DetailLink,
    DocumentData,
    DocumentRef,
    EntityConfig,
    ErrorCode,
    PlatformError,
    RelationKeyFinder,
    Row,
    SqlFinder,
    TargetObject,
)
from cost_platform.queries.related import OracleRelatedQuery
from tests.contracts.test_related_query import Case, RelatedQueryContract

from .support import field

ENTITIES = {
    "COST_PINGGU": EntityConfig(table="T_COST_PINGGU", primary_key="DOCID", freezable=True,
                                fields=[field("DOCID", "单据号"), field("GOODSID", "产品"), field("GOODSNAME", "产品名称", "text")],
                                details=[DetailLink(entity="COST_MATERIAL", parent_key="DOCID")]),
    "COST_MATERIAL": EntityConfig(table="T_COST_PINGGU_DTL", primary_key="DTLID", freezable=True,
                                  fields=[field("DTLID", "明细"), field("DOCID", "单据号"), field("GOODSID", "物料"),
                                          field("PRICE", "单价")]),
    "COST_GOODS_PRICE": EntityConfig(table="T_COST_GOODS", primary_key="GOODSID", freezable=True,
                                     fields=[field("GOODSID", "物料"), field("GOODSNAME", "名称", "text")]),
}

# 成本单 2001（产品 115）、2002、2003；2001 有两行物料 115，2002 有一行 115，2003 只有 116。
# T_QE_LOST、T_QE_HIT 是给关联 SQL 准备的结果行（按 SEQ 排序），用来造出"所属单据已删除""明细已删除""同一行查出两次"等情况。
_DDL = [
    "CREATE TABLE T_COST_PINGGU (DOCID NUMBER(19) PRIMARY KEY, GOODSID NUMBER(19), GOODSNAME VARCHAR2(200))",
    "CREATE TABLE T_COST_PINGGU_DTL (DTLID NUMBER(19) PRIMARY KEY, DOCID NUMBER(19), GOODSID NUMBER(19), PRICE NUMBER)",
    "CREATE TABLE T_COST_GOODS (GOODSID NUMBER(19) PRIMARY KEY, GOODSNAME VARCHAR2(200))",
    "CREATE TABLE T_QE_LOST (SEQ NUMBER(5), GOODSID NUMBER(19), DOC_ID NUMBER(19), DTL_ID NUMBER(19), PRODUCT_NAME VARCHAR2(200))",
    "CREATE TABLE T_QE_HIT (SEQ NUMBER(5), DOCID NUMBER(19), GOODSID NUMBER(19), DTLID NUMBER(19))",
]
_ROWS = {
    "T_COST_PINGGU": [(2001, 115, "甲"), (2002, 300, "乙"), (2003, 301, "丙")],
    "T_COST_PINGGU_DTL": [(6001, 2001, 115, 80), (6003, 2001, 115, 81), (6004, 2002, 115, 82), (6005, 2003, 116, 12)],
    "T_COST_GOODS": [(115, "硬脂酸镁"), (116, "胶囊壳")],
    "T_QE_LOST": [(1, 115, 2001, 5001, "甲"), (2, 115, 2001, 5001, "甲"), (3, 115, 2001, 5002, "甲"), (4, 115, 2004, 5009, None),
                  (5, 115, None, 5007, None), (6, 115, 2003, None, "丁"), (7, 115, 2005, None, "丁")],
    "T_QE_HIT": [(1, 2001, 115, 7001), (2, 2002, 115, 7002), (3, 2008, 115, 7008), (4, 2008, 115, 7008),
                 (5, 2002, 116, 7003), (6, 2003, 116, 7004), (7, 2003, 116, 7005), (8, 2009, 116, 7009)],
}

RELATION = RelationKeyFinder(kind="relationKey", entity="COST_GOODS_PRICE", target_key="GOODSID",
                             source_key="COST_MATERIAL.GOODSID", rows="all")
RELATION_DETAIL = RelationKeyFinder(kind="relationKey", entity="COST_MATERIAL", target_key="GOODSID",
                                    source_key="COST_GOODS_PRICE.GOODSID", rows="all")
SQL = SqlFinder(kind="sql", entity="COST_PINGGU",
                sql="SELECT M.DOCID AS DOC_ID, M.GOODSNAME AS PRODUCT_NAME FROM T_COST_PINGGU M WHERE EXISTS "
                    "(SELECT 1 FROM T_COST_PINGGU_DTL D WHERE D.DOCID = M.DOCID AND D.GOODSID = :goodsId) ORDER BY M.DOCID",
                binds={"goodsId": "COST_GOODS_PRICE.GOODSID"}, record_key_column="DOC_ID", label_column="PRODUCT_NAME",
                display_columns=["DOC_ID", "PRODUCT_NAME"])
LOST = SqlFinder(kind="sql", entity="COST_MATERIAL",
                 sql="SELECT DOC_ID, DTL_ID, PRODUCT_NAME FROM T_QE_LOST WHERE GOODSID = :goodsId ORDER BY SEQ",
                 binds={"goodsId": "COST_GOODS_PRICE.GOODSID"}, record_key_column="DOC_ID", row_key_columns=["DTL_ID"],
                 label_column="PRODUCT_NAME", display_columns=["DTL_ID"])
# 含某个物料、产品不同的成本单：物料编号取原辅料明细，产品取主表（主表和原辅料都有 GOODSID，值不同）
SQL_DETAIL = SqlFinder(kind="sql", entity="COST_PINGGU",
                       sql="SELECT D.DOCID AS DTL_DOC, M.DOCID AS DOC_ID, D.GOODSID AS HIT, D.DTLID AS DTL_ID FROM T_QE_HIT D "
                           "LEFT JOIN T_COST_PINGGU M ON M.DOCID = D.DOCID "
                           "WHERE D.GOODSID = :goodsId AND (M.DOCID IS NULL OR M.GOODSID <> :productId) ORDER BY D.SEQ",
                       binds={"goodsId": "COST_MATERIAL.GOODSID", "productId": "COST_PINGGU.GOODSID"},
                       record_key_column="DOC_ID", label_column="DTL_DOC", display_columns=["HIT", "DTL_ID"])


def _row(entity: str, key: str, **values: object) -> Row:
    return Row(entity=entity, row_key=key, client_row_id=None, values={k: Decimal(str(v)) for k, v in values.items()})


GOODS_115 = DocumentData(ref=DocumentRef("COST_GOODS_PRICE", "115"), master=_row("COST_GOODS_PRICE", "115", GOODSID=115), details={})
COST_DOC = DocumentData(
    ref=DocumentRef("COST_PINGGU", "1001"), master=_row("COST_PINGGU", "1001", DOCID=1001, GOODSID=900),
    details={"COST_MATERIAL": [_row("COST_MATERIAL", "5001", DOCID=1001, GOODSID=115, PRICE=80),
                               _row("COST_MATERIAL", "5002", DOCID=1001, GOODSID=116, PRICE=12)]})


def _target(entity: str, record_key: str | None, row_keys: tuple[str, ...], missing: bool = False, **display: object) -> TargetObject:
    shown = {k: v if v is None or isinstance(v, str) else Decimal(str(v)) for k, v in display.items()}
    return TargetObject(entity=entity, record_key=record_key, row_keys=row_keys, display=shown, missing=missing)


def database() -> FakeUnitOfWorkFactory:
    factory = FakeUnitOfWorkFactory()
    with factory.engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
        for table, rows in _ROWS.items():
            for row in rows:
                marks = ", ".join(f":v{i}" for i in range(len(row)))
                conn.execute(text(f"INSERT INTO {table} VALUES ({marks})"), {f"v{i}": v for i, v in enumerate(row)})
    return factory


class SqliteRelatedQueryHarness:
    def __init__(self) -> None:
        self._stack = ExitStack()
        self.uow = self._stack.enter_context(database().begin())
        self.query = OracleRelatedQuery(FakeEntityDirectory(ENTITIES))

    def close(self) -> None:
        self._stack.close()

    def relation_key_case(self) -> Case:
        return RELATION, copy.deepcopy(COST_DOC), [_target("COST_GOODS_PRICE", "115", (), GOODSID=115),
                                                     _target("COST_GOODS_PRICE", "116", (), GOODSID=116)]

    def sql_case(self) -> Case:
        return SQL, copy.deepcopy(GOODS_115), [_target("COST_PINGGU", "2001", (), DOC_ID=2001, PRODUCT_NAME="甲"),
                                                _target("COST_PINGGU", "2002", (), DOC_ID=2002, PRODUCT_NAME="乙")]

    def relation_key_detail_case(self) -> Case:
        return RELATION_DETAIL, copy.deepcopy(GOODS_115), [_target("COST_MATERIAL", "2001", ("6001",), GOODSID=115),
                                                            _target("COST_MATERIAL", "2001", ("6003",), GOODSID=115),
                                                            _target("COST_MATERIAL", "2002", ("6004",), GOODSID=115)]

    def sql_detail_bind_case(self) -> Case:
        return SQL_DETAIL, copy.deepcopy(COST_DOC), [
            _target("COST_PINGGU", "2001", (), DTL_DOC=2001, HIT=115, DTL_ID=7001),
            _target("COST_PINGGU", "2002", (), DTL_DOC=2002, HIT=115, DTL_ID=7002),
            _target("COST_PINGGU", None, (), True, DTL_DOC=2008, HIT=115, DTL_ID=7008),
            _target("COST_PINGGU", "2003", (), DTL_DOC=2003, HIT=116, DTL_ID=7004),
            _target("COST_PINGGU", None, (), True, DTL_DOC=2009, HIT=116, DTL_ID=7009)]

    def missing_record_key_case(self) -> tuple[SqlFinder, DocumentData]:
        return SQL.model_copy(update={"sql": SQL.sql.replace("M.DOCID AS DOC_ID, ", "")}), copy.deepcopy(GOODS_115)

    def missing_row_key_column_case(self) -> tuple[SqlFinder, DocumentData]:
        return SQL.model_copy(update={"row_key_columns": ["DTL_ID"]}), copy.deepcopy(GOODS_115)

    def lost_record_case(self) -> Case:
        return LOST, copy.deepcopy(GOODS_115), [
            _target("COST_MATERIAL", "2001", ("5001",), PRODUCT_NAME="甲", DTL_ID=5001),
            _target("COST_MATERIAL", "2001", ("5002",), PRODUCT_NAME="甲", DTL_ID=5002),
            _target("COST_MATERIAL", "2004", ("5009",), PRODUCT_NAME=None, DTL_ID=5009),
            _target("COST_MATERIAL", None, (), True, PRODUCT_NAME=None, DTL_ID=5007),
            _target("COST_MATERIAL", "2003", (), True, PRODUCT_NAME="丁", DTL_ID=None),
            _target("COST_MATERIAL", "2005", (), True, PRODUCT_NAME="丁", DTL_ID=None)]


class TestOracleRelatedQueryOnSqlite(RelatedQueryContract):
    @pytest.fixture
    def harness(self) -> Iterator[SqliteRelatedQueryHarness]:
        harness = SqliteRelatedQueryHarness()
        yield harness
        harness.close()


# ---------------------------------------------------------------- 任务卡 T-QE-2 点名的场景

@pytest.fixture
def harness() -> Iterator[SqliteRelatedQueryHarness]:
    h = SqliteRelatedQueryHarness()
    yield h
    h.close()


def test_two_material_rows_run_twice_and_each_document_once(harness: SqliteRelatedQueryHarness) -> None:
    """关联 SQL 绑定原辅料的物料编号、传入单据有物料 115、116 两行时，按两行各执行一次，含两种物料的成本单只返回一次。"""
    finder = SqlFinder(kind="sql", entity="COST_PINGGU",
                       sql="SELECT M.DOCID AS DOC_ID FROM T_COST_PINGGU M WHERE EXISTS (SELECT 1 FROM T_COST_PINGGU_DTL D "
                           "WHERE D.DOCID = M.DOCID AND D.GOODSID = :goodsId) ORDER BY M.DOCID",
                       binds={"goodsId": "COST_MATERIAL.GOODSID"}, record_key_column="DOC_ID")
    harness.uow.connection.execute(text("INSERT INTO T_COST_PINGGU_DTL VALUES (6006, 2002, 116, 13)"))  # 2002 同时含 115 和 116
    found = harness.query.find(harness.uow, finder, copy.deepcopy(COST_DOC))
    assert [t.record_key for t in found] == ["2001", "2002", "2003"]


def test_three_rows_one_without_record_key(harness: SqliteRelatedQueryHarness) -> None:
    """关联 SQL 查出 3 行、其中一行的 recordKeyColumn 为空时，返回 3 个对象，这一个 missing 为 True、record_key 为空。"""
    finder = SqlFinder(kind="sql", entity="COST_MATERIAL",
                       sql="SELECT DOC_ID, DTL_ID FROM T_QE_LOST WHERE GOODSID = :goodsId AND SEQ IN (1, 3, 5) ORDER BY SEQ",
                       binds={"goodsId": "COST_GOODS_PRICE.GOODSID"}, record_key_column="DOC_ID", row_key_columns=["DTL_ID"])
    found = harness.query.find(harness.uow, finder, copy.deepcopy(GOODS_115))
    assert [(t.record_key, t.row_keys, t.missing) for t in found] == [("2001", ("5001",), False), ("2001", ("5002",), False),
                                                                      (None, (), True)]


def test_missing_key_column_is_internal_error(harness: SqliteRelatedQueryHarness) -> None:
    finder, source = harness.missing_row_key_column_case()
    with pytest.raises(PlatformError) as caught:
        harness.query.find(harness.uow, finder, source)
    assert caught.value.code is ErrorCode.INTERNAL_ERROR
