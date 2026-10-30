"""queries-export 的真实验证（d_cg，标 oracle，合并后统一运行）。

读 d_cg 已复制的业务表 T_COST_PINGGU、T_COST_PINGGU_DTL、V_COST_PINGGU_MATERIAL、V_COST_PINGGU_PACKAGE、T_COST_GOODS，
实体配置取 backend/seed/config 中的真实配置；结果与直接写的 SQL（旧系统的写法）比较。只有个人配置一项写平台表
PF_PERSONAL_CONFIG（需先执行平台表升级），测试结束删除自己写的行。
"""

from __future__ import annotations

import functools
import json
import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text

from cost_platform.contracts.decimal_text import format_decimal
from cost_platform.contracts.fakes import FakeConfigSnapshot, FakeEntityDirectory, FakePermissionChecker
from cost_platform.contracts.types import (
    DocumentData,
    DocumentRef,
    EntityConfig,
    ExportConfig,
    ExportRequest,
    GridOptions,
    ListRequest,
    LookupConfig,
    LookupSearchRequest,
    PackRef,
    PageView,
    PersonalConfig,
    RoleConfig,
    RolePage,
    Row,
    SqlFinder,
    ViewDetail,
    ViewMaster,
    dump_wire,
    parse_wire,
)
from cost_platform.db_core.engine import OracleUnitOfWorkFactory, create_oracle_engine
from cost_platform.queries.catalog import ItemsCatalog
from cost_platform.queries.documents import OracleDocumentReader
from cost_platform.queries.exports import Exports
from cost_platform.queries.lists import PageQueries
from cost_platform.queries.lookups import LookupQueries
from cost_platform.queries.personal import PersonalConfigStore
from cost_platform.queries.related import OracleRelatedQuery

from . import xlsx_reader
from .support import context, view_fields

pytestmark = pytest.mark.oracle

ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / "backend" / "seed" / "config"
PAGE = "COST_PINGGU"
_GRID = GridOptions(side_bar=True, cell_selection=True, group_by=[])


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return {**values, **os.environ}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    env = _env()
    engine = create_oracle_engine(env["PLATFORM_DB_USER"], env["PLATFORM_DB_PASSWORD"], env["PLATFORM_DB_DSN"])
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def uow(engine: Engine) -> OracleUnitOfWorkFactory:
    return OracleUnitOfWorkFactory(engine)


def _entity(code: str) -> EntityConfig:
    return parse_wire(EntityConfig, json.loads((SEED / f"entity.{code}.json").read_text(encoding="utf-8"))["content"])


@functools.cache
def entities() -> dict[str, EntityConfig]:
    """seed 配置中的成本核算实体；运行测试时才读取。"""
    return {code: _entity(code) for code in ("COST_PINGGU", "COST_MATERIAL", "COST_PACKAGE")}


def _view() -> PageView:
    """成本核算页（seed 配置），全部字段可见。"""
    master = entities()["COST_PINGGU"]
    return PageView(
        page_code=PAGE, title="成本核算", version=1, layout="masterDetail", detail_mode="tabs", audit=True,
        save_operation="COST_PINGGU.save", rules_pack=PackRef(pack_id=PAGE, version=1),
        master=ViewMaster(entity="COST_PINGGU", primary_key="DOCID", fields=view_fields(master, ()), buttons=[], grid=_GRID,
                          form_layout=[]),
        details=[ViewDetail(entity=d.entity, title=d.entity, primary_key="DTLID", parent_key=d.parent_key,
                            fields=view_fields(entities()[d.entity], ()), buttons=[], grid=_GRID, form_layout=[])
                 for d in master.details],
        system_buttons=["save"])


def ctx() -> Any:
    role = RoleConfig(name="系统管理员", admin=True, pages={PAGE: RolePage(buttons=["*"])})
    return context(FakeConfigSnapshot(version=1, role_code="ADMIN", role=role, page_views={PAGE: _view()}, entities=entities()),
                   user_id="1")


def scalar(engine: Engine, sql: str, **binds: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), binds).scalar()


def column(engine: Engine, sql: str, **binds: Any) -> list[str]:
    with engine.connect() as conn:
        return [str(v) for v in conn.execute(text(sql), binds).scalars()]


def request(**body: Any) -> ListRequest:
    return parse_wire(ListRequest, {"startRow": 0, "endRow": 50, **body})


# ---------------------------------------------------------------- T-QE-1

def test_paging_total_and_sum(engine: Engine, uow: OracleUnitOfWorkFactory) -> None:
    """在 d_cg 上分页和汇总正确：两页拼起来与 ORDER BY DOCID 的前 100 行相同，总数和汇总与直接查询相同。"""
    catalog = ItemsCatalog(sums={(PAGE, "master"): ["TOTAL_COST", "COST_PERBOX"]})
    queries = PageQueries(uow, FakePermissionChecker(), catalog=lambda c: catalog)
    first = queries.list(ctx(), PAGE, request(startRow=0, endRow=50))
    second = queries.list(ctx(), PAGE, request(startRow=50, endRow=100))
    expected = column(engine, "SELECT DOCID FROM T_COST_PINGGU ORDER BY DOCID FETCH FIRST 100 ROWS ONLY")
    assert [r.row_key for r in first.rows + second.rows] == expected
    assert first.total == scalar(engine, "SELECT COUNT(*) FROM T_COST_PINGGU")
    assert Decimal(str(first.aggregates["TOTAL_COST"])) == scalar(engine, "SELECT SUM(TOTAL_COST) FROM T_COST_PINGGU")
    assert Decimal(str(first.aggregates["COST_PERBOX"])) == scalar(engine, "SELECT SUM(COST_PERBOX) FROM T_COST_PINGGU")


def test_equal_sort_values_page_stably(engine: Engine, uow: OracleUnitOfWorkFactory) -> None:
    queries = PageQueries(uow, FakePermissionChecker())
    sort = [{"colId": "GOODSNAME", "sort": "asc"}]
    pages = [queries.list(ctx(), PAGE, request(startRow=s, endRow=s + 30, sortModel=sort)).rows for s in (0, 30, 60)]
    expected = column(engine, "SELECT DOCID FROM T_COST_PINGGU ORDER BY GOODSNAME ASC, DOCID ASC FETCH FIRST 90 ROWS ONLY")
    assert [r.row_key for page in pages for r in page] == expected


def test_record_2550_details_through_views(engine: Engine, uow: OracleUnitOfWorkFactory) -> None:
    """单据加载：明细经视图 V_COST_PINGGU_MATERIAL、V_COST_PINGGU_PACKAGE 读取，按主键排序。"""
    record = PageQueries(uow, FakePermissionChecker()).record(ctx(), PAGE, "2550")
    assert record.master.row_key == "2550"
    assert record.master.values["GOODSNAME"] == scalar(engine, "SELECT GOODSNAME FROM T_COST_PINGGU WHERE DOCID = 2550")
    for entity, view in (("COST_MATERIAL", "V_COST_PINGGU_MATERIAL"), ("COST_PACKAGE", "V_COST_PINGGU_PACKAGE")):
        assert [r.row_key for r in record.details[entity]] == column(engine, f"SELECT DTLID FROM {view} WHERE DOCID = 2550 ORDER BY DTLID")
    first = record.details["COST_MATERIAL"][0].values
    assert (first["GOODSID"], first["GOODSNAME"], first["PRICE"]) == ("25", "聚维酮K30", "75")


def test_e30_on_d_cg(engine: Engine, uow: OracleUnitOfWorkFactory) -> None:
    """E30 真实验证：物料 115 且价格大于 3 的成本单，与旧系统同样条件（同一条明细的 EXISTS）查出的相同。"""
    advanced = {"op": "and", "conditions": [
        {"entity": "COST_MATERIAL", "group": "g1", "field": "GOODSID", "operator": "eq", "value": "115"},
        {"entity": "COST_MATERIAL", "group": "g1", "logic": "and", "field": "PRICE", "operator": "gt", "value": "3"}]}
    result = PageQueries(uow, FakePermissionChecker()).list(ctx(), PAGE, request(startRow=0, endRow=1000, advanced=advanced))
    old = column(engine, "SELECT a.DOCID FROM T_COST_PINGGU a WHERE EXISTS (SELECT 1 FROM V_COST_PINGGU_MATERIAL d "
                         "WHERE d.DOCID = a.DOCID AND (d.GOODSID = 115 AND d.PRICE > 3)) ORDER BY a.DOCID")
    assert [r.row_key for r in result.rows] == old and result.total == len(old) > 0


# ---------------------------------------------------------------- T-QE-2

def test_c06_relation_sql_finds_cost_details(engine: Engine, uow: OracleUnitOfWorkFactory) -> None:
    """C06 6.1 的关联 SQL 在 d_cg 上查出成本单的原辅料明细（聚维酮K30，物料 25）。"""
    finder = SqlFinder(kind="sql", entity="COST_MATERIAL",
                       sql="SELECT D.DOCID AS DOC_ID, D.DTLID AS DTL_ID FROM T_COST_PINGGU_DTL D WHERE D.GOODSID = :goodsId "
                           "ORDER BY D.DOCID, D.DTLID",
                       binds={"goodsId": "COST_GOODS_PRICE.GOODSID"}, record_key_column="DOC_ID", row_key_columns=["DTL_ID"])
    source = parse_document("COST_GOODS_PRICE", "25", {"GOODSID": Decimal(25)})
    with uow.begin() as unit:
        found = OracleRelatedQuery(FakeEntityDirectory(entities())).find(unit, finder, source)
    with engine.connect() as conn:
        expected = [(str(d), (str(t),)) for d, t in conn.execute(text(
            "SELECT DOCID, DTLID FROM T_COST_PINGGU_DTL WHERE GOODSID = 25 ORDER BY DOCID, DTLID"))]
    assert [(t.record_key, t.row_keys) for t in found] == expected and len({k for k, _ in expected}) > 1


def test_detail_bind_runs_per_row_and_each_document_once(engine: Engine, uow: OracleUnitOfWorkFactory) -> None:
    """成本单 2550 的原辅料中物料 25、115 两行：按两行各执行一次，含两种物料的成本单只返回一次。"""
    document = OracleDocumentReader(uow, FakeEntityDirectory(entities())).load(DocumentRef("COST_PINGGU", "2550"))
    assert document is not None
    document.details["COST_MATERIAL"] = [r for r in document.details["COST_MATERIAL"] if r.values["GOODSID"] in (25, 115)]
    assert [r.values["GOODSID"] for r in document.details["COST_MATERIAL"]] == [Decimal(25), Decimal(115)]
    finder = SqlFinder(kind="sql", entity="COST_PINGGU",
                       sql="SELECT M.DOCID AS DOC_ID FROM T_COST_PINGGU M WHERE EXISTS (SELECT 1 FROM T_COST_PINGGU_DTL D "
                           "WHERE D.DOCID = M.DOCID AND D.GOODSID = :goodsId) ORDER BY M.DOCID",
                       binds={"goodsId": "COST_MATERIAL.GOODSID"}, record_key_column="DOC_ID")
    with uow.begin() as unit:
        found = [t.record_key for t in OracleRelatedQuery(FakeEntityDirectory(entities())).find(unit, finder, document)]
    with_25 = column(engine, "SELECT DISTINCT DOCID FROM T_COST_PINGGU_DTL WHERE GOODSID = 25 ORDER BY DOCID")
    with_115 = column(engine, "SELECT DISTINCT DOCID FROM T_COST_PINGGU_DTL WHERE GOODSID = 115 ORDER BY DOCID")
    assert found == with_25 + [d for d in with_115 if d not in with_25]
    assert len(found) == len(set(found))


def test_document_reader_loads_2550(engine: Engine, uow: OracleUnitOfWorkFactory) -> None:
    document = OracleDocumentReader(uow, FakeEntityDirectory(entities())).load(DocumentRef("COST_PINGGU", "2550"))
    assert document is not None
    assert document.master.values["TOTAL_COST"] == scalar(engine, "SELECT TOTAL_COST FROM T_COST_PINGGU WHERE DOCID = 2550")
    assert [r.row_key for r in document.details["COST_PACKAGE"]] == column(
        engine, "SELECT DTLID FROM V_COST_PINGGU_PACKAGE WHERE DOCID = 2550 ORDER BY DTLID")
    assert OracleDocumentReader(uow, FakeEntityDirectory(entities())).load(DocumentRef("COST_PINGGU", "999999999")) is None


def test_lookup_on_t_cost_goods(engine: Engine, uow: OracleUnitOfWorkFactory) -> None:
    catalog = ItemsCatalog(lookups={"GOODS": LookupConfig(table="T_COST_GOODS", columns=["GOODSID", "GOODSNAME", "GOODSTYPE"],
                                                          keyword_columns=["GOODSID", "GOODSNAME"], order_by="GOODSID")})
    result = LookupQueries(uow, lambda c: catalog).search(
        ctx(), "GOODS", parse_wire(LookupSearchRequest, {"keyword": "胶囊", "startRow": 0, "endRow": 20}))
    where = "WHERE TO_CHAR(GOODSID) LIKE '%胶囊%' OR GOODSNAME LIKE '%胶囊%'"
    assert result.total == scalar(engine, f"SELECT COUNT(*) FROM T_COST_GOODS {where}") > 0
    assert [r.values["GOODSID"] for r in result.rows] == column(
        engine, f"SELECT GOODSID FROM T_COST_GOODS {where} ORDER BY GOODSID FETCH FIRST 20 ROWS ONLY")


def test_personal_config_on_d_cg(uow: OracleUnitOfWorkFactory) -> None:
    """需要 PF_PERSONAL_CONFIG（平台表升级后）。只替换请求中给出的部分。"""
    user = "qe-oracle-test"
    with uow.begin() as unit:
        unit.connection.execute(text("DELETE FROM pf_personal_config WHERE user_id = :u"), {"u": user})
        unit.commit()
    store = PersonalConfigStore(uow)
    grid = {"columns": [{"field": "DOCID", "width": 120, "pinned": "left", "hide": False}]}
    try:
        store.save(user, PAGE, parse_wire(PersonalConfig, {"grids": {"master": grid}}), ctx().now)
        saved = store.save(user, PAGE, parse_wire(PersonalConfig, {"detailMode": "stack"}), ctx().now)
        assert dump_wire(PersonalConfig, saved) == {"grids": {"master": grid}, "detailMode": "stack"}
    finally:
        with uow.begin() as unit:
            unit.connection.execute(text("DELETE FROM pf_personal_config WHERE user_id = :u"), {"u": user})
            unit.commit()


# ---------------------------------------------------------------- T-QE-3

def _cost_pinggu_export() -> ExportConfig:
    """seed 中按旧系统 cmx.T_COST_EXPORT_CONFIG 的 cost-pinggu-export 写的导出配置（`export.cost-pinggu-export.json` 的
    `content`，SQL 和列原文见 .reports/modules/queries-export/01-旧导出与个人配置.out.txt）；d_cg 复制的业务表没有 DELETED 列，
    去掉了 `m.DELETED = 0`。"""
    source = (SEED / "export.cost-pinggu-export.json").read_text(encoding="utf-8")
    return parse_wire(ExportConfig, json.loads(source)["content"])


def test_cost_pinggu_export_on_d_cg(engine: Engine, uow: OracleUnitOfWorkFactory) -> None:
    """以管理员导出 cost-pinggu-export：主表一张、每张有明细的成本单一张"明细_<DOCID>"，块、链接与旧系统相同；
    数值为数值单元格，`<v>` 为数据库原样的十进制文本（2566 的每批辅料成本有 40 位有效数字），文本为文本单元格。"""
    config = _cost_pinggu_export()
    catalog = ItemsCatalog(exports={"cost-pinggu-export": config})
    exports = Exports(uow, FakePermissionChecker(), lambda c: catalog)
    file = exports.export(ctx(), PAGE, parse_wire(ExportRequest, {"mode": "config", "exportCode": "cost-pinggu-export",
                                                                  "scope": "all", "request": {"startRow": 0, "endRow": 100}}))
    book = xlsx_reader.read(file.content)
    master = book.sheets[0]
    assert master.name == "物料成本核算" and book.fonts[0] == "Calibri"
    assert master.row(1) == [c.header for c in config.master.columns]
    assert len(master.rows()) - 1 == scalar(engine, "SELECT COUNT(*) FROM T_COST_PINGGU")
    with_details = scalar(engine, "SELECT COUNT(*) FROM (SELECT DOCID FROM V_COST_PINGGU_MATERIAL UNION "
                                  "SELECT DOCID FROM V_COST_PINGGU_PACKAGE)")
    assert len(book.sheets) - 1 == with_details
    sheet = book.sheet("明细_2550")
    materials = scalar(engine, "SELECT COUNT(*) FROM V_COST_PINGGU_MATERIAL WHERE DOCID = 2550")
    packages = scalar(engine, "SELECT COUNT(*) FROM V_COST_PINGGU_PACKAGE WHERE DOCID = 2550")
    titles = [r[0] for r in sheet.rows() if r and isinstance(r[0], str) and r[0].startswith("【")]
    assert titles == ["【原辅料明细】", "【包材明细】"]
    assert len(sheet.rows()) == 2 + materials + 1 + 2 + packages
    row_2550 = next(i for i, r in enumerate(master.rows(), start=1) if r and r[0] == "2550")
    assert master.links[f"A{row_2550}"] == "'明细_2550'!A1"
    assert sheet.links["A1"] == f"'物料成本核算'!A{row_2550}" and sheet.links["B3"] == f"'物料成本核算'!A{row_2550}"
    assert [master.cells[f"{c}{row_2550}"].kind for c in "ABC"] == ["n", "n", "s"]  # Summary ID、Product ID、Product Name
    assert [sheet.cells[f"{c}3"].kind for c in "ABE"] == ["n", "n", "s"]  # Details ID、Summary ID、Material Name
    row_2566 = next(i for i, r in enumerate(master.rows(), start=1) if r and r[0] == "2566")
    excipient = master.cells[f"O{row_2566}"]  # Excipient Cost/batch (Excl Rebate)，即 TOTAL_FL
    expected = format_decimal(scalar(engine, "SELECT TOTAL_FL FROM T_COST_PINGGU WHERE DOCID = 2566"))
    assert (excipient.kind, excipient.value) == ("n", expected)


def test_number_cell_on_d_cg(uow: OracleUnitOfWorkFactory) -> None:
    """数值为数值单元格，12345678.12345678 原样写进 `<v>`，不经过浮点。"""
    config = parse_wire(ExportConfig, {
        "page": PAGE, "name": "精度", "fileName": "精度",
        "master": {"sheet": "精度", "sql": 'SELECT m.DOCID AS DOCID, 12345678.12345678 AS "Big" FROM T_COST_PINGGU m WHERE m.DOCID = 2550',
                   "keyColumn": "DOCID", "columns": [{"field": "Big", "header": "Big"}]}})
    catalog = ItemsCatalog(exports={"big": config})
    file = Exports(uow, FakePermissionChecker(), lambda c: catalog).export(
        ctx(), PAGE, parse_wire(ExportRequest, {"mode": "config", "exportCode": "big", "scope": "all",
                                                "request": {"startRow": 0, "endRow": 1}}))
    cell = xlsx_reader.read(file.content).sheet("精度").cells["A2"]
    assert (cell.kind, cell.value) == ("n", "12345678.12345678")


def test_default_export_matches_list_on_d_cg(uow: OracleUnitOfWorkFactory) -> None:
    query = {"startRow": 0, "endRow": 2000, "sortModel": [{"colId": "TOTAL_COST", "sort": "desc"}],
             "filterModel": {"GOODSNAME": {"filterType": "text", "type": "contains", "filter": "片"}}}
    listed = PageQueries(uow, FakePermissionChecker()).list(ctx(), PAGE, parse_wire(ListRequest, query))
    file = Exports(uow, FakePermissionChecker(), lambda c: ItemsCatalog()).export(
        ctx(), PAGE, parse_wire(ExportRequest, {"mode": "page", "request": query, "columns": ["DOCID", "GOODSNAME"]}))
    rows = xlsx_reader.read(file.content).sheet("成本核算").rows()
    assert [r[0] for r in rows[1:]] == [r.row_key for r in listed.rows] and listed.total == len(listed.rows) > 0


def parse_document(entity: str, key: str, values: dict[str, Any]) -> DocumentData:
    return DocumentData(ref=DocumentRef(entity, key), master=Row(entity=entity, row_key=key, client_row_id=None, values=values),
                        details={})
