"""测试用：用标准库读出导出的 xlsx（工作表、单元格的值和类型、样式、超链接、列宽、字体）。"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


@dataclass
class CellData:
    value: str | bool
    kind: str  # s：文本（共享字符串）；b：是非
    style: int


def _position(ref: str) -> tuple[int, int]:
    """单元格引用转成（行号 1 起，列号 0 起）。"""
    letters, digits = re.match(r"([A-Z]+)(\d+)", ref).groups()  # type: ignore[union-attr]
    index = 0
    for ch in letters:
        index = index * 26 + ord(ch) - 64
    return int(digits), index - 1


@dataclass
class SheetData:
    name: str
    cells: dict[str, CellData] = field(default_factory=dict)
    links: dict[str, str] = field(default_factory=dict)
    widths: dict[int, float] = field(default_factory=dict)
    _grid: dict[int, dict[int, str | bool]] = field(default_factory=dict)

    def put(self, ref: str, cell: CellData) -> None:
        self.cells[ref] = cell
        row, col = _position(ref)
        self._grid.setdefault(row, {})[col] = cell.value

    def row(self, number: int) -> list[str | bool | None]:
        """第 number 行（1 起）从 A 列起的值，空单元格为 None，去掉末尾的空单元格。"""
        found = self._grid.get(number, {})
        return [found.get(i) for i in range(max(found) + 1)] if found else []

    def rows(self) -> list[list[str | bool | None]]:
        return [self.row(n) for n in range(1, max(self._grid, default=0) + 1)]


@dataclass
class Book:
    sheets: list[SheetData]
    fonts: list[str]

    def sheet(self, name: str) -> SheetData:
        return next(s for s in self.sheets if s.name == name)


def read(content: bytes) -> Book:
    archive = zipfile.ZipFile(io.BytesIO(content))
    strings = [si.findtext("m:t", default="", namespaces=NS)
               for si in ElementTree.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", NS)]
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    names = [s.get("name") or "" for s in workbook.findall("m:sheets/m:sheet", NS)]
    sheets = []
    for number, name in enumerate(names, start=1):
        root = ElementTree.fromstring(archive.read(f"xl/worksheets/sheet{number}.xml"))
        sheet = SheetData(name)
        for c in root.iter(f"{{{NS['m']}}}c"):
            raw = c.findtext("m:v", default="", namespaces=NS)
            kind = c.get("t") or "n"
            value: str | bool = strings[int(raw)] if kind == "s" else (raw == "1" if kind == "b" else raw)
            sheet.put(c.get("r") or "", CellData(value=value, kind=kind, style=int(c.get("s") or 0)))
        for link in root.iter(f"{{{NS['m']}}}hyperlink"):
            sheet.links[link.get("ref") or ""] = link.get("location") or ""
        for col in root.iter(f"{{{NS['m']}}}col"):
            sheet.widths[int(col.get("min") or 0) - 1] = float(col.get("width") or 0)
        sheets.append(sheet)
    styles = ElementTree.fromstring(archive.read("xl/styles.xml"))
    fonts = [f.find("m:name", NS).get("val") or "" for f in styles.findall("m:fonts/m:font", NS)]  # type: ignore[union-attr]
    return Book(sheets=sheets, fonts=fonts)
