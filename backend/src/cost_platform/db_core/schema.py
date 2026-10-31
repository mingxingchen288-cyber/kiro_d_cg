"""表结构读取：`SchemaInspector` 的 Oracle 实现（C08 第 2 节）。

读 d_cg 当前用户的数据字典（USER_TAB_COLUMNS、USER_OBJECTS、USER_CONSTRAINTS、USER_SEQUENCES、USER_COL_COMMENTS），
每次调用从连接池取一个连接，读完归还；不缓存，建表、改表后马上能读到（需要缓存的调用方自己缓存，例如
write-pipeline 的 `ColumnScales`）。名称按 Oracle 不加引号的写法转为大写。

对照旧系统：`metadata/service/MetaConfigService.listViewColumns`（DBA_TAB_COLUMNS + DBA_COL_COMMENTS 读列名、类型、
长度、精度、小数位和注释）、`listDbObjects`（DBA_OBJECTS 按关键字列出表和视图，最多 100 个）、
`WizardGenerateService.getPkColumn`（主键约束的列）、`ensureSequenceExists`（USER_SEQUENCES）。

- `column_comments`、`objects`（C08 v21，DB-07）：新建页面向导的列标题取列注释，没有注释时取列名；按关键字搜表和视图。
- `view_sources`（C08 v22，DB-08）：视图直接读取的表、视图和同义词（USER_DEPENDENCIES），write-pipeline 判断读取视图
  是否只读实体自己的表（WP-03）。
- `sequence_exists`：C08 没有（`.reports/modules/db-core/contract-gaps.md`），config 检查 `<表名>_SEQ` 已存在
  （C06 第 10 节、CF-14、C09 wizard/columns 的 `sequence.exists`）。
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import Engine, text

from cost_platform.contracts.types import ColumnInfo, DbObject

_CHARACTER = {"VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR"}
_NUMERIC = {"NUMBER", "FLOAT"}

_COLUMNS = text("SELECT column_name, data_type, nullable, char_length, data_precision, data_scale FROM user_tab_columns "
                "WHERE table_name = :b_name ORDER BY column_id")
_OBJECT = text("SELECT object_type FROM user_objects WHERE object_name = :b_name AND object_type IN ('TABLE', 'VIEW')")
_PRIMARY_KEY = text("SELECT cc.column_name FROM user_constraints c "
                    "JOIN user_cons_columns cc ON cc.constraint_name = c.constraint_name "
                    "JOIN user_tables t ON t.table_name = c.table_name "
                    "WHERE c.table_name = :b_name AND c.constraint_type = 'P' ORDER BY cc.position")
_SEQUENCE = text("SELECT COUNT(*) FROM user_sequences WHERE sequence_name = :b_name")
_COMMENTS = text("SELECT c.column_name, m.comments FROM user_tab_columns c "
                 "LEFT JOIN user_col_comments m ON m.table_name = c.table_name AND m.column_name = c.column_name "
                 "WHERE c.table_name = :b_name ORDER BY c.column_id")
# 视图直接读取的对象（C08 v22）：USER_DEPENDENCIES 中视图依赖的表、视图、同义词，函数、包、类型、序列不算；视图存在、
# 一个依赖都没有时为一行空值。当前用户的只写名称，别的用户写"用户.名称"，经数据库链接的加"@链接名"。
_VIEW_SOURCES = text(
    "SELECT CASE WHEN d.referenced_name IS NULL THEN NULL "
    "WHEN d.referenced_owner = USER THEN d.referenced_name ELSE d.referenced_owner || '.' || d.referenced_name END "
    "|| CASE WHEN d.referenced_link_name IS NOT NULL THEN '@' || d.referenced_link_name END AS source "
    "FROM user_views v LEFT JOIN user_dependencies d ON d.name = v.view_name AND d.type = 'VIEW' "
    "AND d.referenced_type NOT IN ('PACKAGE', 'PACKAGE BODY', 'FUNCTION', 'PROCEDURE', 'TYPE', 'TYPE BODY', 'SEQUENCE', "
    "'OPERATOR', 'LIBRARY', 'JAVA CLASS') "
    "WHERE v.view_name = :b_name ORDER BY 1")
# 同旧系统 listDbObjects：OBJECT_NAME LIKE '%关键字%'（关键字转大写，`_`、`%` 照样是通配符），先表后视图，最多 100 个
_OBJECTS = text("SELECT * FROM (SELECT object_name, object_type FROM user_objects "
                "WHERE object_type IN ('TABLE', 'VIEW') AND object_name LIKE '%' || :b_keyword || '%' "
                "ORDER BY object_type, object_name) WHERE ROWNUM <= 100")


def _column(name: str, data_type: str, nullable: str, char_length: object, precision: object, scale: object) -> ColumnInfo:
    """字符列给出长度（字符数），数值列给出精度和小数位（不带精度的 NUMBER 两者都为 None），其余为 None。"""
    numeric = data_type in _NUMERIC
    return ColumnInfo(name=name, data_type=data_type, nullable=nullable == "Y",
                      length=int(str(char_length)) if data_type in _CHARACTER else None,
                      precision=int(str(precision)) if numeric and precision is not None else None,
                      scale=int(str(scale)) if numeric and scale is not None else None)


class OracleSchemaInspector:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def columns(self, table: str) -> dict[str, ColumnInfo] | None:
        """表或视图的列，按列的顺序，键为列名；不存在时为 None。"""
        with self._engine.connect() as c:
            rows = c.execute(_COLUMNS, {"b_name": table.upper()}).all()
        return {r[0]: _column(*r) for r in rows} if rows else None

    def object_type(self, name: str) -> Literal["table", "view"] | None:
        with self._engine.connect() as c:
            found = c.execute(_OBJECT, {"b_name": name.upper()}).scalar()
        if found is None:
            return None
        return "table" if found == "TABLE" else "view"

    def primary_key(self, table: str) -> str | None:
        """表的单列主键；没有主键、主键多于一列或不是表时为 None。"""
        with self._engine.connect() as c:
            rows = c.execute(_PRIMARY_KEY, {"b_name": table.upper()}).all()
        return str(rows[0][0]) if len(rows) == 1 else None

    def sequence_exists(self, name: str) -> bool:
        with self._engine.connect() as c:
            return bool(c.execute(_SEQUENCE, {"b_name": name.upper()}).scalar_one())

    def column_comments(self, table: str) -> dict[str, str | None] | None:
        """表或视图每一列的注释，按列的顺序，没有注释的为 None；表或视图不存在时为 None。"""
        with self._engine.connect() as c:
            rows = c.execute(_COMMENTS, {"b_name": table.upper()}).all()
        return {r[0]: r[1] for r in rows} if rows else None

    def objects(self, keyword: str) -> list[DbObject]:
        """名称中含关键字的表和视图（当前用户 d_cg 的），最多 100 个，先表后视图、各按名称排列。"""
        with self._engine.connect() as c:
            rows = c.execute(_OBJECTS, {"b_keyword": keyword.strip().upper()}).all()
        return [DbObject(name=str(r[0]), type="table" if r[1] == "TABLE" else "view") for r in rows]

    def view_sources(self, view: str) -> list[str] | None:
        """视图直接读取的表、视图和同义词（USER_DEPENDENCIES），按名称排列；不是视图时为 None。"""
        with self._engine.connect() as c:
            rows = c.execute(_VIEW_SOURCES, {"b_name": view.upper()}).all()
        return [str(r[0]) for r in rows if r[0] is not None] if rows else None
