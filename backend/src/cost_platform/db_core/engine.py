"""Oracle 连接池和 UnitOfWork（DB-01、DB-02）。

SQLAlchemy Core 加 python-oracledb（thin 模式）。数值列读出为 Decimal 或 int（整数），不经过浮点；
每条语句的调用超时为 25 秒（工程约定第 1 节）。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import oracledb
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from cost_platform.contracts.types import ErrorCode, PlatformError

CALL_TIMEOUT_MS = 25_000
_log = logging.getLogger(__name__)

_BUSY = {"ORA-00054", "ORA-00060", "ORA-30006"}
_UNAVAILABLE = {"ORA-03113", "ORA-03114", "ORA-03135", "ORA-12514", "ORA-12541", "ORA-12170", "DPY-4011", "DPY-6005"}


def create_oracle_engine(user: str, password: str, dsn: str) -> Engine:
    oracledb.defaults.fetch_decimals = True
    engine = create_engine(
        "oracle+oracledb://",
        connect_args={"user": user, "password": password, "dsn": dsn},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
        dbapi_connection.call_timeout = CALL_TIMEOUT_MS

    return engine


def map_error(exc: DBAPIError) -> PlatformError:
    """DB-02：等锁超时和死锁为 DOCUMENT_BUSY，连接断开为 DATABASE_UNAVAILABLE，其余为 INTERNAL_ERROR；不带 ORA- 文本。"""
    text = str(exc.orig)
    if any(code in text for code in _BUSY):
        return PlatformError(ErrorCode.DOCUMENT_BUSY, "单据正被其他人修改，请稍后再试")
    if exc.connection_invalidated or any(code in text for code in _UNAVAILABLE):
        return PlatformError(ErrorCode.DATABASE_UNAVAILABLE, "数据库暂时不可用")
    return PlatformError(ErrorCode.INTERNAL_ERROR, "数据库执行出错")


class OracleUnitOfWork:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self._tx = connection.begin()

    def commit(self) -> None:
        self._tx.commit()

    def rollback(self) -> None:
        if self._tx.is_active:
            self._tx.rollback()


class OracleUnitOfWorkFactory:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def begin(self) -> Iterator[OracleUnitOfWork]:
        try:
            with self._engine.connect() as connection:
                uow = OracleUnitOfWork(connection)
                try:
                    yield uow
                finally:
                    uow.rollback()
        except DBAPIError as exc:
            _log.warning("数据库错误：%s", exc.orig)  # 原文只进应用日志，不进响应（DB-02）
            raise map_error(exc) from exc
