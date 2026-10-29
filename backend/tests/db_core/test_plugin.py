"""db-core 插件（plugin-spec 第 2、5 节）：setup 注册三个端口；真实验证在 d_cg 上经注册的端口读写。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import text

from cost_platform.contracts.ports import ConnectionFactory, SchemaInspector, UnitOfWorkFactory
from cost_platform.contracts.registry import PluginView, Registry
from cost_platform.db_core.engine import OracleUnitOfWorkFactory
from cost_platform.db_core.legacy import OracleLegacyConnectionFactory
from cost_platform.db_core.plugin import DbCorePlugin, copy_tables, create_oracle_engine, migrate
from cost_platform.db_core.schema import OracleSchemaInspector

PORTS = (UnitOfWorkFactory, SchemaInspector, ConnectionFactory)


class Probe:
    """只声明 requires 的插件：在 setup 中取出被测插件注册的实现（boot 结束后注册表冻结，不能再取）。"""

    name = "probe"
    provides: tuple[type, ...] = ()

    def __init__(self, *ports: type) -> None:
        self.requires = ports
        self.got: dict[type, Any] = {}

    def setup(self, reg: PluginView) -> None:
        self.got = {port: reg.get(port) for port in self.requires}


def test_setup_registers_ports() -> None:
    """setup 只建连接池、不连数据库，所以用连不上的地址也能完成。"""
    plugin = DbCorePlugin("ct_user", "ct_password", "127.0.0.1:1/none")
    probe = Probe(*PORTS)
    ordered = Registry().boot([probe, plugin])
    assert [p.name for p in ordered] == ["db-core", "probe"]
    assert [type(probe.got[p]) for p in PORTS] == [OracleUnitOfWorkFactory, OracleSchemaInspector,
                                                   OracleLegacyConnectionFactory]
    asyncio.run(plugin.stop())


def test_exports_for_platform_db() -> None:
    """assembly 的 `platform db` 只从 plugin 导入这些函数（plugin-spec 第 4 节）。"""
    assert callable(create_oracle_engine)
    assert callable(migrate.upgrade) and callable(migrate.check)
    assert callable(copy_tables.copy_business_tables) and "T_COST_GOODS" in copy_tables.table_specs()


@pytest.mark.oracle
def test_registered_ports_work_on_d_cg() -> None:
    """按 `.env` 的连接信息启动插件，经注册的三个端口读 d_cg 和 cmx；关闭时释放连接池。"""
    from cost_platform.assembly.settings import Settings

    s = Settings.load()
    plugin = DbCorePlugin(s.db_user, s.db_password, s.db_dsn)
    probe = Probe(*PORTS)
    Registry().boot([plugin, probe])
    uow_factory: UnitOfWorkFactory = probe.got[UnitOfWorkFactory]
    inspector: SchemaInspector = probe.got[SchemaInspector]
    legacy: ConnectionFactory = probe.got[ConnectionFactory]
    try:
        with uow_factory.begin() as uow:
            assert uow.connection.execute(text("SELECT COUNT(*) FROM T_COST_GOODS WHERE GOODSID = 115")).scalar_one() == 1
        assert inspector.object_type("T_COST_GOODS") == "table"
        assert inspector.primary_key("T_COST_GOODS") == "GOODSID"
        with legacy.legacy_readonly() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM CMX.T_COST_GOODS WHERE GOODSID = 115")).scalar_one() == 1
    finally:
        asyncio.run(plugin.stop())
