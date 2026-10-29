"""`SchemaInspector` 的契约测试（C08 第 2 节）。

真实实现（db-core）的测试继承 `SchemaInspectorContract`，提供 `harness` fixture，实现 `SchemaInspectorHarness`。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeSchemaInspector
from cost_platform.contracts.ports import SchemaInspector
from cost_platform.contracts.types import ColumnInfo

# NUMBER(18,2) 可空、VARCHAR2(50) 非空、DATE 可空：数值列给出精度和小数位，字符列给出长度，其余为 None。
COLUMNS = [
    ColumnInfo(name="PRICE", data_type="NUMBER", nullable=True, length=None, precision=18, scale=2),
    ColumnInfo(name="GOODSNAME", data_type="VARCHAR2", nullable=False, length=50, precision=None, scale=None),
    ColumnInfo(name="CREATE_DATE", data_type="DATE", nullable=True, length=None, precision=None, scale=None),
]


class SchemaInspectorHarness(Protocol):
    inspector: SchemaInspector

    def create_table(self, table: str, columns: Sequence[ColumnInfo], primary_key: str | None = None) -> None:
        """建一张有这些列的表；给出 primary_key 时以这一列为主键。"""
        ...

    def create_view(self, view: str, table: str) -> None:
        """在表 `table` 上建一个选出它全部列的视图。"""
        ...

    def missing_table(self) -> str:
        """一个不存在的表名。"""
        ...


class SchemaInspectorContract:
    @pytest.fixture
    def harness(self) -> SchemaInspectorHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_missing_table_is_none(self, harness: SchemaInspectorHarness) -> None:
        assert harness.inspector.columns(harness.missing_table()) is None
        assert harness.inspector.object_type(harness.missing_table()) is None

    def test_columns_keyed_by_name(self, harness: SchemaInspectorHarness) -> None:
        harness.create_table("CT_SCHEMA_PROBE", COLUMNS)
        assert harness.inspector.columns("CT_SCHEMA_PROBE") == {c.name: c for c in COLUMNS}

    def test_table_and_view_are_told_apart(self, harness: SchemaInspectorHarness) -> None:
        """审批的冻结表、修改表只能是表（C06 第 10 节）：表为 table，视图为 view，视图也能读出列。"""
        harness.create_table("CT_SCHEMA_PROBE", COLUMNS)
        harness.create_view("CT_SCHEMA_PROBE_V", "CT_SCHEMA_PROBE")
        assert harness.inspector.object_type("CT_SCHEMA_PROBE") == "table"
        assert harness.inspector.object_type("CT_SCHEMA_PROBE_V") == "view"
        assert set(harness.inspector.columns("CT_SCHEMA_PROBE_V") or {}) == {c.name for c in COLUMNS}

    def test_primary_key(self, harness: SchemaInspectorHarness) -> None:
        """展示数据的 `keyColumn` 省略时取表的主键（C06 7.5）；视图没有主键。"""
        harness.create_table("CT_SCHEMA_PROBE", COLUMNS, primary_key="GOODSNAME")
        harness.create_view("CT_SCHEMA_PROBE_V", "CT_SCHEMA_PROBE")
        assert harness.inspector.primary_key("CT_SCHEMA_PROBE") == "GOODSNAME"
        assert harness.inspector.primary_key("CT_SCHEMA_PROBE_V") is None


class FakeSchemaInspectorHarness:
    def __init__(self) -> None:
        self.inspector = FakeSchemaInspector()

    def create_table(self, table: str, columns: Sequence[ColumnInfo], primary_key: str | None = None) -> None:
        self.inspector.add_table(table, columns, primary_key)

    def create_view(self, view: str, table: str) -> None:
        self.inspector.add_view(view, list((self.inspector.columns(table) or {}).values()))

    def missing_table(self) -> str:
        return "CT_NO_SUCH_TABLE"


class TestFakeSchemaInspector(SchemaInspectorContract):
    @pytest.fixture
    def harness(self) -> FakeSchemaInspectorHarness:
        return FakeSchemaInspectorHarness()
