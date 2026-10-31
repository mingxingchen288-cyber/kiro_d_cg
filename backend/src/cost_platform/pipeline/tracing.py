"""SQL 追踪（T-WP-4 的 SQL 条数、WP-17 的命令审查）。

创建时挂在 SQLAlchemy `Engine` 类的游标事件上，对所有引擎（包括 db-core 创建的、之后创建的）生效，所以不需要拿到
引擎。只记录 `capture()` 期间、同一上下文（线程或协程，`contextvars`）中经 SQLAlchemy 执行的语句：每条语句的文本、
绑定值、耗时、影响行数和错误，与旧系统的操作日志（`OperationLogContext.SqlDetail`）对应。命令在线程池中执行时，
`capture()` 和执行在同一个线程里，照样记得到；别的线程、协程同时执行的语句不记。

计数口径：一次 `execute` 或 `executemany` 计 1 条；提交、回滚和连接池探活（不经过游标事件）不计。
行数：INSERT、UPDATE、DELETE、MERGE 取驱动的 `rowcount`（影响行数）；返回结果的语句（查询，含加锁读取）为取出的行数
（WP-23，同旧系统 SQL 追踪的返回行数）。游标事件发生时查询结果还没有取，所以在这时把这条语句的取数方式换成会计数的包装
（`_Counted`，委托给原来的取数方式），调用方取结果时累加，不多发 SQL；结果一行都没取的语句（例如只加锁、不读结果）为空。
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
from sqlalchemy.engine.cursor import BufferedRowCursorFetchStrategy, CursorFetchStrategy, ResultFetchStrategy

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


class _Counted(ResultFetchStrategy):
    """查询结果的取数方式的包装（WP-23）：照原来的方式取，数取出的行，记到这条语句上。

    SQLAlchemy 在游标事件之后用执行上下文的 `cursor_fetch_strategy` 建结果对象；原来是默认方式、且要分批取
    （`yield_per`、`stream_results`）时，SQLAlchemy 会换成分批的方式，这里先换好再包上，取数的方式不变。
    `yield_per` 会换掉取数方式，换完再包一层。取完后 SQLAlchemy 换成"没有游标"的方式，不再经过这里。"""

    __slots__ = ("_inner", "_entry")

    def __init__(self, inner: ResultFetchStrategy, entry: TracedStatement) -> None:
        self._inner = inner
        self._entry = entry

    @property  # type: ignore[override]
    def alternate_cursor_description(self) -> Any:
        return self._inner.alternate_cursor_description

    def _add(self, count: int) -> None:
        self._entry.rows = (self._entry.rows or 0) + count

    def soft_close(self, result: Any, dbapi_cursor: Any) -> None:
        self._inner.soft_close(result, dbapi_cursor)

    def hard_close(self, result: Any, dbapi_cursor: Any) -> None:
        self._inner.hard_close(result, dbapi_cursor)

    def handle_exception(self, result: Any, dbapi_cursor: Any, err: BaseException) -> Any:
        return self._inner.handle_exception(result, dbapi_cursor, err)

    def yield_per(self, result: Any, dbapi_cursor: Any, num: int) -> None:
        result.cursor_strategy = self._inner
        self._inner.yield_per(result, dbapi_cursor, num)
        result.cursor_strategy = _Counted(result.cursor_strategy, self._entry)

    def fetchone(self, result: Any, dbapi_cursor: Any, hard_close: bool = False) -> Any:
        row = self._inner.fetchone(result, dbapi_cursor, hard_close)
        self._add(0 if row is None else 1)
        return row

    def fetchmany(self, result: Any, dbapi_cursor: Any, size: int | None = None) -> Any:
        rows = self._inner.fetchmany(result, dbapi_cursor, size)
        self._add(len(rows))
        return rows

    def fetchall(self, result: Any, dbapi_cursor: Any) -> Any:
        rows = self._inner.fetchall(result, dbapi_cursor)
        self._add(len(rows))
        return rows


def _count_rows(context: Any, cursor: Any, entry: TracedStatement) -> None:
    """返回结果的语句（游标有列说明）：把执行上下文的取数方式换成 `_Counted`。"""
    inner = getattr(context, "cursor_fetch_strategy", None)
    if inner is None or getattr(cursor, "description", None) is None:
        return
    # 与 SQLAlchemy 建结果对象时相同（DefaultExecutionContext._setup_result_proxy）：服务端游标，或者编译出的查询
    # 带 stream_results 时分批取
    plain = bool(getattr(context, "is_crud", False) or getattr(context, "is_text", False))
    batched = getattr(context, "_is_server_side", False) or (
        not plain and bool(context.execution_options.get("stream_results", False)))
    if type(inner) is CursorFetchStrategy and batched:
        inner = BufferedRowCursorFetchStrategy(cursor, context.execution_options)
    context.cursor_fetch_strategy = _Counted(inner, entry)


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
        """在 `Engine` 类上挂事件（每个实例挂一次，进程中通常只有命令审查的一个）。"""
        self._current: ContextVar[Trace | None] = ContextVar(f"sql_trace_{id(self)}", default=None)
        event.listen(Engine, "before_cursor_execute", self._before)
        event.listen(Engine, "after_cursor_execute", self._after)
        event.listen(Engine, "handle_error", self._error)

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
        elif not executemany:
            _count_rows(context, cursor, entry)

    def _error(self, context: Any) -> None:
        trace = self._current.get()
        cursor = getattr(context.execution_context, "cursor", None)
        entry = trace._open.pop(id(cursor), None) if trace is not None and cursor is not None else None
        if entry is None:
            return
        entry.ms = round((time.perf_counter() - entry.started) * 1000, 3)
        entry.error = str(context.original_exception).splitlines()[0][:2000]
