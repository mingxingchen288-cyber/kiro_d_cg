"""db-core 插件（`.reports/modules/plugin-spec.md` 第 2 节）：Oracle 连接池、事务、表结构读取、只读读取旧库。

另导出命令行 `platform db` 要用的函数，assembly 只从这里导入：
- `create_oracle_engine(user, password, dsn)`；
- `migrate.upgrade(engine, 迁移目录)`、`migrate.check(engine, 迁移目录)`（DB-04，迁移目录取各模块 plugin.py 的 `MIGRATIONS`）；
- `copy_tables.copy_business_tables(engine, copy_tables.table_specs(), refresh)`（DB-03）。

db-core 自己没有平台表（`migrations/` 只是 Alembic 的执行环境），所以不导出 `MIGRATIONS`。
"""

from __future__ import annotations

from sqlalchemy import Engine

from cost_platform.contracts.ports import ConnectionFactory, SchemaInspector, UnitOfWorkFactory
from cost_platform.contracts.registry import PluginView

from . import copy_tables, migrate
from .engine import OracleUnitOfWorkFactory, create_oracle_engine
from .legacy import OracleLegacyConnectionFactory
from .schema import OracleSchemaInspector

__all__ = ["DbCorePlugin", "copy_tables", "create_oracle_engine", "migrate"]


class DbCorePlugin:
    """三个端口共用一个连接池；连接在第一次使用时才建立，setup 不连数据库。关闭时释放连接池。"""

    name = "db-core"
    provides = (UnitOfWorkFactory, SchemaInspector, ConnectionFactory)
    requires = ()

    def __init__(self, db_user: str, db_password: str, db_dsn: str) -> None:
        self._user = db_user
        self._password = db_password
        self._dsn = db_dsn
        self._engine: Engine   # setup 中创建，stop 时释放

    def setup(self, reg: PluginView) -> None:
        engine = create_oracle_engine(self._user, self._password, self._dsn)
        reg.provide(UnitOfWorkFactory, OracleUnitOfWorkFactory(engine))
        reg.provide(SchemaInspector, OracleSchemaInspector(engine))
        reg.provide(ConnectionFactory, OracleLegacyConnectionFactory(engine))
        self._engine = engine

    async def stop(self) -> None:
        self._engine.dispose()
