"""从 cmx 复制业务表到 d_cg（DB-03）。

整表复制结构和数据（CTAS），补上列默认值和主键，建序列 `<表名>_SEQ`，起始值为最大主键加一。
已存在的表不动；`refresh` 中的表先删除再复制。cmx 只读。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import Connection, Engine, text

TABLE_LIST = Path(__file__).resolve().parent / "business_tables.txt"
_NAME = re.compile(r"[A-Z][A-Z0-9_]*")


def table_list() -> list[str]:
    lines = TABLE_LIST.read_text(encoding="utf-8").splitlines()
    return [s.strip().upper() for s in lines if s.strip() and not s.lstrip().startswith("#")]


def _exists(conn: Connection, view: str, column: str, name: str) -> bool:
    sql = f"SELECT COUNT(*) FROM {view} WHERE {column} = :n"
    return bool(conn.execute(text(sql), {"n": name}).scalar())


def _copy(conn: Connection, table: str) -> str:
    columns = conn.execute(text(
        "SELECT column_name, virtual_column, data_default FROM all_tab_cols "
        "WHERE owner = 'CMX' AND table_name = :t AND hidden_column = 'NO' ORDER BY column_id"), {"t": table}).all()
    stored = [c for c in columns if c[1] == "NO"]
    conn.exec_driver_sql(f"CREATE TABLE {table} AS SELECT {', '.join(c[0] for c in stored)} FROM CMX.{table}")
    for column, _, default in stored:
        expression = str(default).strip() if default is not None else ""
        # cmx 标识列的默认值取 cmx 自己的序列；平台新增行的主键取 <表名>_SEQ（WP-09），不复制这个默认值
        if expression and "NEXTVAL" not in expression.upper():
            conn.exec_driver_sql(f"ALTER TABLE {table} MODIFY ({column} DEFAULT {expression})")
    for column, virtual, default in columns:
        if virtual == "YES":  # 虚拟列照原样建，表达式中只引用本表的列
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD ({column} AS ({str(default).strip()}))")
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
    conn.exec_driver_sql(f"CREATE SEQUENCE {sequence} START WITH {int(rows[1]) + 1} NOCACHE")
    return f"{table}: 已复制 {rows[0]} 行，主键 {pk_name}({', '.join(pk_columns)})，序列 {sequence} 从 {int(rows[1]) + 1} 开始"


def copy_business_tables(engine: Engine, tables: Iterable[str], refresh: Iterable[str] = ()) -> list[str]:
    """返回每张表的处理结果。"""
    refresh_set = {t.upper() for t in refresh}
    report: list[str] = []
    with engine.connect() as conn:
        for table in tables:
            if not _NAME.fullmatch(table) or table.startswith(("BP_T09_", "PF_")):
                raise ValueError(f"不能复制的表名：{table}")
            if _exists(conn, "user_tables", "table_name", table):
                if table not in refresh_set:
                    report.append(f"{table}: 已存在，未改动")
                    continue
                conn.exec_driver_sql(f"DROP TABLE {table} PURGE")
            report.append(_copy(conn, table))
    return report
