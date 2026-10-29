"""审批流 SQL 片段的包装、参数和执行（C06 7.2）。

入口条件、冻结和展示数据的关联条件、通过后操作的取值，在配置中只写条件或表达式本身；这里把它们包成完整的查询，
参数用绑定变量，经 `UnitOfWork` 在命令事务中只读执行（C08 第 13 节）：

| 写的是 | 执行的语句 |
|---|---|
| 入口条件 | `SELECT 1 FROM DUAL WHERE (<条件>)`，查到一行即成立 |
| 冻结的关联条件 | `SELECT <冻结表的主键> FROM <冻结表> WHERE (<条件>)`；冻结表是注册过的明细表时，另取关联主表的列 |
| 展示数据的关联条件 | `SELECT * FROM <展示表或视图> WHERE (<条件>)` |
| 取值 | `SELECT (<表达式>) AS V FROM DUAL`，取第一行第一列 |

参数（片段中写 `:名称`）：`:new_字段`、`:old_字段`、`:master_new_字段`、`:master_old_字段`、`:operation`、`:billId`、
`:user_id`、`:user_departmentId`，取值另有 `:row_列名`、`:params_名称`。只绑定语句中出现的参数；字段不存在时绑定空值。

对照旧系统 `ApprovalConditionEvaluator.prepareQuery`：非 SELECT 的片段包成 `SELECT CASE WHEN (...) THEN 1 ELSE 0 END FROM DUAL`，
参数为 `old_X`、`new_X`、`user_X`、`row_X` 等；新平台按 C06 7.2 的写法。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from sqlalchemy import text

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import RowOp, Value

_STRING = re.compile(r"'(?:''|[^'])*'")
_PARAM = re.compile(r"(?<![\w:]):([A-Za-z_][A-Za-z0-9_$#]*)")

OPERATIONS: dict[str, str] = {"add": "added", "modify": "modified", "delete": "deleted"}
"""`:operation` 的取值（C06 7.2）。"""


def params_in(sql: str) -> list[str]:
    """语句中出现的绑定变量名，按出现顺序；字符串常量中的冒号不算。"""
    return list(dict.fromkeys(_PARAM.findall(_STRING.sub("''", sql))))


def entry_sql(condition: str) -> str:
    return f"SELECT 1 FROM DUAL WHERE ({condition})"


def freeze_sql(table: str, columns: Sequence[str], condition: str) -> str:
    return f"SELECT {', '.join(columns)} FROM {table} WHERE ({condition})"


def display_sql(source: str, condition: str) -> str:
    return f"SELECT * FROM {source} WHERE ({condition})"


def value_sql(expression: str) -> str:
    return f"SELECT ({expression}) AS V FROM DUAL"


def keys_sql(source: str, column: str, keys: Sequence[str], columns: Sequence[str] = ("*",)) -> tuple[str, dict[str, object]]:
    """按主键读出行：`SELECT * FROM <表或视图> WHERE <列> IN (:k0, :k1, …)`。"""
    names = [f"k{i}" for i in range(len(keys))]
    statement = f"SELECT {', '.join(columns)} FROM {source} WHERE {column} IN ({', '.join(':' + n for n in names)})"
    return statement, dict(zip(names, keys, strict=True))


def key_text(value: object) -> str:
    """主键值转成文本：Decimal 2550、整数 2550、"2550" 都是 "2550"。"""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value == value.to_integral_value() else format(value, "f")
    return str(value)


def _get(values: Mapping[str, Value], name: str) -> Value:
    if name in values:
        return values[name]
    lowered = name.upper()
    for key, value in values.items():
        if key.upper() == lowered:
            return value
    return None


@dataclass(frozen=True)
class RowScope:
    """片段中"本行"的参数来源（C06 7.2）：入口条件中是正在判断的那一行；冻结、展示数据的关联条件和取值中，是找到这条
    记录的那个触发本审批的行。`row` 只用于取值（修改表这一行的当前值），`params` 只用于取值（审批流参数）。"""

    op: RowOp
    new: Mapping[str, Value]
    old: Mapping[str, Value]
    master_new: Mapping[str, Value]
    master_old: Mapping[str, Value]
    bill_id: Value
    user_id: str
    user_department_id: str | None
    row: Mapping[str, Value] = field(default_factory=dict)
    params: Mapping[str, Value] = field(default_factory=dict)

    def value(self, name: str) -> Value:
        if name == "operation":
            return OPERATIONS[self.op]
        if name == "billId":
            return self.bill_id
        if name == "user_id":
            return self.user_id
        if name == "user_departmentId":
            return self.user_department_id
        for prefix, source in (("master_new_", self.master_new), ("master_old_", self.master_old), ("new_", self.new),
                               ("old_", self.old), ("row_", self.row), ("params_", self.params)):
            if name.startswith(prefix):
                return _get(source, name[len(prefix):])
        return None

    def with_row(self, row: Mapping[str, Value], params: Mapping[str, Value]) -> RowScope:
        return RowScope(self.op, self.new, self.old, self.master_new, self.master_old, self.bill_id, self.user_id,
                        self.user_department_id, row, params)


def db_value(value: Value) -> object:
    """绑定到数据库的值：是非为 1/0（C01），其余原样。"""
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def binds_for(statement: str, scope: RowScope | None, extra: Mapping[str, object] | None = None) -> dict[str, object]:
    """语句中出现的每个参数的值：`extra` 优先，其余按 `scope` 取。"""
    binds: dict[str, object] = {}
    for name in params_in(statement):
        if extra is not None and name in extra:
            binds[name] = extra[name]
        else:
            binds[name] = db_value(scope.value(name)) if scope is not None else None
    return binds


class SqlRunner(Protocol):
    """执行一条只读语句，返回各行（列名为大写）。真实实现为 `UowSqlRunner`。"""

    def rows(self, uow: UnitOfWork, statement: str, binds: Mapping[str, object]) -> list[dict[str, object]]: ...


def _read(value: object) -> object:
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    return value


class UowSqlRunner:
    """经 `UnitOfWork` 的连接执行（db-core 的数值列读出为 Decimal 或整数，这里整数也转为 Decimal）。"""

    def rows(self, uow: UnitOfWork, statement: str, binds: Mapping[str, object]) -> list[dict[str, object]]:
        result = uow.connection.execute(text(statement), dict(binds))
        return [{str(k).upper(): _read(v) for k, v in m.items()} for m in result.mappings()]


class KeyAllocator(Protocol):
    """新增行的主键取序列 `<表名>_SEQ`（C06 第 2 节，AP-02）。"""

    def next_key(self, uow: UnitOfWork, table: str) -> str: ...


class SequenceKeys:
    def next_key(self, uow: UnitOfWork, table: str) -> str:
        value = uow.connection.execute(text(f"SELECT {table}_SEQ.NEXTVAL FROM DUAL")).scalar_one()
        return key_text(value)


def exists(runner: SqlRunner, uow: UnitOfWork, condition: str, scope: RowScope) -> bool:
    """入口条件对这一行是否成立。"""
    statement = entry_sql(condition)
    return bool(runner.rows(uow, statement, binds_for(statement, scope)))


def scalar(runner: SqlRunner, uow: UnitOfWork, expression: str, scope: RowScope) -> object:
    """取值：第一行第一列；没有行时为空。"""
    statement = value_sql(expression)
    rows = runner.rows(uow, statement, binds_for(statement, scope))
    if not rows:
        return None
    return next(iter(rows[0].values()), None)
