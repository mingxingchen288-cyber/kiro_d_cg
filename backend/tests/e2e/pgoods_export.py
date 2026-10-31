"""端到端用例 `frontend/tests/e2e/pgoods-export-1031.spec.ts` 用：按旧系统代码推出"产品选择(按物料)导出"（旧导出编码
goods-price-pgoods-export，cmx T_COST_EXPORT_CONFIG 21）对物料清单按物料ID筛选的"导出当前"会写出什么，与下载的文件逐格比较。

旧代码（`cost-server/.../export/service/CustomExportService.java`）的推法：
- 文件名为导出名称 + .xlsx（第 141 行），只有一张工作表，名称为 MASTER_SHEET_NAME（第 151 行），没有明细。
- "导出当前"在主表 SQL 后面接 `WHERE EXISTS (SELECT 1 FROM <页面查询视图> p WHERE p.GOODSID = m.GOODSID <页面筛选>)`
  （buildMasterSql、buildPageExistsClause，第 236、296 行）；COLUMNS 为空，不排序（appendOrderByClause 第 502 行）。
- 列取第一行结果的 Map 的键（resolveColumns 第 987 行），表头就是键名。Map 是 MyBatis 默认的 HashMap：值为空的列不放进去，
  键按 HashMap 的顺序（`.reports/batch8-20261031/g3-audit-export/hashmap_order.py`）；SQL 中 GOODSNAME 选了两次，Map 里只有一个。
- 单元格：数值写成数值单元格，文本写成文本（normalizeCellValue）。

数据：d_cg（只读查询）。主表 SQL 用 seed 配置的那一条（旧视图 V_COST_PGOODS_BY_MGOODS 按 d_cg 的表展开，见 seed
`export.goods-price-pgoods-export.json`），后面照旧代码接 EXISTS。
用法（backend 目录）：uv run python -m tests.e2e.pgoods_export <下载的文件> <物料ID>，输出一行 JSON：
`{"fileName": 旧系统的文件名, "sheets": [...], "header": [...], "rows": 行数, "mismatches": [前 20 处不同]}`。
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from tests.queries.xlsx_reader import read

from .dcg import oracle_engine, rows

SEED = Path(__file__).resolve().parents[2] / "seed" / "config" / "export.goods-price-pgoods-export.json"
PAGE_VIEW = "T_COST_GOODS_PRICE_V"
OLD_SQL_COLUMNS = ["GOODSID", "GOODSNAME", "DTL_USEFLAG", "FACTORYNAME", "PRICE", "GOODSNO", "PGOODSID", "PGOODSNO",
                   "GOODSNAME", "APEX_PL", "BATCH_QTY"]
"""旧配置 MASTER_SQL 选出的列，按 SQL 中的顺序（MyBatis 按这个顺序放进 Map）。"""


def java_hash(text: str) -> int:
    value = 0
    for ch in text:
        value = (31 * value + ord(ch)) & 0xFFFFFFFF
    return value


def hashmap_keys(keys: list[str], capacity: int = 16) -> list[str]:
    """java.util.HashMap 的遍历顺序：下标 (h ^ (h >>> 16)) & (容量 - 1)，同一下标按放入的先后。"""
    buckets: dict[int, list[str]] = {}
    for key in dict.fromkeys(keys):
        h = java_hash(key)
        buckets.setdefault((h ^ (h >> 16)) & (capacity - 1), []).append(key)
    return [k for i in range(capacity) for k in buckets.get(i, [])]


def expected(goodsid: int) -> tuple[str, str, list[str], list[dict[str, Any]]]:
    config = json.loads(SEED.read_text(encoding="utf-8"))["content"]
    sql = (f"{config['master']['sql']} WHERE EXISTS (SELECT 1 FROM {PAGE_VIEW} p WHERE p.GOODSID = m.GOODSID "
           f"AND p.GOODSID = :g)")
    engine = oracle_engine()
    try:
        found = rows(engine, sql, g=goodsid)
    finally:
        engine.dispose()
    maps = [{c: r[c.lower()] for c in OLD_SQL_COLUMNS if r[c.lower()] is not None} for r in found]
    header = hashmap_keys([c for c in OLD_SQL_COLUMNS if maps and c in maps[0]])
    return f"{config['name']}.xlsx", config["master"]["sheet"], header, maps


def compare(path: str, goodsid: int) -> dict[str, Any]:
    file_name, sheet_name, header, maps = expected(goodsid)
    book = read(Path(path).read_bytes())
    mismatches: list[str] = []
    sheet = book.sheet(sheet_name) if any(s.name == sheet_name for s in book.sheets) else None
    if sheet is None:
        mismatches.append(f"没有工作表 {sheet_name}")
    else:
        if sheet.row(1) != header:
            mismatches.append(f"表头 {sheet.row(1)}，旧系统 {header}")
        if len(sheet.rows()) != len(maps) + 1:
            mismatches.append(f"{len(sheet.rows()) - 1} 行数据，旧系统 {len(maps)} 行")
        for i, values in enumerate(maps, start=2):
            for j, column in enumerate(header):
                ref = f"{chr(65 + j)}{i}"
                want, got = values.get(column), sheet.cells.get(ref)
                if want is None:
                    ok = got is None or got.value == ""
                elif isinstance(want, (int, Decimal)):
                    ok = got is not None and got.kind == "n" and Decimal(str(got.value)) == Decimal(want)
                else:
                    ok = got is not None and got.kind == "s" and got.value == str(want)
                if not ok:
                    mismatches.append(f"{ref}（{column}）为 {None if got is None else (got.kind, got.value)}，旧系统 {want!r}")
    return {"fileName": file_name, "sheets": [s.name for s in book.sheets], "header": header, "rows": len(maps),
            "mismatches": mismatches[:20]}


def main() -> None:
    print(json.dumps(compare(sys.argv[1], int(sys.argv[2])), ensure_ascii=False))


if __name__ == "__main__":
    main()
