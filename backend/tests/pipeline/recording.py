"""记录 SQL 的连接：按 Oracle 方言编译收到的语句，记下文本和绑定变量，按顺序返回预设的查询结果。

用来核对 `OracleDocumentStore`、`OracleTableWriter` 生成的语句（写哪些列、几条语句），不连数据库；
语句在 Oracle 上的执行由 oracle 测试验证。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.dialects import oracle

_DIALECT = oracle.dialect()


@dataclass
class Statement:
    sql: str
    params: Any


class _Driver:
    call_timeout = 0


class _Pooled:
    driver_connection = _Driver()


class Result(list):  # type: ignore[type-arg]
    """查询结果：可以遍历，也支持 `first()`、`mappings().first()`（预设的行为字典时）。"""

    def first(self) -> Any:
        return self[0] if self else None

    def mappings(self) -> Result:
        return self


@dataclass
class RecordingConnection:
    results: list[Sequence[Any]] = field(default_factory=list)
    statements: list[Statement] = field(default_factory=list)
    connection: _Pooled = field(default_factory=_Pooled)

    def execute(self, statement: Any, params: Any = None) -> Result:
        first = params[0] if isinstance(params, list) and params else params
        keys = list(first) if isinstance(first, dict) else None
        compiled = statement.compile(dialect=_DIALECT, column_keys=keys) if keys else statement.compile(dialect=_DIALECT)
        sql = " ".join(str(compiled).split())
        self.statements.append(Statement(sql, params))
        if sql.startswith("SELECT") or " RETURNING " in sql:
            return Result(self.results.pop(0) if self.results else [])
        return Result()

    @property
    def sql(self) -> list[str]:
        return [s.sql for s in self.statements]


@dataclass(eq=False)
class RecordingUnitOfWork:
    connection: RecordingConnection = field(default_factory=RecordingConnection)

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
