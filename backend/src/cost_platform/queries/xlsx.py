"""最小的 xlsx 写入（Office Open XML，标准库 zipfile）：文本、数值、是非三种单元格，工作簿内超链接，列宽，字体和表头样式。

项目依赖中没有 Excel 库（缺口见 contract-gaps.md），这里只写导出需要的部分。样式取自旧系统
`CustomExportService`（EasyExcel + POI）：
- 内容：字体 `font`、11 号；
- 主表表头 `HEADER`：同一字体、不加粗，左对齐、垂直居中、自动换行，GREY_25_PERCENT 底色（索引色 22），细边框；
- 明细块表头 `BLOCK_HEADER`：同一字体、不加粗，左对齐、垂直居中，灰色底色，无边框；
- 超链接 `LINK`：同一字体，蓝色（索引色 12）、单下划线。
列宽按旧系统 LongestMatchColumnWidthStyleStrategy：每列最长内容的字节数（UTF-8，中文 3 字节），最多 255，单位为字符；
数值按它的十进制文本算。
数值（Decimal）写成数值单元格（QE-06）：`<c r="O2"><v>1292.385444247787610619469026548672566372</v></c>`，不带 `t`，
`<v>` 中是数据库原样的十进制文本，不经过浮点、不用科学计数法。Excel 打开时按双精度读，只保留 15 位有效数字（上例显示为
1292.38544424779），与旧系统相同（旧系统经 EasyExcel 写成 double）。
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from xml.sax.saxutils import escape, quoteattr

from cost_platform.contracts.decimal_text import format_decimal

BODY, HEADER, BLOCK_HEADER, LINK = 0, 1, 2, 3
MAX_WIDTH = 255

_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_NS_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _clean(text: str) -> str:
    return _INVALID_XML.sub("", text)


def column_letter(index: int) -> str:
    """0 起的列号转成 Excel 的列字母：0 -> A，26 -> AA。"""
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def location(sheet: str, row: int, column: int = 0) -> str:
    """工作簿内的位置，例如 `'明细_2550'!A1`；row 为 0 起的行号。"""
    return f"'{sheet.replace(chr(39), chr(39) * 2)}'!{column_letter(column)}{row + 1}"


CellValue = str | bool | Decimal | None
"""单元格的值：文本、是非、数值（Decimal）；为空时不写单元格。"""


def cell_text(value: str | bool | Decimal) -> str:
    """单元格内容的文本：数值为十进制文本，是非为 true/false。列宽按它算，导出按它推断链接列。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format_decimal(value)
    return value


@dataclass(frozen=True)
class Cell:
    value: CellValue
    style: int = BODY
    link: str | None = None
    """工作簿内的位置（`location` 生成）；为空时没有链接。"""


@dataclass
class Sheet:
    name: str
    rows: list[list[Cell]] = field(default_factory=list)
    widths: dict[int, int] = field(default_factory=dict)

    def append(self, cells: list[Cell]) -> int:
        """追加一行，返回这一行的行号（0 起）；同时按内容更新列宽。"""
        for i, cell in enumerate(cells):
            if cell.value is None:
                continue
            width = min(len(_clean(cell_text(cell.value)).encode("utf-8")), MAX_WIDTH)
            if width > self.widths.get(i, -1):
                self.widths[i] = width
        self.rows.append(cells)
        return len(self.rows) - 1


class Workbook:
    def __init__(self, font: str = "Calibri") -> None:
        self.font = font
        self.sheets: list[Sheet] = []

    def sheet(self, name: str) -> Sheet:
        sheet = Sheet(name)
        self.sheets.append(sheet)
        return sheet

    def to_bytes(self) -> bytes:
        strings: dict[str, int] = {}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for number, sheet in enumerate(self.sheets, start=1):
                archive.writestr(f"xl/worksheets/sheet{number}.xml", _sheet_xml(sheet, strings))
            archive.writestr("[Content_Types].xml", self._content_types())
            archive.writestr("_rels/.rels", _DECL + (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                'Target="xl/workbook.xml"/></Relationships>'))
            archive.writestr("xl/workbook.xml", self._workbook())
            archive.writestr("xl/_rels/workbook.xml.rels", self._workbook_rels())
            archive.writestr("xl/styles.xml", self._styles())
            archive.writestr("xl/sharedStrings.xml", _shared_strings(strings))
        return buffer.getvalue()

    def _content_types(self) -> str:
        sheets = "".join(
            f'<Override PartName="/xl/worksheets/sheet{n}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for n in range(1, len(self.sheets) + 1))
        return _DECL + (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            f"{sheets}"
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            "</Types>")

    def _workbook(self) -> str:
        sheets = "".join(f'<sheet name={quoteattr(_clean(s.name))} sheetId="{n}" r:id="rId{n}"/>'
                         for n, s in enumerate(self.sheets, start=1))
        return _DECL + f"<workbook {_NS} {_NS_R}><sheets>{sheets}</sheets></workbook>"

    def _workbook_rels(self) -> str:
        count = len(self.sheets)
        sheets = "".join(
            f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{n}.xml"/>' for n in range(1, count + 1))
        return _DECL + (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{sheets}"
            f'<Relationship Id="rId{count + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/>'
            f'<Relationship Id="rId{count + 2}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
            "</Relationships>")

    def _styles(self) -> str:
        font = quoteattr(_clean(self.font))
        return _DECL + (
            f"<styleSheet {_NS}>"
            f'<fonts count="2"><font><sz val="11"/><name val={font}/></font>'
            f'<font><u/><sz val="11"/><color indexed="12"/><name val={font}/></font></fonts>'
            '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid"><fgColor indexed="22"/><bgColor indexed="64"/></patternFill></fill></fills>'
            '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
            '<border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="4">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="0" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" '
            'applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>'
            '<xf numFmtId="0" fontId="0" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1">'
            '<alignment horizontal="left" vertical="center"/></xf>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
            "</cellXfs>"
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            "</styleSheet>")


def _sheet_xml(sheet: Sheet, strings: dict[str, int]) -> str:
    parts = [_DECL, f"<worksheet {_NS} {_NS_R}>"]
    if sheet.widths:
        cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in sorted(sheet.widths.items()))
        parts.append(f"<cols>{cols}</cols>")
    parts.append("<sheetData>")
    links: list[str] = []
    for r, cells in enumerate(sheet.rows, start=1):
        row: list[str] = []
        for c, cell in enumerate(cells):
            if cell.value is None:
                continue
            ref = f"{column_letter(c)}{r}"
            style = f' s="{cell.style}"' if cell.style else ""
            if isinstance(cell.value, bool):
                row.append(f'<c r="{ref}"{style} t="b"><v>{1 if cell.value else 0}</v></c>')
            elif isinstance(cell.value, Decimal):
                row.append(f'<c r="{ref}"{style}><v>{format_decimal(cell.value)}</v></c>')
            else:
                text = _clean(cell.value)
                index = strings.setdefault(text, len(strings))
                row.append(f'<c r="{ref}"{style} t="s"><v>{index}</v></c>')
            if cell.link:
                links.append(f'<hyperlink ref="{ref}" location={quoteattr(_clean(cell.link))}/>')
        if row:
            parts.append(f'<row r="{r}">{"".join(row)}</row>')
    parts.append("</sheetData>")
    if links:
        parts.append(f"<hyperlinks>{''.join(links)}</hyperlinks>")
    parts.append("</worksheet>")
    return "".join(parts)


def _shared_strings(strings: dict[str, int]) -> str:
    items = []
    for text in strings:  # dict 保持插入顺序，与索引一致
        space = ' xml:space="preserve"' if text != text.strip() or "\n" in text else ""
        items.append(f"<si><t{space}>{escape(text)}</t></si>")
    return _DECL + f'<sst {_NS} count="{len(strings)}" uniqueCount="{len(strings)}">{"".join(items)}</sst>'
