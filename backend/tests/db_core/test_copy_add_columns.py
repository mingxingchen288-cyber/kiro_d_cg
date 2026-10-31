"""DB-06：`copy-business-tables --add-columns` 给已存在的表补列（模拟验证，记录生成的 SQL）。

业务例子：d_cg 的物料表 T_COST_GOODS 已有物料清单用的 13 列（物料清单在 d_cg 改过单价，不能删表重建）；产品信息维护要
客户 ID ZX_CUSTOMERID（cmx 为 NUMBER(19,0)）、华益代码 GOODSNO（VARCHAR2(100 BYTE)）、创建人 CREATE_BY。补列只加这三列、
按主键从 cmx 取值，已有的列、行和序列不动。真实执行见 `.reports/batch8-20261031/g1-basic-pages/` 的 copy 日志和前后核对。
"""

from __future__ import annotations

from typing import Any

from cost_platform.db_core.copy_tables import TableSpec, copy_business_tables


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]], rowcount: int = 0) -> None:
        self._rows = rows
        self.rowcount = rowcount

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows

    def __iter__(self) -> Any:
        return iter(self._rows)

    def scalar(self) -> Any:
        return self._rows[0][0] if self._rows else None


class _Connection:
    """按 SQL 开头返回结果；DDL（exec_driver_sql）和提交只记录。"""

    def __init__(self) -> None:
        self.ddl: list[str] = []
        self.sql: list[str] = []
        self.commits = 0

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        sql = str(statement)
        self.sql.append(sql)
        if "FROM user_tables" in sql:
            return _Result([(1,)])
        if "FROM user_tab_cols" in sql:
            return _Result([(c,) for c in ("GOODSID", "GOODSNAME", "ISERP", "UPDATE_BY")])
        if "FROM all_tab_cols" in sql:
            return _Result([
                ("GOODSID", "NUMBER", 19, 0, None, 0, "NO", None),
                ("GOODSNO", "VARCHAR2", None, None, "B", 100, "NO", None),
                ("GOODSNAME", "VARCHAR2", None, None, "B", 1000, "NO", None),
                ("ZX_CUSTOMERID", "NUMBER", 19, 0, None, 0, "NO", None),
                ("ISERP", "NUMBER", 1, 0, None, 0, "NO", "0"),
                ("CREATE_BY", "VARCHAR2", None, None, "B", 320, "NO", None),
                ("UPDATE_BY", "VARCHAR2", None, None, "B", 320, "NO", None),
                ("TARGETMARKET", "VARCHAR2", None, None, "B", 1000, "NO", None),
            ])
        if "FROM all_constraints" in sql:
            return _Result([("SYS_C0025635", "GOODSID")])
        if sql.startswith("MERGE INTO"):
            return _Result([], rowcount=14419)
        if "FROM all_col_comments" in sql:
            return _Result([])
        if sql.startswith("SELECT COUNT(*) FROM T_COST_GOODS"):
            return _Result([(14419,)])
        raise AssertionError(f"没有准备的 SQL：{sql}")

    def exec_driver_sql(self, sql: str) -> None:
        self.ddl.append(sql)

    def commit(self) -> None:
        self.commits += 1


class _Engine:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    def connect(self) -> _Connection:
        return self._connection


def test_add_columns_adds_only_missing_listed_columns_and_fills_them_from_cmx() -> None:
    spec = TableSpec(("GOODSID", "GOODSNO", "GOODSNAME", "ZX_CUSTOMERID", "ISERP", "CREATE_BY", "UPDATE_BY"), True)
    connection = _Connection()
    report = copy_business_tables(_Engine(connection), {"T_COST_GOODS": spec}, add_columns=["T_COST_GOODS"])  # type: ignore[arg-type]
    assert connection.ddl == [
        "ALTER TABLE T_COST_GOODS ADD (GOODSNO VARCHAR2(100 BYTE))",
        "ALTER TABLE T_COST_GOODS ADD (ZX_CUSTOMERID NUMBER(19, 0))",
        "ALTER TABLE T_COST_GOODS ADD (CREATE_BY VARCHAR2(320 BYTE))"]
    [merge] = [s for s in connection.sql if s.startswith("MERGE")]
    assert merge == ("MERGE INTO T_COST_GOODS t USING (SELECT GOODSID, GOODSNO, ZX_CUSTOMERID, CREATE_BY FROM CMX.T_COST_GOODS) s "
                     "ON (t.GOODSID = s.GOODSID) WHEN MATCHED THEN UPDATE SET t.GOODSNO = s.GOODSNO, "
                     "t.ZX_CUSTOMERID = s.ZX_CUSTOMERID, t.CREATE_BY = s.CREATE_BY")
    assert connection.commits == 1
    assert report == ["T_COST_GOODS: 补上 3 列（GOODSNO, ZX_CUSTOMERID, CREATE_BY），按主键从 cmx 取值 14419 行，表共 14419 行；"
                      "已有的列、行和序列未改动"]
