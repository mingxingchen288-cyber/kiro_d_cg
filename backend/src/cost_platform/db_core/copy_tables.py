"""从 cmx 复制业务表和视图到 d_cg（DB-03）。

表：只复制 business_tables.json 为每张表列出的列（页面显示的列，以及用户点名保留的列），按 cmx 的列顺序；
虚拟列复制为普通列，值为复制时 cmx 算出的当前值；`excludeDeleted` 为 true 时不复制已删除（DELETED=1）的行；
`parent` 给出主表时，只复制主表中未删除的行的明细（主表的 `excludeDeleted` 为 true 时）。
补上列默认值和主键，建序列 `<表名>_SEQ`，起始值为 cmx 最大主键加一。保留列在 cmx 中的列注释也一起复制
（旧向导的列标题取列注释，`SchemaInspector` 的 `column_comments` 读它；2026-10-29 加入，之前复制的表要 `--refresh` 才有）。
视图（`"kind": "view"`）：清单中写的是 d_cg 版本的 SQL（去掉方案名、引用 d_cg 的表、去掉不复制的列和 DELETED 条件），
按它建视图。例外是 `"readsCmx": true` 的视图：它们直接读 cmx 的同名视图（`reason` 写明为什么 d_cg 的表做不出来），
例如成本核算主表的产品 Lookup：产品的"BOM状态"由 cmx 视图经 ERP 数据库链接算出（2026-10-30）；币种 Lookup 的汇率
同样经 ERP 数据库链接取出（T_COST_FORMONEY_V，2026-10-31）。
已存在的表和视图不动；`refresh` 中的先删除（视图为替换）再建。cmx 只读。

补列（`add_columns`，DB-06，2026-10-31）：已存在的表中没有、清单里有的列，按 cmx 的类型和默认值补上（`ALTER TABLE … ADD`），
再按主键从 cmx 取这些列的值（`MERGE`，只更新 d_cg 和 cmx 都有的行；d_cg 新增的行为列默认值或空）；已有的列和行不动，
序列不动。用于已在 d_cg 维护、不能删表重建的表，例如 T_COST_GOODS：物料清单在 d_cg 改过单价，产品信息维护要用到
ZX_CUSTOMERID 等列。补上的列排在原有列之后。
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
    parent: tuple[str, str] | None = None
    """（主表名，本表中关联主表主键的列）。"""


@dataclass(frozen=True)
class ViewSpec:
    sql: str
    reads_cmx: bool = False
    """为 true 时视图直接读 cmx 的视图（清单中的 `readsCmx`），见文件说明。"""


def table_specs() -> dict[str, TableSpec | ViewSpec]:
    data = json.loads(TABLE_SPECS.read_text(encoding="utf-8"))
    specs: dict[str, TableSpec | ViewSpec] = {}
    for name, spec in data.items():
        if spec.get("kind") == "view":
            specs[name.upper()] = ViewSpec(spec["sql"], bool(spec.get("readsCmx", False)))
            continue
        parent = spec.get("parent")
        specs[name.upper()] = TableSpec(
            tuple(c.upper() for c in spec["columns"]), bool(spec.get("excludeDeleted", False)),
            (parent["table"].upper(), parent["column"].upper()) if parent else None)
    return specs


def _exists(conn: Connection, view: str, column: str, name: str) -> bool:
    sql = f"SELECT COUNT(*) FROM {view} WHERE {column} = :n"
    return bool(conn.execute(text(sql), {"n": name}).scalar())


def _primary_key(conn: Connection, table: str) -> tuple[str, list[str]]:
    pk = conn.execute(text(
        "SELECT c.constraint_name, cc.column_name FROM all_constraints c "
        "JOIN all_cons_columns cc ON cc.owner = c.owner AND cc.constraint_name = c.constraint_name "
        "WHERE c.owner = 'CMX' AND c.table_name = :t AND c.constraint_type = 'P' ORDER BY cc.position"), {"t": table}).all()
    return pk[0][0], [row[1] for row in pk]


def _where(conn: Connection, spec: TableSpec, specs: Mapping[str, TableSpec | ViewSpec]) -> str:
    conditions = ["NVL(DELETED, 0) = 0"] if spec.exclude_deleted else []
    if spec.parent:
        parent_table, column = spec.parent
        parent_spec = specs[parent_table]
        assert isinstance(parent_spec, TableSpec)
        _, parent_pk = _primary_key(conn, parent_table)
        live = " WHERE NVL(DELETED, 0) = 0" if parent_spec.exclude_deleted else ""
        conditions.append(f"{column} IN (SELECT {parent_pk[0]} FROM CMX.{parent_table}{live})")
    return f" WHERE {' AND '.join(conditions)}" if conditions else ""


def _copy(conn: Connection, table: str, spec: TableSpec, specs: Mapping[str, TableSpec | ViewSpec]) -> str:
    source = conn.execute(text(
        "SELECT column_name, virtual_column, data_default FROM all_tab_cols "
        "WHERE owner = 'CMX' AND table_name = :t AND hidden_column = 'NO' ORDER BY column_id"), {"t": table}).all()
    missing = sorted(set(spec.columns) - {c[0] for c in source})
    if missing:
        raise ValueError(f"{table} 在 cmx 中没有这些列：{', '.join(missing)}")
    wanted = set(spec.columns)
    columns = [c for c in source if c[0] in wanted]
    where = _where(conn, spec, specs)
    # CTAS 选出的虚拟列在新表中是普通列，值为 cmx 当前算出的结果
    conn.exec_driver_sql(f"CREATE TABLE {table} AS SELECT {', '.join(c[0] for c in columns)} FROM CMX.{table}{where}")
    for column, virtual, default in columns:
        expression = str(default).strip() if default is not None else ""
        # 虚拟列的表达式不作为默认值；cmx 标识列的默认值取 cmx 自己的序列，平台新增行的主键取 <表名>_SEQ（WP-09）
        if virtual == "NO" and expression and "NEXTVAL" not in expression.upper():
            conn.exec_driver_sql(f"ALTER TABLE {table} MODIFY ({column} DEFAULT {expression})")
    comments = conn.execute(text(
        "SELECT column_name, comments FROM all_col_comments WHERE owner = 'CMX' AND table_name = :t AND comments IS NOT NULL"),
        {"t": table}).all()
    kept_comments = [(column, str(comment)) for column, comment in comments if column in wanted]
    for column, comment in kept_comments:
        conn.exec_driver_sql(f"COMMENT ON COLUMN {table}.{column} IS '{comment.replace(chr(39), chr(39) * 2)}'")
    pk_name, pk_columns = _primary_key(conn, table)
    if pk_name.startswith("SYS_"):  # 系统生成的约束名不照搬
        pk_name = f"PK_{table}"
    conn.exec_driver_sql(f"ALTER TABLE {table} ADD CONSTRAINT {pk_name} PRIMARY KEY ({', '.join(pk_columns)})")
    rows = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    sequence = f"{table}_SEQ"
    if _exists(conn, "user_sequences", "sequence_name", sequence):
        conn.exec_driver_sql(f"DROP SEQUENCE {sequence}")
    # 序列从 cmx 的最大主键加一开始（含已删除的行），不重用旧主键
    max_key = conn.execute(text(f"SELECT NVL(MAX({pk_columns[0]}), 0) FROM CMX.{table}")).scalar()
    conn.exec_driver_sql(f"CREATE SEQUENCE {sequence} START WITH {int(max_key) + 1} NOCACHE")
    virtual_count = sum(1 for c in columns if c[1] == "YES")
    return (f"{table}: 复制 {rows} 行、{len(columns)} 列（cmx 共 {len(source)} 列，其中 {virtual_count} 个虚拟列改为普通列），"
            f"列注释 {len(kept_comments)} 个，主键 {pk_name}({', '.join(pk_columns)})，序列 {sequence} 从 {int(max_key) + 1} 开始")


_TEXT_TYPES = {"VARCHAR2", "CHAR"}
_NATIONAL_TYPES = {"NVARCHAR2", "NCHAR"}


def _column_type(data_type: str, precision: object, scale: object, char_used: object, char_length: object) -> str:
    """cmx 列的类型写法（补列用）：字符列按字节或字符的长度，数值列按精度和小数位，日期和时间戳原样。"""
    if data_type in _TEXT_TYPES:
        return f"{data_type}({int(str(char_length))} {'CHAR' if char_used == 'C' else 'BYTE'})"
    if data_type in _NATIONAL_TYPES:
        return f"{data_type}({int(str(char_length))})"
    if data_type == "NUMBER":
        if precision is None:
            return "NUMBER" if scale is None else f"NUMBER(*, {int(str(scale))})"
        return f"NUMBER({int(str(precision))}, {int(str(scale or 0))})"
    if data_type == "FLOAT":
        return f"FLOAT({int(str(precision))})" if precision is not None else "FLOAT"
    if data_type == "DATE" or data_type.startswith("TIMESTAMP"):
        return data_type
    raise ValueError(f"补列不支持的类型：{data_type}")


def _add_columns(conn: Connection, table: str, spec: TableSpec) -> str:
    """已存在的表补上清单中有、表中没有的列（见文件说明）。"""
    present = {r[0] for r in conn.execute(text(
        "SELECT column_name FROM user_tab_cols WHERE table_name = :t AND hidden_column = 'NO'"), {"t": table})}
    source = conn.execute(text(
        "SELECT column_name, data_type, data_precision, data_scale, char_used, char_length, virtual_column, data_default "
        "FROM all_tab_cols WHERE owner = 'CMX' AND table_name = :t AND hidden_column = 'NO' ORDER BY column_id"),
        {"t": table}).all()
    missing = sorted(set(spec.columns) - {c[0] for c in source})
    if missing:
        raise ValueError(f"{table} 在 cmx 中没有这些列：{', '.join(missing)}")
    adding = [c for c in source if c[0] in set(spec.columns) and c[0] not in present]
    if not adding:
        return f"{table}: 已存在，没有要补的列，未改动"
    for column, data_type, precision, scale, char_used, char_length, virtual, default in adding:
        expression = str(default).strip() if default is not None else ""
        clause = f" DEFAULT {expression}" if virtual == "NO" and expression and "NEXTVAL" not in expression.upper() else ""
        conn.exec_driver_sql(
            f"ALTER TABLE {table} ADD ({column} {_column_type(data_type, precision, scale, char_used, char_length)}{clause})")
    names = [c[0] for c in adding]
    _, pk_columns = _primary_key(conn, table)
    on = " AND ".join(f"t.{k} = s.{k}" for k in pk_columns)
    merged = conn.execute(text(
        f"MERGE INTO {table} t USING (SELECT {', '.join([*pk_columns, *names])} FROM CMX.{table}) s ON ({on}) "
        f"WHEN MATCHED THEN UPDATE SET {', '.join(f't.{n} = s.{n}' for n in names)}")).rowcount
    conn.commit()
    comments = conn.execute(text(
        "SELECT column_name, comments FROM all_col_comments WHERE owner = 'CMX' AND table_name = :t AND comments IS NOT NULL"),
        {"t": table}).all()
    for column, comment in comments:
        if column in names:
            conn.exec_driver_sql(f"COMMENT ON COLUMN {table}.{column} IS '{str(comment).replace(chr(39), chr(39) * 2)}'")
    rows = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    return (f"{table}: 补上 {len(names)} 列（{', '.join(names)}），按主键从 cmx 取值 {merged} 行，表共 {rows} 行；"
            f"已有的列、行和序列未改动")


def _create_view(conn: Connection, view: str, spec: ViewSpec) -> str:
    conn.exec_driver_sql(f"CREATE OR REPLACE VIEW {view} AS {spec.sql}")
    columns = conn.execute(text("SELECT COUNT(*) FROM user_tab_cols WHERE table_name = :t"), {"t": view}).scalar()
    rows = conn.execute(text(f"SELECT COUNT(*) FROM {view}")).scalar()
    return f"{view}: 视图已建，{columns} 列，{rows} 行"


def copy_business_tables(engine: Engine, specs: Mapping[str, TableSpec | ViewSpec], refresh: Iterable[str] = (),
                         add_columns: Iterable[str] = ()) -> list[str]:
    """按清单的顺序处理（视图写在它引用的表之后），返回每项的处理结果。`add_columns` 中已存在的表补列（见文件说明）。"""
    refresh_set = {t.upper() for t in refresh}
    add_set = {t.upper() for t in add_columns}
    unknown = sorted(add_set - {n for n, s in specs.items() if isinstance(s, TableSpec)})
    if unknown or add_set & refresh_set:
        raise ValueError(f"补列只用于清单中的表，且不能同时 refresh：{', '.join(unknown or sorted(add_set & refresh_set))}")
    report: list[str] = []
    with engine.connect() as conn:
        for name, spec in specs.items():
            if not _NAME.fullmatch(name) or name.startswith(("BP_T09_", "PF_")):
                raise ValueError(f"不能复制的对象名：{name}")
            if isinstance(spec, ViewSpec):
                if _exists(conn, "user_views", "view_name", name) and name not in refresh_set:
                    report.append(f"{name}: 已存在，未改动")
                else:
                    report.append(_create_view(conn, name, spec))
                continue
            if _exists(conn, "user_tables", "table_name", name):
                if name in add_set:
                    report.append(_add_columns(conn, name, spec))
                    continue
                if name not in refresh_set:
                    report.append(f"{name}: 已存在，未改动")
                    continue
                conn.exec_driver_sql(f"DROP TABLE {name} PURGE")
            report.append(_copy(conn, name, spec, specs))
    return report
