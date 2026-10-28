"""只读连接旧库 cmx 的 `ConnectionFactory`（C08 第 2 节）。

用 d_cg 账号连接，开启只读事务（SET TRANSACTION READ ONLY），以 `CMX.表名` 读取；每条语句的调用超时为 25 秒
（engine 的 `create_oracle_engine`）。退出时总是回滚，不提交。只供 migration 和复制业务表使用。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy.engine import Connection


class OracleLegacyConnectionFactory:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def legacy_readonly(self) -> Iterator[Connection]:
        with self._engine.connect() as connection:
            tx = connection.begin()
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            try:
                yield connection
            finally:
                if tx.is_active:
                    tx.rollback()
