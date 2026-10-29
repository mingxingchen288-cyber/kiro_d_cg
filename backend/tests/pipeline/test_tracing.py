"""SQL 追踪的计数口径（T-WP-4）：一次 execute 或 executemany 计 1 条，提交和回滚不计；记下文本、绑定值、影响行数和错误。

追踪挂在 SQLAlchemy 的 `Engine` 类上，不需要拿到引擎：这里的引擎都在创建 `SqlTracer` 之前就有了。用 contracts 的事务替代
实现（SQLite）验证追踪本身；Oracle 上的条数见 `test_oracle_sql_count.py`。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from cost_platform.contracts.fakes import FakeUnitOfWorkFactory
from cost_platform.pipeline.tracing import SqlTracer, Trace


def test_counts_statements_executemany_once_and_not_commit() -> None:
    factory = FakeUnitOfWorkFactory()
    tracer = SqlTracer()
    with factory.engine.connect() as connection:
        connection.execute(text("CREATE TABLE t_wp (id INTEGER PRIMARY KEY, price NUMBER)"))
        connection.commit()
    with tracer.capture() as trace, factory.begin() as uow:
        uow.connection.execute(text("INSERT INTO t_wp (id, price) VALUES (:id, :price)"),
                               [{"id": 1, "price": Decimal("3.50")}, {"id": 2, "price": Decimal("3.80")}])
        uow.connection.execute(text("UPDATE t_wp SET price = :p WHERE id = :id"), {"p": Decimal("4"), "id": 1})
        uow.connection.execute(text("SELECT price FROM t_wp WHERE id = :id"), {"id": 1}).one()
        uow.commit()
    assert trace.count == 3
    insert, update, select = trace.statements
    # SQLite 的绑定变量是位置参数（Oracle 为命名参数，键为变量名）
    assert insert.binds == {"rows": [{"1": 1, "2": "3.50"}, {"1": 2, "2": "3.80"}]}
    assert update.text == "UPDATE t_wp SET price = ? WHERE id = ?" and update.rows == 1
    assert update.binds == {"1": "4", "2": 1}
    assert select.rows is None and select.error is None
    assert trace.total_ms >= 0


def test_failed_statement_recorded_with_error() -> None:
    factory = FakeUnitOfWorkFactory()
    tracer = SqlTracer()
    with tracer.capture() as trace, factory.begin() as uow, pytest.raises(DBAPIError):
        uow.connection.execute(text("SELECT * FROM missing_table"))
    [statement] = trace.statements
    assert statement.error is not None and "missing_table" in statement.error


def test_statements_outside_capture_not_recorded() -> None:
    factory = FakeUnitOfWorkFactory()
    tracer = SqlTracer()
    with factory.begin() as uow:
        uow.connection.execute(text("SELECT 1"))
    with tracer.capture() as trace:
        pass
    assert trace.count == 0


def test_command_in_thread_pool_recorded() -> None:
    """FastAPI 在线程池中执行命令：capture 和执行在同一个线程里，语句照样记下。"""
    factory = FakeUnitOfWorkFactory()
    tracer = SqlTracer()

    def command() -> Trace:
        with tracer.capture() as trace, factory.begin() as uow:
            uow.connection.execute(text("SELECT 1"))
            uow.connection.execute(text("SELECT :a"), {"a": 2})
        return trace

    with ThreadPoolExecutor(max_workers=2) as pool:
        trace = pool.submit(command).result()
    assert trace.texts == ["SELECT 1", "SELECT ?"]
