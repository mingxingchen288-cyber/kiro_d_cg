"""identity 的两个插件（`.reports/modules/plugin-spec.md` 第 2 节）。

- `identity.directory`：`DirectoryReader`（账号、按角色找启用的账号、部门），只要数据库。config 和 approval 用它；
  它和 `identity` 分开，是因为 `identity` 要用 config 的 `ConfigSnapshotReader`，放在一起会成环。
- `identity`：`Authenticator` 和 C09 第 2 节的路由（登录、选角色、注销、`/api/me`、账号和部门管理）；会话在 Redis。
  启动时初始化 admin（ID-06）。

两个插件各自创建自己的账号存储 `OracleAccounts`，共享的只有数据库。平台表迁移目录为 `MIGRATIONS`。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection
from pathlib import Path

from fastapi import APIRouter

from cost_platform.contracts.ports import (
    Authenticator,
    Clock,
    ConfigSnapshotReader,
    DirectoryReader,
    IdGenerator,
    RealtimePublisher,
    UnitOfWorkFactory,
)
from cost_platform.contracts.registry import PluginView

from . import migrations
from .accounts import OracleAccounts
from .admin import AccountAdmin
from .router import identity_router
from .service import IdentityService, describe_role_from
from .sessions import RedisSessions

__all__ = ["MIGRATIONS", "IdentityDirectoryPlugin", "IdentityPlugin"]

MIGRATIONS = Path(migrations.__file__).parent
"""PF_USER、PF_USER_ROLE、PF_DEPARTMENT 和它们的序列（assembly 的 `platform db` 用）。"""

_log = logging.getLogger(__name__)


class IdentityDirectoryPlugin:
    name = "identity.directory"
    provides = (DirectoryReader,)
    requires = (UnitOfWorkFactory,)

    def setup(self, reg: PluginView) -> None:
        reg.provide(DirectoryReader, OracleAccounts(reg.get(UnitOfWorkFactory)))


class IdentityPlugin:
    """构造参数取 `.env`：`PLATFORM_REDIS_URL`、`PLATFORM_REDIS_NAMESPACE`、`PLATFORM_SESSION_IDLE_MINUTES`、
    `PLATFORM_ALLOWED_ORIGINS`。Redis 客户端在第一次读写会话时才连接，setup 不连 Redis。"""

    name = "identity"
    provides = (Authenticator, APIRouter)
    requires = (UnitOfWorkFactory, Clock, IdGenerator, ConfigSnapshotReader, RealtimePublisher)

    def __init__(self, redis_url: str, redis_namespace: str, session_idle_minutes: int,
                 allowed_origins: Collection[str]) -> None:
        self._redis_url = redis_url
        self._namespace = redis_namespace
        self._idle_minutes = session_idle_minutes
        self._allowed_origins = frozenset(allowed_origins)
        self._accounts: OracleAccounts   # setup 中创建，start 用

    def setup(self, reg: PluginView) -> None:
        accounts = OracleAccounts(reg.get(UnitOfWorkFactory))
        sessions = RedisSessions.from_url(self._redis_url, self._namespace)
        config = reg.get(ConfigSnapshotReader)
        publisher, ids = reg.get(RealtimePublisher), reg.get(IdGenerator)
        describe = describe_role_from(config)
        service = IdentityService(accounts, sessions, reg.get(Clock), self._idle_minutes, describe,
                                  publisher=publisher, ids=ids)
        admin = AccountAdmin(accounts, sessions, describe, publisher=publisher, ids=ids)
        reg.provide(Authenticator, service)
        reg.add(APIRouter, identity_router(service, admin, config, self._allowed_origins))
        self._accounts = accounts

    async def start(self) -> None:
        """ID-06：没有 admin 时创建 admin / admin123..，分配 ADMIN 角色；已存在时不改任何内容。"""
        if await asyncio.to_thread(self._accounts.ensure_admin):
            _log.info("已创建管理员账号 admin（ID-06）")
