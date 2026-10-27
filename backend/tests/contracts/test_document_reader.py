"""`DocumentReader` 的契约测试（C08 第 9 节）。

真实实现（queries-export）的测试继承 `DocumentReaderContract`，提供 `harness` fixture，实现 `DocumentReaderHarness`。
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeDocumentReader
from cost_platform.contracts.ports import DocumentReader
from cost_platform.contracts.types import DocumentData, DocumentRef, Row


def _document(record_key: str, details: int) -> DocumentData:
    ref = DocumentRef(entity="COST_PINGGU", record_key=record_key)
    master = Row(entity="COST_PINGGU", row_key=record_key, client_row_id=None,
                 values={"DOCID": Decimal(record_key), "GOODSNAME": "胶囊", "QTY": Decimal("12.5"), "AUDITED": False})
    rows = [Row(entity="COST_MATERIAL", row_key=f"{record_key}{i}", client_row_id=None,
                values={"DTLID": Decimal(f"{record_key}{i}"), "DOCID": Decimal(record_key), "PRICE": Decimal("3.50")})
            for i in range(details, 0, -1)]
    return DocumentData(ref=ref, master=master, details={"COST_MATERIAL": rows})


DOC_A = _document("1001", 2)
DOC_B = _document("1002", 0)
MISSING = DocumentRef(entity="COST_PINGGU", record_key="1999")


def _normalized(document: DocumentData | None) -> DocumentData | None:
    """明细的顺序没有约定，按行主键排序后比较。"""
    if document is None:
        return None
    return replace(document, details={k: sorted(v, key=lambda r: r.row_key or "") for k, v in document.details.items()})


class DocumentReaderHarness(Protocol):
    reader: DocumentReader

    def put(self, document: DocumentData) -> None:
        """写入这张单据（主表行和明细行）。"""
        ...


class DocumentReaderContract:
    @pytest.fixture
    def harness(self) -> DocumentReaderHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    @pytest.fixture
    def arranged(self, harness: DocumentReaderHarness) -> DocumentReaderHarness:
        harness.put(DOC_A)
        harness.put(DOC_B)
        return harness

    def test_load(self, arranged: DocumentReaderHarness) -> None:
        assert _normalized(arranged.reader.load(DOC_A.ref)) == _normalized(DOC_A)
        assert _normalized(arranged.reader.load(DOC_B.ref)) == _normalized(DOC_B)

    def test_load_missing_is_none(self, arranged: DocumentReaderHarness) -> None:
        assert arranged.reader.load(MISSING) is None

    def test_numbers_are_decimal(self, arranged: DocumentReaderHarness) -> None:
        loaded = arranged.reader.load(DOC_A.ref)
        assert loaded is not None
        assert isinstance(loaded.master.values["QTY"], Decimal)

    def test_load_many(self, arranged: DocumentReaderHarness) -> None:
        found = arranged.reader.load_many([DOC_A.ref, DOC_B.ref])
        assert set(found) == {DOC_A.ref, DOC_B.ref}
        assert _normalized(found[DOC_A.ref]) == _normalized(DOC_A)
        assert _normalized(found[DOC_B.ref]) == _normalized(DOC_B)

    def test_load_many_omits_missing(self, arranged: DocumentReaderHarness) -> None:
        """不存在的单据不在结果中，与 load 返回 None 对应（C08 第 9 节）。"""
        found = arranged.reader.load_many([DOC_A.ref, MISSING])
        assert set(found) == {DOC_A.ref}
        assert arranged.reader.load_many([MISSING]) == {}


class FakeDocumentReaderHarness:
    def __init__(self) -> None:
        self.reader = FakeDocumentReader()

    def put(self, document: DocumentData) -> None:
        self.reader.put(document)


class TestFakeDocumentReader(DocumentReaderContract):
    @pytest.fixture
    def harness(self) -> FakeDocumentReaderHarness:
        return FakeDocumentReaderHarness()


def test_fake_returns_copies() -> None:
    """替代实现：调用方修改读到的单据，不影响存储的内容。"""
    reader = FakeDocumentReader()
    reader.put(DOC_A)
    loaded = reader.load(DOC_A.ref)
    assert loaded is not None
    loaded.master.values["QTY"] = Decimal("0")
    assert reader.load(DOC_A.ref) == DOC_A
