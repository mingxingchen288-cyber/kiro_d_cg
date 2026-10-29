"""SQL 文本的检查：只能是一条查询、参数、审批流 SQL 片段的包装（C06 7.2），以及交给数据库解析（C06 第 10 节）。

交给数据库解析时执行 `SELECT * FROM (<语句>) q_ WHERE 1 = 0`，参数全部绑 NULL：数据库照常解析语句、核对表和列，
但不返回数据。经调用方的 UnitOfWork 执行（只读语句，不加锁）。解析失败的原因转成中文，不带 ORA- 文本（C03 第 1 节）。
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, StatementError

from cost_platform.contracts.ports import UnitOfWork

_STRING = re.compile(r"'(?:[^']|'')*'")
_QUOTED = re.compile(r'"(?:[^"]|"")*"')
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_PARAM = re.compile(r"(?<![:\w]):([A-Za-z_][A-Za-z0-9_]*)")
_WRITE_WORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE|CALL|BEGIN|DECLARE|COMMIT|"
    r"ROLLBACK|LOCK|RENAME|COMMENT)\b", re.I)
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_$#]*")


class SqlProblem(Exception):
    """数据库不能解析这段 SQL；`message` 是给管理员看的中文说明。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def strip_literals(sql: str) -> str:
    """去掉注释，把字符串和带引号的标识符换成占位，便于查找分号、关键字和参数。"""
    sql = _BLOCK_COMMENT.sub(" ", sql)
    sql = _STRING.sub("''", sql)
    sql = _QUOTED.sub('"x"', sql)
    return _LINE_COMMENT.sub(" ", sql)


def parameters(sql: str) -> list[str]:
    """SQL 中的绑定变量名（`:名称`），按出现顺序去重。"""
    seen: dict[str, None] = {}
    for name in _PARAM.findall(strip_literals(sql)):
        seen.setdefault(name, None)
    return list(seen)


def has_semicolon(sql: str) -> bool:
    return ";" in strip_literals(sql)


def is_single_query(sql: str) -> bool:
    """只能是一条查询语句：以 SELECT 或 WITH 开头，没有分号，不含数据修改语句的关键字。"""
    body = strip_literals(sql).strip()
    first = body.split(None, 1)[0].upper() if body else ""
    return first in ("SELECT", "WITH") and ";" not in body and not _WRITE_WORDS.search(body)


def is_condition(sql: str) -> bool:
    """行权限的 SQL 条件（C06 第 8 节）：只能是一个条件表达式，不能含分号和数据修改语句。"""
    body = strip_literals(sql)
    return bool(body.strip()) and ";" not in body and not _WRITE_WORDS.search(body)


def is_identifier(value: str) -> bool:
    """表名或视图名（不是查询语句）。"""
    return bool(_IDENTIFIER.fullmatch(value.strip()))


# ---------------------------------------------------------------- C06 7.2 的包装

def wrap_entry(condition: str) -> str:
    """入口条件：查到一行即成立。"""
    return f"SELECT 1 FROM DUAL WHERE ({condition})"


def wrap_freeze(table: str, key_column: str, condition: str) -> str:
    """冻结的关联条件。"""
    return f"SELECT {key_column} FROM {table} WHERE ({condition})"


def wrap_display(source: str, condition: str) -> str:
    """展示数据的关联条件。"""
    return f"SELECT * FROM {source} WHERE ({condition})"


def wrap_value(expression: str) -> str:
    """取值：取第一行第一列。"""
    return f"SELECT ({expression}) FROM DUAL"


# ---------------------------------------------------------------- 交给数据库解析

_SYNTAX = {"00905", "00906", "00907", "00908", "00911", "00917", "00920", "00921", "00923", "00924", "00933", "00936",
           "00969", "01756", "01740"}


def _reason(exc: DBAPIError) -> str:
    raw = str(exc.orig)
    found = re.search(r"ORA-(\d{5})", raw)
    if found:
        code = found.group(1)
        if code == "00904":
            names = re.findall(r'"([^"]+)"', raw)
            return f"列不存在或写法不对：{names[-1]}" if names else "列不存在或写法不对"
        if code in ("00942", "04043"):
            return "表或视图不存在"
        if code in _SYNTAX:
            return "SQL 语法错误"
        if code == "01008":
            return "有参数没有绑定"
        if code in ("00932", "01722", "01858", "01861"):
            return "数据类型不一致"
        return f"数据库不能解析这段 SQL（错误码 {code}）"
    lowered = raw.lower()
    if "no such column" in lowered:
        return f"列不存在或写法不对：{raw.split(':', 1)[-1].strip()}"
    if "no such table" in lowered:
        return "表或视图不存在"
    if "syntax error" in lowered or "incomplete input" in lowered:
        return "SQL 语法错误"
    return "数据库不能解析这段 SQL"


class QueryChecker:
    """把查询语句交给数据库解析，返回结果列名（大写）。"""

    def describe(self, uow: UnitOfWork, sql: str) -> list[str]:
        statement = text(f"SELECT * FROM ({sql}) q_ WHERE 1 = 0")
        # 参数取 SQLAlchemy 自己解析出的绑定变量，全部绑 NULL
        binds = {name: None for name in statement._bindparams}
        try:
            result = uow.connection.execute(statement, binds)
        except DBAPIError as exc:
            raise SqlProblem(_reason(exc)) from None
        except StatementError:
            raise SqlProblem("数据库不能解析这段 SQL") from None
        try:
            return [str(column[0]).upper() for column in result.cursor.description or ()]
        finally:
            result.close()
