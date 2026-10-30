"""config 的插件（plugin-spec 第 5 节）：用 contracts 的替代实现做提供方，`Registry().boot` 后两个插件声明的端口都已注册；
`config` 插件的 start 依次导入基础配置、ADMIN 初始化、预热、启动恢复任务（需要 Redis）。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import APIRouter

from cost_platform.config.deps import DirectoryDepartments
from cost_platform.config.entities import PublishedEntities
from cost_platform.config.plugin import MIGRATIONS, ConfigApiPlugin, ConfigPlugin
from cost_platform.config.records import BASE_TYPES
from cost_platform.config.seed import import_seed
from cost_platform.config.snapshot import ConfigReader
from cost_platform.contracts.fakes import (
    FakeClock,
    FakeDirectory,
    FakeIdGenerator,
    FakeRealtimePublisher,
    FakeRulesEngine,
    FakeSchemaInspector,
    FakeUnitOfWorkFactory,
)
from cost_platform.contracts.ports import (
    Clock,
    ConfigSnapshotReader,
    ContextProvider,
    DirectoryReader,
    EntityDirectory,
    IdGenerator,
    RealtimePublisher,
    RulesEngine,
    SchemaInspector,
    UnitOfWorkFactory,
)
from cost_platform.contracts.registry import MULTI_PORTS, PluginView, Registry

from .support import DEPARTMENTS, SEED, SEQUENCES, Env, base_world, flow_samples, seed_drafts

REDIS_URL = "redis://127.0.0.1:6379/0"


class Provider:
    """替代实现的提供方：一个插件注册给出的端口。"""

    requires: tuple[type, ...] = ()

    def __init__(self, impls: dict[type, Any], name: str = "fakes") -> None:
        self.name = name
        self.provides = tuple(impls)
        self._impls = impls

    def setup(self, reg: PluginView) -> None:
        for port, impl in self._impls.items():
            (reg.add if port in MULTI_PORTS else reg.provide)(port, impl)


class Consumer:
    """取用被测插件注册的端口，记下拿到的实现。"""

    name = "consumer"
    provides: tuple[type, ...] = ()

    def __init__(self, *ports: type) -> None:
        self.requires = ports
        self.got: dict[type, Any] = {}

    def setup(self, reg: PluginView) -> None:
        for port in self.requires:
            self.got[port] = reg.all(port) if port in MULTI_PORTS else reg.get(port)


class NoContext:
    def context(self, request: Any, is_write: bool) -> Any:
        raise AssertionError("setup 测试不处理请求")


def fakes(env: Env | None = None, directory: FakeDirectory | None = None) -> Provider:
    return Provider({
        UnitOfWorkFactory: env.uow if env else FakeUnitOfWorkFactory(),
        SchemaInspector: env.schema if env else FakeSchemaInspector(),
        RulesEngine: env.engine if env else FakeRulesEngine(),
        RealtimePublisher: env.publisher if env else FakeRealtimePublisher(),
        DirectoryReader: directory or FakeDirectory(),
        Clock: env.clock if env else FakeClock(),
        IdGenerator: env.ids if env else FakeIdGenerator(),
        ContextProvider: NoContext(),
    })


def test_setup_registers_config_ports() -> None:
    """`config` 注册配置快照读取和实体目录，`config.api` 注册 C09 第 3 节的路由；两者都排在提供方之后。"""
    config = ConfigPlugin(REDIS_URL, "cost-platform-test", str(SEED))
    api = ConfigApiPlugin(REDIS_URL, "cost-platform-test")
    consumer = Consumer(ConfigSnapshotReader, EntityDirectory, APIRouter)
    order = Registry().boot([consumer, api, config, fakes()])
    assert [p.name for p in order] == ["fakes", "config", "config.api", "consumer"]
    assert isinstance(consumer.got[ConfigSnapshotReader], ConfigReader)
    assert isinstance(consumer.got[EntityDirectory], PublishedEntities)
    [router] = consumer.got[APIRouter]
    assert {"/api/config/items", "/api/config/items/{config_type}/{key}", "/api/pages/{page_code}/view"} <= {
        r.path for r in router.routes}
    assert (MIGRATIONS / "cf_0001_pf_config.py").exists()


def test_departments_come_from_directory_reader() -> None:
    """审批节点的部门按 identity 的 `DirectoryReader.department` 判断：C06 7.9 的部门 1069 在目录中，三个样例能保存。"""
    env = Env()
    directory = FakeDirectory()
    directory.departments = {d: (f"部门{d}", None) for d in DEPARTMENTS}
    env.validator.departments = DirectoryDepartments(directory)
    env.save(base_world())
    env.save(flow_samples())
    assert "1069" in [c.args[0] for c in directory.calls_to("department")]


def test_import_seed_only_when_no_base_items() -> None:
    """PF_CONFIG_ITEM 没有基础配置项时一次保存 seed 的配置项（代号加一）；已有时不再导入。"""
    env = Env()
    assert import_seed(env.service, SEED) == len(seed_drafts()) == 28
    stored = {(r.type, r.key) for r in env.records().values() if r.type in BASE_TYPES}
    assert stored == {(d.type, d.key) for d in seed_drafts()} and env.generation() == 1
    assert import_seed(env.service, SEED) == 0 and env.generation() == 1


# ---------------------------------------------------------------- start（内存 SQLite + 真实 Redis）

@pytest.mark.redis
def test_start_imports_seed_then_warms_up_and_stops() -> None:
    """start：导入 seed → ADMIN 已在 seed 中，不再创建 → 预热（ready）→ 恢复任务在运行；stop 停掉它。
    再启动一次时已有基础配置项，不导入，代号不变。

    数据库是内存 SQLite（tests/config/support.py）。插件用 `OracleSequences` 查 USER_SEQUENCES，这里在 SQLite 中按
    support.SEQUENCES 建一张同名的表代替 Oracle 的数据字典视图。"""
    from .real_support import drop_namespace, env_values, fresh_namespace, redis_client

    url = env_values().get("PLATFORM_REDIS_URL", REDIS_URL)
    env = Env()
    with env.uow.engine.begin() as c:
        c.exec_driver_sql("CREATE TABLE user_sequences (sequence_name VARCHAR2(128))")
        for name in SEQUENCES:
            c.exec_driver_sql("INSERT INTO user_sequences VALUES (?)", (name,))
    directory = FakeDirectory()
    client, namespace = redis_client(), fresh_namespace()
    started: list[ConfigPlugin] = []
    try:
        plugin = ConfigPlugin(url, namespace, str(SEED))
        Registry().boot([plugin, fakes(env, directory)])
        started.append(plugin)
        asyncio.run(plugin.start())
        assert {(r.type, r.key) for r in env.records().values() if r.type in BASE_TYPES} == {(d.type, d.key) for d in seed_drafts()}
        assert plugin.runtime.ready and plugin.recovery._thread is not None and plugin.recovery._thread.is_alive()
        generation = env.generation()
        assert plugin.reader.current_version() == generation
        assert plugin.reader.read("ADMIN").page_view("COST_PINGGU").page_code == "COST_PINGGU"
        asyncio.run(plugin.stop())
        assert not plugin.recovery._thread.is_alive()

        again = ConfigPlugin(url, namespace, str(SEED))
        Registry().boot([again, fakes(env, directory)])
        started.append(again)
        asyncio.run(again.start())
        assert env.generation() == generation and again.runtime.ready
    finally:
        for p in started:
            p.recovery.stop()
        drop_namespace(client, namespace)
