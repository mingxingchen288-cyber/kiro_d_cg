"""db-core 的真实验证（d_cg）共用的准备。本模块没有替代实现，测试直接用 d_cg（模块说明第 7 节）。

- 连接信息由 assembly 的 Settings 从仓库根目录的 `.env` 读取，不打印。
- 测试自己建的表、视图都以 `CT_DB_` 或 `CT_SCHEMA_` 开头（契约测试固定用 CT_SCHEMA_PROBE），用完删除；
  不碰 `PF_`、`BP_T09_` 开头的对象，也不改复制来的业务表。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text


def oracle_engine() -> Engine:
    from cost_platform.assembly.settings import Settings
    from cost_platform.db_core.engine import create_oracle_engine

    s = Settings.load()
    return create_oracle_engine(s.db_user, s.db_password, s.db_dsn)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    found = oracle_engine()
    yield found
    found.dispose()


def drop_if_exists(engine: Engine, name: str, kind: str = "TABLE") -> None:
    """删除测试自己建的表或视图（kind 为 TABLE 或 VIEW）。"""
    assert name.startswith(("CT_DB_", "CT_SCHEMA_")), name
    with engine.connect() as c:
        found = c.execute(text("SELECT COUNT(*) FROM user_objects WHERE object_name = :n AND object_type = :k"),
                          {"n": name, "k": kind}).scalar_one()
        if found:
            c.exec_driver_sql(f"DROP {kind} {name}" + (" PURGE" if kind == "TABLE" else ""))


def ensure_table(engine: Engine, name: str, ddl: str) -> None:
    """表不存在时按 `ddl`（CREATE TABLE 之后的部分）建表，然后清空。"""
    assert name.startswith("CT_DB_"), name
    with engine.connect() as c:
        if not c.execute(text("SELECT COUNT(*) FROM user_tables WHERE table_name = :n"), {"n": name}).scalar_one():
            c.exec_driver_sql(f"CREATE TABLE {name} {ddl}")
        c.exec_driver_sql(f"DELETE FROM {name}")
        c.commit()
