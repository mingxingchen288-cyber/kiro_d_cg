"""config 的两个插件（`.reports/modules/plugin-spec.md` 第 2 节）。

- `config`：配置快照读取（`ConfigSnapshotReader`）和最新已发布的实体配置（`EntityDirectory`）；start 依次导入基础配置
  （PF_CONFIG_ITEM 没有基础配置项时，`seed.py`）→ ADMIN 角色初始化（CF-10）→ 启动预热（CF-13）→ 启动恢复任务（CF-05），
  stop 停恢复任务。
- `config.api`：C09 第 3 节的 HTTP 接口。路由要用 `ContextProvider`（assembly 提供），而 assembly 的 `ContextProvider` 要用
  `ConfigSnapshotReader`，放在同一个插件里会成环，所以单列。它有自己的 `ConfigService` 和 Redis 缓存对象，与 `config`
  共享的只有数据库和 Redis。

两个插件的 Redis 客户端都用 `decode_responses=True`（`RedisConfigCache` 的要求），读写超时 5 秒。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import redis
from fastapi import APIRouter

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
from cost_platform.contracts.registry import PluginView

from . import migrations
from .deps import DirectoryDepartments, OracleSequences
from .entities import PublishedEntities
from .redis_cache import RedisConfigCache
from .router import create_router
from .runtime import ConfigRuntime, RecoveryTask
from .seed import import_seed
from .service import ConfigService
from .snapshot import ConfigReader
from .validation import Validator

MIGRATIONS = Path(migrations.__file__).parent
"""PF_CONFIG_ITEM、PF_CONFIG_GENERATION 的迁移脚本目录（assembly 的 `platform db` 用）。"""

REDIS_TIMEOUT_SECONDS = 5


def _cache(redis_url: str, redis_namespace: str) -> RedisConfigCache:
    client = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=REDIS_TIMEOUT_SECONDS)
    return RedisConfigCache(client, redis_namespace)


def _service(uow: UnitOfWorkFactory, schema: SchemaInspector, engine: RulesEngine, publisher: RealtimePublisher,
             directory: DirectoryReader, clock: Clock, ids: IdGenerator, cache: RedisConfigCache) -> ConfigService:
    validator = Validator(schema, OracleSequences(), DirectoryDepartments(directory), engine)
    return ConfigService(uow, validator, cache, publisher, clock, ids)


class ConfigPlugin:
    name = "config"
    provides = (ConfigSnapshotReader, EntityDirectory)
    requires = (UnitOfWorkFactory, SchemaInspector, RulesEngine, RealtimePublisher, DirectoryReader, Clock, IdGenerator)

    def __init__(self, redis_url: str, redis_namespace: str, seed_dir: str) -> None:
        self._redis_url = redis_url
        self._redis_namespace = redis_namespace
        self._seed_dir = Path(seed_dir)

    def setup(self, reg: PluginView) -> None:
        uow = reg.get(UnitOfWorkFactory)
        engine = reg.get(RulesEngine)
        publisher = reg.get(RealtimePublisher)
        clock = reg.get(Clock)
        ids = reg.get(IdGenerator)
        cache = _cache(self._redis_url, self._redis_namespace)
        self.service = _service(uow, reg.get(SchemaInspector), engine, publisher, reg.get(DirectoryReader), clock, ids, cache)
        self.reader = ConfigReader(uow, cache, engine, publisher, ids)
        self.runtime = ConfigRuntime(uow, cache, self.reader)
        self.recovery = RecoveryTask(uow, cache, publisher, clock, ids)
        reg.provide(ConfigSnapshotReader, self.reader)
        reg.provide(EntityDirectory, PublishedEntities(uow, self.reader))

    def _boot(self) -> None:
        import_seed(self.service, self._seed_dir)
        self.service.ensure_admin_role()
        self.runtime.warm_up()
        self.recovery.start()

    async def start(self) -> None:
        """预热要读 Oracle、写 Redis（Redis 不可用时每 5 秒重试），在线程中执行，不占事件循环。"""
        await asyncio.to_thread(self._boot)

    async def stop(self) -> None:
        await asyncio.to_thread(self.recovery.stop)


class ConfigApiPlugin:
    name = "config.api"
    provides = (APIRouter,)
    requires = (ContextProvider, UnitOfWorkFactory, SchemaInspector, RulesEngine, RealtimePublisher, DirectoryReader, Clock,
                IdGenerator)

    def __init__(self, redis_url: str, redis_namespace: str) -> None:
        self._redis_url = redis_url
        self._redis_namespace = redis_namespace

    def setup(self, reg: PluginView) -> None:
        cache = _cache(self._redis_url, self._redis_namespace)
        service = _service(reg.get(UnitOfWorkFactory), reg.get(SchemaInspector), reg.get(RulesEngine),
                           reg.get(RealtimePublisher), reg.get(DirectoryReader), reg.get(Clock), reg.get(IdGenerator), cache)
        reg.add(APIRouter, create_router(service, reg.get(ContextProvider).context))
