"""插件清单（架构 6.1，用户 2026-10-29 定）：assembly 只维护插件清单并调用注册表的 `boot`，不创建各模块的对象。

各模块的插件在它的 plugin.py 里；这里另有 assembly 自己的四个插件：

| 插件 | provides | requires |
|---|---|---|
| `system` | Clock、IdGenerator（AS-08） | — |
| `rules-core` | RulesEngine（rules-core 的 Python 包，只有 assembly 可以导入它） | — |
| `http` | ContextProvider（AS-02：会话、来源、CSRF、配置快照） | Authenticator、ConfigSnapshotReader、Clock、IdGenerator |
| `app` | — | CommandExecutor、ContextProvider、ConfigSnapshotReader、RulesEngine、APIRouter |

`app` 在 setup 中取到命令执行、执行上下文、配置代号、规则引擎和全部路由，由 app.py 挂到 FastAPI 上。

运行时只有一份插件清单：Oracle + Redis（`oracle_plugins`），不再有 `PLATFORM_BACKEND` 设置。内存组合（contracts 的替代实现）
只用于 assembly 的模拟验证（backend/tests/assembly，AS-01）。
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from cost_platform.approval.plugin import MIGRATIONS as APPROVAL_MIGRATIONS
from cost_platform.approval.plugin import ApprovalPlugin, ApprovalServicePlugin
from cost_platform.authz.plugin import AuthzPlugin
from cost_platform.config.plugin import MIGRATIONS as CONFIG_MIGRATIONS
from cost_platform.config.plugin import ConfigApiPlugin, ConfigPlugin
from cost_platform.contracts.ports import (
    Authenticator,
    Clock,
    CommandExecutor,
    ConfigSnapshotReader,
    ContextProvider,
    IdGenerator,
    RulesEngine,
)
from cost_platform.contracts.registry import Plugin, PluginView
from cost_platform.contracts.types import ErrorCode, ExecutionContext, Origin, PlatformError
from cost_platform.db_core.plugin import DbCorePlugin
from cost_platform.delivery.plugin import MIGRATIONS as DELIVERY_MIGRATIONS
from cost_platform.delivery.plugin import DeliveryPlugin
from cost_platform.identity.plugin import MIGRATIONS as IDENTITY_MIGRATIONS
from cost_platform.identity.plugin import IdentityDirectoryPlugin, IdentityPlugin
from cost_platform.operations.plugin import OperationsPlugin
from cost_platform.orchestration.plugin import OrchestrationPlugin
from cost_platform.pipeline.plugin import MIGRATIONS as PIPELINE_MIGRATIONS
from cost_platform.pipeline.plugin import PipelinePlugin
from cost_platform.queries.plugin import MIGRATIONS as QUERIES_MIGRATIONS
from cost_platform.queries.plugin import QueriesPlugin, QueryReadersPlugin
from cost_platform.realtime.plugin import RealtimePlugin, RealtimePublisherPlugin

from .settings import Settings

MIGRATION_DIRS: list[Path] = [PIPELINE_MIGRATIONS, IDENTITY_MIGRATIONS, CONFIG_MIGRATIONS, QUERIES_MIGRATIONS,
                              APPROVAL_MIGRATIONS, DELIVERY_MIGRATIONS]
"""各模块平台表的迁移目录（`platform db`）。"""

SESSION_COOKIE = "cp_session"


# ---------------------------------------------------------------- system：时间和编号（AS-08）

class SystemClock:
    """服务器本地时间，不带时区（C01 第 4 节）。"""

    def now(self) -> datetime:
        return datetime.now()


class UuidGenerator:
    def uuid(self) -> str:
        return str(uuid.uuid4())


class SystemPlugin:
    name = "system"
    provides = (Clock, IdGenerator)
    requires = ()

    def setup(self, reg: PluginView) -> None:
        reg.provide(Clock, SystemClock())
        reg.provide(IdGenerator, UuidGenerator())


# ---------------------------------------------------------------- rules-core：规则引擎

class RulesCorePlugin:
    """rules-core 的 Python 包 `cost_rules_core`（wheel）。只有 assembly 可以导入它（架构第 3 节），在 setup 中导入。"""

    name = "rules-core"
    provides = (RulesEngine,)
    requires = ()

    def setup(self, reg: PluginView) -> None:
        from cost_rules_core import RulesEngine as CoreRulesEngine

        reg.provide(RulesEngine, CoreRulesEngine())


# ---------------------------------------------------------------- http：执行上下文（AS-02）

class RequestContexts:
    """`ContextProvider`：写请求先核对来源（Origin 必须在 `PLATFORM_ALLOWED_ORIGINS` 中），再校验会话和 CSRF；
    带 `X-Background-Request: 1` 的请求不顺延会话（ID-10）；按会话的角色取配置快照。"""

    def __init__(self, authenticator: Authenticator, config: ConfigSnapshotReader, clock: Clock, ids: IdGenerator,
                 allowed_origins: Collection[str]) -> None:
        self._authenticator = authenticator
        self._config = config
        self._clock = clock
        self._ids = ids
        self._allowed_origins = frozenset(allowed_origins)

    def context(self, request: Any, is_write: bool) -> ExecutionContext:
        if is_write and request.headers.get("origin") not in self._allowed_origins:
            raise PlatformError(ErrorCode.ORIGIN_REJECTED, "请求来源不被允许")
        identity = self._authenticator.authenticate(
            request.cookies.get(SESSION_COOKIE), request.headers.get("x-csrf-token"), is_write,
            touch=request.headers.get("x-background-request") != "1")
        snapshot = self._config.read(identity.role_code)
        return ExecutionContext(request_id=self._ids.uuid(), identity=identity, config=snapshot,
                                config_version=snapshot.version, origin=Origin("user", None), now=self._clock.now())


class HttpPlugin:
    name = "http"
    provides = (ContextProvider,)
    requires = (Authenticator, ConfigSnapshotReader, Clock, IdGenerator)

    def __init__(self, allowed_origins: Collection[str]) -> None:
        self._allowed_origins = frozenset(allowed_origins)

    def setup(self, reg: PluginView) -> None:
        reg.provide(ContextProvider, RequestContexts(reg.get(Authenticator), reg.get(ConfigSnapshotReader), reg.get(Clock),
                                                     reg.get(IdGenerator), self._allowed_origins))


# ---------------------------------------------------------------- app：挂到 FastAPI 上的东西

class AppPlugin:
    """取用 app.py 要挂载的东西：全部路由（含 realtime 的 /ws）、`POST /api/commands` 用的命令执行和执行上下文、
    响应头 `X-Config-Version` 和 `/health` 用的配置代号，以及 `/health` 的 `coreVersion`（C09）用的规则引擎。"""

    name = "app"
    provides = ()
    requires = (CommandExecutor, ContextProvider, ConfigSnapshotReader, RulesEngine, APIRouter)

    executor: CommandExecutor
    contexts: ContextProvider
    config: ConfigSnapshotReader
    rules: RulesEngine
    routers: list[APIRouter]

    def setup(self, reg: PluginView) -> None:
        self.executor = reg.get(CommandExecutor)
        self.contexts = reg.get(ContextProvider)
        self.config = reg.get(ConfigSnapshotReader)
        self.rules = reg.get(RulesEngine)
        self.routers = reg.all(APIRouter)


# ---------------------------------------------------------------- 插件清单

def oracle_plugins(settings: Settings) -> list[Plugin]:
    """Oracle + Redis 组合的全部插件（不含 `app`）。清单的先后不影响启动顺序，由注册表按 requires 排。"""
    redis_url, ns, origins = settings.redis_url, settings.redis_namespace, settings.allowed_origins
    return [
        DbCorePlugin(settings.db_user, settings.db_password, settings.db_dsn),
        SystemPlugin(),
        RulesCorePlugin(),
        HttpPlugin(origins),
        RealtimePublisherPlugin(redis_url, ns),
        RealtimePlugin(redis_url, ns, origins),
        IdentityDirectoryPlugin(),
        IdentityPlugin(redis_url, ns, settings.session_idle_minutes, origins),
        ConfigPlugin(redis_url, ns, str(settings.config_dir)),
        ConfigApiPlugin(redis_url, ns),
        AuthzPlugin(),
        QueryReadersPlugin(),
        QueriesPlugin(),
        PipelinePlugin(settings.lock_wait_seconds, settings.request_wait_seconds, redis_url, ns),
        OperationsPlugin(),
        ApprovalPlugin(),
        ApprovalServicePlugin(),
        DeliveryPlugin(),
        OrchestrationPlugin(),
    ]
