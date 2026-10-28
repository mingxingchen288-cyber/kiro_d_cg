"""从 cmx 复制业务表到 d_cg（DB-03）。

只复制 business_tables.json 为每张表列出的列（页面显示的列，以及用户点名保留的列），按 cmx 的列顺序；
虚拟列复制为普通列，值为复制时 cmx 算出的当前值；`excludeDeleted` 为 true 时不复制已删除（DELETED=1）的行。
补上列默认值和主键，建序列 `<表名>_SEQ`，起始值为最大主键加一。
已存在的表不动；`refresh` 中的表先删除再复制。cmx 只读。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, Engine, text

TABLE_SPECS = Path(__file__).resolve().parent / "business_tables.json"
_NAME = re.compile(r"[A-Z][A-Z0-9_]*")


@dataclass(frozen=True)
class TableSpec:
    columns: tuple[str, ...]
    exclude_deleted: bool


def table_specs() -> dict[str, TableSpec]:
    data = json.loads(TABLE_SPECS.read_text(encoding="utf-8"))
    return {name.upper(): TableSpec(tuple(c.upper() for c in spec["columns"]), bool(spec.get("excludeDeleted", False)))
            for name, spec in data.items()}


def _exists(conn: Connection, view: str, column: str, name: str) -> bool:
    sql = f"SELECT COUNT(*) FROM {view} WHERE {column} = :n"
    return bool(conn.execute(text(sql), {"n": name}).scalar())


def _copy(conn: Connection, table: str, spec: TableSpec) -> str:
    source = conn.execute(text(
        "SELECT column_name, virtual_column, data_default FROM all_tab_cols "
        "WHERE owner = 'CMX' AND table_name = :t AND hidden_column = 'NO' ORDER BY column_id"), {"t": table}).all()
    missing = sorted(set(spec.columns) - {c[0] for c in source})
    if missing:
        raise ValueError(f"{table} 在 cmx 中没有这些列：{', '.join(missing)}")
    wanted = set(spec.columns)
    columns = [c for c in source if c[0] in wanted]
    where = " WHERE NVL(DELETED, 0) = 0" if spec.exclude_deleted else ""
    # CTAS 选出的虚拟列在新表中是普通列，值为 cmx 当前算出的结果
    conn.exec_driver_sql(f"CREATE TABLE {table} AS SELECT {', '.join(c[0] for c in columns)} FROM CMX.{table}{where}")
    for column, virtual, default in columns:
        expression = str(default).strip() if default is not None else ""
        # 虚拟列的表达式不作为默认值；cmx 标识列的默认值取 cmx 自己的序列，平台新增行的主键取 <表名>_SEQ（WP-09）
        if virtual == "NO" and expression and "NEXTVAL" not in expression.upper():
            conn.exec_driver_sql(f"ALTER TABLE {table} MODIFY ({column} DEFAULT {expression})")
    pk = conn.execute(text(
        "SELECT c.constraint_name, cc.column_name FROM all_constraints c "
        "JOIN all_cons_columns cc ON cc.owner = c.owner AND cc.constraint_name = c.constraint_name "
        "WHERE c.owner = 'CMX' AND c.table_name = :t AND c.constraint_type = 'P' ORDER BY cc.position"), {"t": table}).all()
    pk_name, pk_columns = pk[0][0], [row[1] for row in pk]
    conn.exec_driver_sql(f"ALTER TABLE {table} ADD CONSTRAINT {pk_name} PRIMARY KEY ({', '.join(pk_columns)})")
    rows = conn.execute(text(f"SELECT COUNT(*), NVL(MAX({pk_columns[0]}), 0) FROM {table}")).one()
    sequence = f"{table}_SEQ"
    if _exists(conn, "user_sequences", "sequence_name", sequence):
        conn.exec_driver_sql(f"DROP SEQUENCE {sequence}")
    # 序列从 cmx 的最大主键加一开始（含已删除的行），不重用旧主键
    max_key = conn.execute(text(f"SELECT NVL(MAX({pk_columns[0]}), 0) FROM CMX.{table}")).scalar()
    conn.exec_driver_sql(f"CREATE SEQUENCE {sequence} START WITH {int(max_key) + 1} NOCACHE")
    virtual_count = sum(1 for c in columns if c[1] == "YES")
    return (f"{table}: 复制 {rows[0]} 行、{len(columns)} 列（cmx 共 {len(source)} 列，其中 {virtual_count} 个虚拟列改为普通列），"
            f"主键 {pk_name}({', '.join(pk_columns)})，序列 {sequence} 从 {int(max_key) + 1} 开始")


def copy_business_tables(engine: Engine, specs: Mapping[str, TableSpec], refresh: Iterable[str] = ()) -> list[str]:
    """返回每张表的处理结果。"""
    refresh_set = {t.upper() for t in refresh}
    report: list[str] = []
    with engine.connect() as conn:
        for table, spec in specs.items():
            if not _NAME.fullmatch(table) or table.startswith(("BP_T09_", "PF_")):
                raise ValueError(f"不能复制的表名：{table}")
            if _exists(conn, "user_tables", "table_name", table):
                if table not in refresh_set:
                    report.append(f"{table}: 已存在，未改动")
                    continue
                conn.exec_driver_sql(f"DROP TABLE {table} PURGE")
            report.append(_copy(conn, table, spec))
    return report
