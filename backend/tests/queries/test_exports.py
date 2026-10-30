"""T-QE-3 的模拟验证：导出（QE-06，C06 第 9 节的版式，与旧系统 CustomExportService 相同）。"""

from __future__ import annotations

import io
import zipfile
from decimal import Decimal
from typing import Any

import pytest

from cost_platform.contracts.fakes import FakePermissionChecker
from cost_platform.contracts.types import (
    ErrorCode,
    ExportConfig,
    ExportRequest,
    ListRequest,
    PlatformError,
    SqlCondition,
    parse_wire,
)
from cost_platform.queries.catalog import ItemsCatalog
from cost_platform.queries.exports import Exports, _field_value
from cost_platform.queries.lists import PageQueries
from cost_platform.queries.xlsx import HEADER, LINK, Cell, Workbook

from . import xlsx_reader
from .support import MASTER, PAGE, context, database, field

MASTER_SQL = ('SELECT m.DOCID AS DOCID, m.DOCID AS "Summary ID", m.GOODSNAME AS "Product Name", '
              'm.TOTAL_COST AS "Total Mat Costs/batch (Excl Rebate)" FROM T_COST_PINGGU m ORDER BY m.DOCID')
MATERIAL_SQL = ('SELECT d.DOCID AS DOCID, d.DTLID AS "Details ID", d.DOCID AS "Summary ID", d.GOODSNAME AS "Material Name", '
                'd.PRICE AS "Unit price (VAT included)" FROM V_COST_PINGGU_MATERIAL d ORDER BY d.DTLID')
DETAIL_COLUMNS = [{"field": f, "header": f} for f in ("Details ID", "Summary ID", "Material Name", "Unit price (VAT included)")]


def export_config(**changes: Any) -> ExportConfig:
    """仿照 cost-pinggu-export：主表一张，原辅料、包材两个明细块（这里的"包材"取物料 116 的明细）。"""
    body: dict[str, Any] = {
        "page": PAGE, "name": "物料成本核算表导出", "fileName": "物料成本核算表",
        "master": {"sheet": "物料成本核算", "sql": MASTER_SQL, "keyColumn": "DOCID",
                   "columns": [{"field": f, "header": f} for f in ("Summary ID", "Product Name", "Total Mat Costs/batch (Excl Rebate)")]},
        "details": [
            {"sheet": "原辅料明细", "sql": MATERIAL_SQL, "linkColumn": "DOCID", "columns": DETAIL_COLUMNS},
            {"sheet": "包材明细", "sql": MATERIAL_SQL.replace(" ORDER BY", " WHERE d.GOODSID = 116 ORDER BY"), "linkColumn": "DOCID",
             "columns": DETAIL_COLUMNS},
        ],
        **changes,
    }
    return parse_wire(ExportConfig, body)


def make(permission: FakePermissionChecker | None = None, **configs: ExportConfig) -> Exports:
    catalog = ItemsCatalog(exports=configs or {"cost-pinggu-export": export_config()})
    return Exports(database(), permission or FakePermissionChecker(), lambda ctx: catalog, batch_size=2)


def body(**fields: Any) -> Any:
    return parse_wire(ExportRequest, fields)


def list_request(**fields: Any) -> dict[str, Any]:
    return {"startRow": 0, "endRow": 100, **fields}


def test_default_export_has_the_shown_columns_and_the_list_rows() -> None:
    """默认导出当前页面：列为用户当前显示的列，行和顺序与列表相同（全部满足条件的行，不分页）；数值字段（单据号、总成本）
    为数值单元格，`<v>` 与列表返回的十进制文本相同，产品名称为文本单元格。"""
    query = list_request(sortModel=[{"colId": "TOTAL_COST", "sort": "desc"}],
                         filterModel={"GOODSNAME": {"filterType": "text", "type": "contains", "filter": "胶囊"}})
    file = make().export(context(), PAGE, body(mode="page", request=query, columns=["GOODSNAME", "DOCID", "TOTAL_COST"]))
    assert file.file_name == "成本核算.xlsx"
    assert file.content_disposition == "attachment; filename*=UTF-8''%E6%88%90%E6%9C%AC%E6%A0%B8%E7%AE%97.xlsx"
    sheet = xlsx_reader.read(file.content).sheet("成本核算")
    listed = PageQueries(database(), FakePermissionChecker()).list(context(), PAGE, parse_wire(ListRequest, {**query, "endRow": 1}))
    every = PageQueries(database(), FakePermissionChecker()).list(context(), PAGE, parse_wire(ListRequest, query))
    assert listed.total == len(every.rows) == 3
    rows = sheet.rows()
    assert rows[0] == ["产品名称", "单据号", "总成本"]
    expected = [[r.values["GOODSNAME"], r.values["DOCID"], r.values["TOTAL_COST"]] for r in every.rows]
    assert rows[1:] == [cells[:2] if cells[2] is None else cells for cells in expected]  # 空值不写单元格（1005 的总成本）
    kinds = {col: {c.kind for ref, c in sheet.cells.items() if ref[0] == col and ref != f"{col}1"} for col in "ABC"}
    assert kinds == {"A": {"s"}, "B": {"n"}, "C": {"n"}}
    assert all(sheet.cells[ref].style == HEADER for ref in ("A1", "B1", "C1"))


def test_default_export_only_visible_columns() -> None:
    """默认导出的列必须对当前角色可见：创建人不可见，返回 422。"""
    with pytest.raises(PlatformError) as caught:
        make().export(context(), PAGE, body(mode="page", request=list_request(), columns=["DOCID", "CREATE_BY"]))
    assert caught.value.code is ErrorCode.VALIDATION_FAILED


def test_numbers_are_number_cells_with_the_database_digits() -> None:
    """数值写成数值单元格（不带 t），`<v>` 是数据库原样的十进制文本，不经过浮点、不用科学计数法：d_cg 成本单 2566 的
    每批辅料成本 1292.385444247787610619469026548672566372 原样写出（Excel 打开后只保留 15 位有效数字，显示 1292.38544424779，
    与旧系统相同），12345678.12345678、8 位小数的 0.00000001 也一样。"""
    values = ["1292.385444247787610619469026548672566372", "12345678.12345678", "0.00000001"]
    workbook = Workbook()
    sheet = workbook.sheet("s")
    sheet.append([Cell(_field_value(field("TOTAL_FL", "每批辅料成本"), Decimal(v))) for v in values])
    xml = zipfile.ZipFile(io.BytesIO(workbook.to_bytes())).read("xl/worksheets/sheet1.xml").decode()
    assert ('<row r="1"><c r="A1"><v>1292.385444247787610619469026548672566372</v></c><c r="B1"><v>12345678.12345678</v></c>'
            '<c r="C1"><v>0.00000001</v></c></row>') in xml
    assert sheet.widths == {0: 41, 1: 17, 2: 10}  # 列宽仍按十进制文本的字节数


def test_role_without_the_export_config_is_denied() -> None:
    permission = FakePermissionChecker()
    permission.deny_export(PAGE, "cost-pinggu-export")
    with pytest.raises(PlatformError) as caught:
        make(permission).export(context(), PAGE, body(mode="config", exportCode="cost-pinggu-export", scope="all",
                                                      request=list_request()))
    assert caught.value.code is ErrorCode.PERMISSION_DENIED


def test_available_exports_only_for_the_role() -> None:
    permission = FakePermissionChecker()
    permission.deny_export(PAGE, "secret-export")
    exports = make(permission, **{"cost-pinggu-export": export_config(), "secret-export": export_config(name="内部导出"),
                                  "other-page": export_config(page="OTHER_PAGE")})
    assert [(i.export_code, i.name) for i in exports.available(context(), PAGE).items] == [("cost-pinggu-export", "物料成本核算表导出")]


def test_per_master_layout_like_the_old_export() -> None:
    """perMaster：主表一张工作表；每张有明细的主单一张"明细_<主键>"，块为标题行、表头行、数据行，块之间空一行；
    主表的 Summary ID 链接到明细工作表，明细标题行和 Summary ID 链接回主表的行；表头一行、"/" 原样保留。
    SQL 查出的数值（Summary ID、总成本、单价）为数值单元格，链接列的数值单元格带链接样式；链接列仍按值推断到 Summary ID。"""
    file = make().export(context(), PAGE, body(mode="config", exportCode="cost-pinggu-export", scope="all", request=list_request()))
    assert file.file_name == "物料成本核算表.xlsx"
    book = xlsx_reader.read(file.content)
    assert [s.name for s in book.sheets] == ["物料成本核算", "明细_1001", "明细_1002", "明细_1003", "明细_1004"]
    assert book.fonts == ["Calibri", "Calibri"]

    master = book.sheet("物料成本核算")
    assert master.rows() == [["Summary ID", "Product Name", "Total Mat Costs/batch (Excl Rebate)"],
                             ["1001", "胶囊A", "10.5"], ["1002", "片剂B", "20.25"], ["1003", "胶囊C", "10.5"],
                             ["1004", "Granule d", "5"], ["1005", "胶囊E"]]
    assert all(master.cells[f"{c}1"].style == HEADER for c in "ABC")
    assert [(master.cells[r].kind, master.cells[r].style) for r in ("A2", "B2", "C2")] == [("n", LINK), ("s", 0), ("n", 0)]
    assert master.links == {"A2": "'明细_1001'!A1", "A3": "'明细_1002'!A1", "A4": "'明细_1003'!A1", "A5": "'明细_1004'!A1"}
    assert master.widths == {0: 10, 1: 12, 2: 35}

    detail = book.sheet("明细_1002")
    assert detail.rows() == [["【原辅料明细】"], ["Details ID", "Summary ID", "Material Name", "Unit price (VAT included)"],
                             ["5002", "1002", "硬脂酸镁", "2"], ["5003", "1002", "胶囊壳", "5"], [""],
                             ["【包材明细】"], ["Details ID", "Summary ID", "Material Name", "Unit price (VAT included)"],
                             ["5003", "1002", "胶囊壳", "5"]]
    assert detail.links == {"A1": "'物料成本核算'!A3", "B3": "'物料成本核算'!A3", "B4": "'物料成本核算'!A3",
                            "A6": "'物料成本核算'!A3", "B8": "'物料成本核算'!A3"}
    assert detail.cells["A2"].style == 2 and detail.cells["A1"].style == 3
    assert [(detail.cells[r].kind, detail.cells[r].style) for r in ("A3", "B3", "C3", "D3")] == [("n", 0), ("n", LINK), ("s", 0), ("n", 0)]
    assert detail.widths[0] == len("【原辅料明细】".encode()) == 21
    assert [r[0] for r in book.sheet("明细_1001").rows()] == ["【原辅料明细】", "Details ID", "5001"]


def test_scope_all_uses_row_permission_and_current_uses_the_query() -> None:
    """scope 为 all 时只按行权限限定，为 current 时按当前查询条件和行权限限定；明细随主表。"""
    permission = FakePermissionChecker()
    permission.set_rows(PAGE, MASTER, SqlCondition(sql="CREATE_BY = :rp_user", binds={"rp_user": "zhang"}))
    exports = make(permission)
    query = list_request(filterModel={"GOODSNAME": {"filterType": "text", "type": "contains", "filter": "胶囊"}})

    every = xlsx_reader.read(exports.export(context(), PAGE, body(mode="config", exportCode="cost-pinggu-export", scope="all",
                                                                  request=query)).content)
    assert [r[0] for r in every.sheet("物料成本核算").rows()[1:]] == ["1001", "1003", "1004"]
    assert [s.name for s in every.sheets] == ["物料成本核算", "明细_1001", "明细_1003", "明细_1004"]

    current = xlsx_reader.read(exports.export(context(), PAGE, body(mode="config", exportCode="cost-pinggu-export",
                                                                    scope="current", request=query)).content)
    assert [r[0] for r in current.sheet("物料成本核算").rows()[1:]] == ["1001", "1003"]
    assert [s.name for s in current.sheets] == ["物料成本核算", "明细_1001", "明细_1003"]


def test_sort_applies_when_the_sql_has_no_order_by() -> None:
    """旧系统 appendOrderByClause：SQL 没有 ORDER BY 时，按请求中与导出列同名的排序字段排序。"""
    config = export_config(master={"sheet": "主表", "sql": "SELECT m.DOCID AS DOCID, m.GOODSNAME AS GOODSNAME FROM T_COST_PINGGU m",
                                   "keyColumn": "DOCID", "columns": [{"field": "DOCID", "header": "单据号"},
                                                                     {"field": "GOODSNAME", "header": "产品"}]}, details=[])
    request = list_request(sortModel=[{"colId": "GOODSNAME", "sort": "desc"}])
    file = make(**{"plain": config}).export(context(), PAGE, body(mode="config", exportCode="plain", scope="all", request=request))
    assert [r[1] for r in xlsx_reader.read(file.content).sheet("主表").rows()[1:]] == ["胶囊E", "胶囊C", "胶囊A", "片剂B", "Granule d"]


def test_per_detail_layout() -> None:
    """perDetail：每个明细配置一张工作表，表头与主表相同，Summary ID 链接回主表。"""
    config = export_config(detailLayout="perDetail", details=[export_config().details[0].model_dump(by_alias=True)])
    book = xlsx_reader.read(make(**{"cost-pinggu-export": config}).export(
        context(), PAGE, body(mode="config", exportCode="cost-pinggu-export", scope="all", request=list_request())).content)
    assert [s.name for s in book.sheets] == ["物料成本核算", "原辅料明细"]
    detail = book.sheet("原辅料明细")
    assert [r[0] for r in detail.rows()] == ["Details ID", "5001", "5002", "5003", "5004", "5005", "5006"]
    assert detail.links["B2"] == "'物料成本核算'!A2" and detail.cells["A1"].style == HEADER
    assert book.sheet("物料成本核算").links["A3"] == "'原辅料明细'!A3"
