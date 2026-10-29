"""T-QE-2：`DocumentReader`（C08 第 9 节）。

真实实现 `OracleDocumentReader` 在 contracts 的 SQLite 替代事务上运行 contracts 的契约测试；d_cg 上读真实单据见 test_oracle.py。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from cost_platform.contracts.fakes import FakeUnitOfWorkFactory
from cost_platform.contracts.types import DetailLink, DocumentData, DocumentRef, EntityConfig
from cost_platform.queries.catalog import MappingEntityDirectory
from cost_platform.queries.documents import OracleDocumentReader
from tests.contracts.test_document_reader import DocumentReaderContract

from .support import MATERIAL, database, entities, field

# 契约测试的单据：主表 DOCID、GOODSNAME、QTY、AUDITED（是非，NUMBER(1)），明细 DTLID、DOCID、PRICE
CONTRACT_ENTITIES = {
    "COST_PINGGU": EntityConfig(table="T_CT_DOC", primary_key="DOCID", freezable=True,
                                fields=[field("DOCID", "单据号"), field("GOODSNAME", "产品", "text"), field("QTY", "数量"),
                                        field("AUDITED", "已审核", "boolean")],
                                details=[DetailLink(entity="COST_MATERIAL", parent_key="DOCID")]),
    "COST_MATERIAL": EntityConfig(table="T_CT_DTL", primary_key="DTLID", freezable=True,
                                  fields=[field("DTLID", "明细"), field("DOCID", "单据号"), field("PRICE", "单价")]),
}


class SqliteDocumentReaderHarness:
    def __init__(self) -> None:
        self._factory = FakeUnitOfWorkFactory()
        with self._factory.engine.begin() as conn:
            conn.execute(text("CREATE TABLE T_CT_DOC (DOCID NUMBER(19) PRIMARY KEY, GOODSNAME VARCHAR2(200), QTY NUMBER, AUDITED NUMBER(1))"))
            conn.execute(text("CREATE TABLE T_CT_DTL (DTLID NUMBER(19) PRIMARY KEY, DOCID NUMBER(19), PRICE NUMBER)"))
        self.reader = OracleDocumentReader(self._factory, MappingEntityDirectory(CONTRACT_ENTITIES))

    def put(self, document: DocumentData) -> None:
        values = document.master.values
        with self._factory.engine.begin() as conn:
            conn.execute(text("INSERT INTO T_CT_DOC VALUES (:a, :b, :c, :d)"),
                         {"a": values["DOCID"], "b": values["GOODSNAME"], "c": values["QTY"], "d": 1 if values["AUDITED"] else 0})
            for row in document.details.get("COST_MATERIAL", []):
                conn.execute(text("INSERT INTO T_CT_DTL VALUES (:a, :b, :c)"),
                             {"a": row.values["DTLID"], "b": row.values["DOCID"], "c": row.values["PRICE"]})


class TestOracleDocumentReaderOnSqlite(DocumentReaderContract):
    @pytest.fixture
    def harness(self) -> SqliteDocumentReaderHarness:
        return SqliteDocumentReaderHarness()


def test_details_are_read_through_the_read_view() -> None:
    """有 readView 的明细经视图读取（物料名称只在视图中），按主键排序；明细实体按主表实体 `details` 的顺序。"""
    reader = OracleDocumentReader(database(), MappingEntityDirectory(entities()))
    loaded = reader.load(DocumentRef("COST_PINGGU", "1002"))
    assert loaded is not None
    assert loaded.master.values["GOODSNAME"] == "片剂B" and loaded.master.values["TOTAL_COST"] == Decimal("20.25")
    assert [(r.row_key, r.values["GOODSNAME"]) for r in loaded.details[MATERIAL]] == [("5002", "硬脂酸镁"), ("5003", "胶囊壳")]
    many = reader.load_many([DocumentRef("COST_PINGGU", "1004"), DocumentRef("COST_PINGGU", "1001")])
    assert {ref.record_key: [r.row_key for r in doc.details[MATERIAL]] for ref, doc in many.items()} == {
        "1004": ["5006"], "1001": ["5001"]}
