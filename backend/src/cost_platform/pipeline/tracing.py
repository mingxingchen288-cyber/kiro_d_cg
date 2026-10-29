"""SQL 追踪（T-WP-4 的 SQL 条数、WP-17 的命令审查）。

挂在 SQLAlchemy 引擎的游标事件上，只记录 `capture()` 期间、同一上下文（线程或协程）中经 SQLAlchemy 执行的语句：
每条语句的文本、绑定值、耗时、影响行数和错误，与旧系统的操作日志（`OperationLogContext.SqlDetail`）对应。

计数口径：一次 `execute` 或 `executemany` 计 1 条；提交、回滚和连接池探活（不经过游标事件）不计。
影响行数取驱动的 `rowcount`，只对 INSERT、UPDATE、DELETE、MERGE 给出；查询为空：游标事件发生时查询结果还没有取完，
旧系统记的"返回行数"这里不记。
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, event

from cost_platform.contracts.decimal_text import format_decimal
from cost_platform.contracts.types import SqlTrace

_DML = ("INSERT", "UPDATE", "DELETE", "MERGE")


def json_value(value: Any) -> Any:
    """绑定值写成 JSON 能表示的值：数值为十进制文本（C01），日期时间到秒。"""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return format_decimal(value) if value.is_finite() else str(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return f"<{type(value).__name__}>"  # 例如 RETURNING 的输出变量


def _binds(parameters: Any, executemany: bool) -> dict[str, Any]:
    def one(params: Any) -> dict[str, Any]:
        if isinstance(params, Mapping):
            return {str(k): json_value(v) for k, v in params.items()}
        if isinstance(params, Sequence) and not isinstance(params, (str, bytes)):
            return {str(i + 1): json_value(v) for i, v in enumerate(params)}
        return {}
    if executemany:
        return {"rows": [one(p) for p in parameters]}
    return one(parameters)


@dataclass
class TracedStatement:
    text: str
    binds: dict[str, Any]
    started: float
    ms: float = 0.0
    rows: int | None = None
    error: str | None = None

    def to_wire(self) -> SqlTrace:
        return SqlTrace(text=self.text, binds=self.binds, ms=self.ms, rows=self.rows, error=self.error)


@dataclass
class Trace:
    """一次 `capture()` 记下的语句。"""

    statements: list[TracedStatement] = field(default_factory=list)
    _open: dict[int, TracedStatement] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.statements)

    @property
    def total_ms(self) -> float:
        return round(sum(s.ms for s in self.statements), 3)

    @property
    def texts(self) -> list[str]:
        return [s.text for s in self.statements]

    def to_wire(self) -> list[SqlTrace]:
        return [s.to_wire() for s in self.statements]


class SqlTracer:
    def __init__(self) -> None:
        self._current: ContextVar[Trace | None] = ContextVar(f"sql_trace_{id(self)}", default=None)
        self._engines: set[int] = set()

    def install(self, engine: Engine) -> None:
        """在引擎上挂事件；同一引擎只挂一次。"""
        if id(engine) in self._engines:
            return
        self._engines.add(id(engine))
        event.listen(engine, "before_cursor_execute", self._before)
        event.listen(engine, "after_cursor_execute", self._after)
        event.listen(engine, "handle_error", self._error)

    @contextmanager
    def capture(self) -> Iterator[Trace]:
        trace = Trace()
        token = self._current.set(trace)
        try:
            yield trace
        finally:
            self._current.reset(token)

    def _before(self, conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        trace = self._current.get()
        if trace is None:
            return
        entry = TracedStatement(text=" ".join(statement.split()), binds=_binds(parameters, executemany),
                                started=time.perf_counter())
        trace.statements.append(entry)
        trace._open[id(cursor)] = entry

    def _after(self, conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        trace = self._current.get()
        entry = trace._open.pop(id(cursor), None) if trace is not None else None
        if entry is None:
            return
        entry.ms = round((time.perf_counter() - entry.started) * 1000, 3)
        if entry.text.lstrip().upper().startswith(_DML):
            rowcount = getattr(cursor, "rowcount", None)
            entry.rows = rowcount if isinstance(rowcount, int) and rowcount >= 0 else None

    def _error(self, context: Any) -> None:
        trace = self._current.get()
        cursor = getattr(context.execution_context, "cursor", None)
        entry = trace._open.pop(id(cursor), None) if trace is not None and cursor is not None else None
        if entry is None:
            return
        entry.ms = round((time.perf_counter() - entry.started) * 1000, 3)
        entry.error = str(context.original_exception).splitlines()[0][:2000]
