"""读一个 xlsx 文件的工作表名称（只读本地文件，不连数据库）：xlsx 是 zip，工作表名称在 `xl/workbook.xml` 的 `<sheet name="…">`。

浏览器端到端用例 `frontend/tests/e2e/export-menu.spec.ts` 用它核对"自定义导出"下载到的文件。
用法（在 backend 目录）：`uv run python -m tests.e2e.xlsx_sheets <文件路径>`，输出一行 JSON，例如
`{"sheets": ["物料成本核算", "明细_2550"]}`，按工作簿中的顺序。
"""

from __future__ import annotations

import argparse
import json
import zipfile
from xml.etree import ElementTree

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def sheet_names(path: str) -> list[str]:
    with zipfile.ZipFile(path) as book:
        workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
    return [sheet.get("name", "") for sheet in workbook.iter(f"{_MAIN}sheet")]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    print(json.dumps({"sheets": sheet_names(args.path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
