"""`EntityDirectory` 的契约测试（C08 第 4 节）：成本核算的主表、两个明细同在 T_COST_PINGGU_DTL，物料清单在 T_COST_GOODS。

真实实现（config）继承 `EntityDirectoryContract`，给出 `directory` 夹具：已发布这三张表上的实体（与下面 `ENTITIES` 相同）。
"""

from __future__ import annotations

from typing import Any

import pytest

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeEntityDirectory


def _field(name: str) -> dict[str, Any]:
    return {"name": name, "column": name, "label": name, "type": "number", "source": "own", "role": "input"}


def _entity(table: str, pk: str, details: list[tuple[str, str]] = (), read_view: str | None = None) -> t.EntityConfig:
    data: dict[str, Any] = {"table": table, "primaryKey": pk, "freezable": True, "fields": [_field(pk), _field("GOODSID")],
                            "details": [{"entity": e, "parentKey": k} for e, k in details]}
    if read_view:
        data["readView"] = read_view
    return t.parse_wire(t.EntityConfig, data)


ENTITIES = {
    "COST_PINGGU": _entity("T_COST_PINGGU", "DOCID", [("COST_MATERIAL", "DOCID"), ("COST_PACKAGE", "DOCID")]),
    "COST_MATERIAL": _entity("T_COST_PINGGU_DTL", "DTLID", read_view="V_COST_PINGGU_MATERIAL"),
    "COST_PACKAGE": _entity("T_COST_PINGGU_DTL", "DTLID", read_view="V_COST_PINGGU_PACKAGE"),
    "COST_GOODS_PRICE": _entity("T_COST_GOODS", "GOODSID", read_view="T_COST_GOODS_PRICE_V"),
}


class EntityDirectoryContract:
    @pytest.fixture
    def directory(self) -> Any:
        raise NotImplementedError

    def test_entity(self, directory: Any) -> None:
        assert directory.entity("COST_MATERIAL").table == "T_COST_PINGGU_DTL"

    def test_master_of(self, directory: Any) -> None:
        assert directory.master_of("COST_PACKAGE") == ("COST_PINGGU", "DOCID")
        assert directory.master_of("COST_PINGGU") is None

    def test_entities_on_table(self, directory: Any) -> None:
        """成本核算的两个明细在同一张表上；物料清单的实体是主表。"""
        assert directory.entities_on_table("T_COST_PINGGU_DTL") == [
            t.TableEntity(entity="COST_MATERIAL", master="COST_PINGGU", parent_key="DOCID"),
            t.TableEntity(entity="COST_PACKAGE", master="COST_PINGGU", parent_key="DOCID")]
        assert directory.entities_on_table("T_COST_GOODS") == [
            t.TableEntity(entity="COST_GOODS_PRICE", master="COST_GOODS_PRICE", parent_key=None)]
        assert directory.entities_on_table("T_COST_NOT_REGISTERED") == []


class TestFakeEntityDirectory(EntityDirectoryContract):
    @pytest.fixture
    def directory(self) -> FakeEntityDirectory:
        return FakeEntityDirectory(ENTITIES)
