"""write-pipeline 的插件（架构 6.1，`.reports/modules/plugin-spec.md` 第 1、2 节）。

提供：`CommandRecorder`（判重、命令结果、命令记录）、`TableWriter`（审批通过后写没注册的表，交给 approval）、
`BusinessLocker`（业务加锁的统一入口，交给 approval、operations，`locks.py`）、
`CommandMonitor`（命令审查 WP-17，orchestration 包在整个命令事务外面）、管道阶段"确定涉及的单据"（页面保存）、
"加锁读取"、"合并修改"、"合并意图"、"计算与规则"、"写入变更"（`stages.py`），以及 C09 第 7a 节的路由
`/api/admin/command-review`（执行上下文取 assembly 的 `ContextProvider`）。

命令审查的开关和记录在 Redis（`{ns}:cmdlog`、`{ns}:cmdlog:enabled`）；Redis 客户端在第一次读写时才连接，setup 不连 Redis。

start 预读已发布实体（`EntityDirectory.tables`）的表的列定义，stop 停掉后台检查（`warmup.py`，WP-15）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import redis
from fastapi import APIRouter

from cost_platform.contracts.ports import (
    BusinessLocker,
    Clock,
    CommandMonitor,
    CommandRecorder,
    ContextProvider,
    EntityDirectory,
    PermissionChecker,
    PipelineStage,
    RulesEngine,
    SchemaInspector,
    TableWriter,
)
from cost_platform.contracts.registry import PluginView

from . import migrations
from .calc import Recalculator
from .command_log import OracleCommandRecorder
from .document_store import OracleDocumentStore
from .loader import DocumentLoader, PageSaveInvolved
from .locks import LockBook, PipelineLocks
from .merge import DocumentMerger, IntentMerger
from .review import RedisCommandMonitor, RedisCommandReview, command_review_router
from .stages import LockStage, MergeIntentsStage, MergePatchesStage, RecalculateStage, WriteChangesStage
from .table_writer import OracleTableWriter
from .tracing import SqlTracer
from .values import ColumnScales
from .warmup import SchemaWarmup
from .writer import ChangeWriter

MIGRATIONS = Path(migrations.__file__).parent
"""PF_COMMAND 的迁移脚本目录（assembly 的 `platform db` 用）。"""

REDIS_TIMEOUT_SECONDS = 5
"""命令审查读写 Redis 的超时：每个命令都要读开关，Redis 不可用时最多等这么久，之后照常执行命令。"""


class PipelinePlugin:
    name = "pipeline"
    provides = (CommandRecorder, TableWriter, BusinessLocker, CommandMonitor, PipelineStage, APIRouter)
    requires = (PermissionChecker, RulesEngine, SchemaInspector, Clock, ContextProvider, EntityDirectory)

    def __init__(self, lock_wait_seconds: int, request_wait_seconds: int, redis_url: str, redis_namespace: str) -> None:
        """`lock_wait_seconds`：加锁读取等锁的秒数（`FOR UPDATE WAIT n`）；`request_wait_seconds`：同一请求键仍在处理时
        等待的秒数（WP-01）；`redis_url`、`redis_namespace`：命令审查用的 Redis（`.env` 的 `PLATFORM_REDIS_URL`、
        `PLATFORM_REDIS_NAMESPACE`）。"""
        self._lock_wait = lock_wait_seconds
        self._request_wait = request_wait_seconds
        self._redis_url = redis_url
        self._redis_namespace = redis_namespace
        self._warmup: SchemaWarmup  # setup 中创建，start 中预读

    def setup(self, reg: PluginView) -> None:
        permission = reg.get(PermissionChecker)
        engine = reg.get(RulesEngine)
        inspector = reg.get(SchemaInspector)
        scales = ColumnScales(inspector)
        self._warmup = SchemaWarmup(scales, reg.get(EntityDirectory))
        book = LockBook()  # 加锁读取、TableWriter、BusinessLocker 共用：同一事务的锁按同一顺序检查（locks.py）
        store = OracleDocumentStore(self._lock_wait)
        loader = DocumentLoader(store, permission, book)
        tables = OracleTableWriter(self._lock_wait, inspector, book)
        reg.provide(TableWriter, tables)
        reg.provide(BusinessLocker, PipelineLocks(book, store, inspector))
        reg.provide(CommandRecorder, OracleCommandRecorder(self._request_wait, tables))
        client = redis.Redis.from_url(self._redis_url, socket_timeout=REDIS_TIMEOUT_SECONDS)
        review = RedisCommandReview(client, self._redis_namespace)
        reg.provide(CommandMonitor, RedisCommandMonitor(review, SqlTracer(), reg.get(Clock)))
        reg.add(APIRouter, command_review_router(review, reg.get(ContextProvider).context))
        stages: list[PipelineStage] = [
            PageSaveInvolved(),
            LockStage(loader),
            MergePatchesStage(DocumentMerger(permission, scales)),
            MergeIntentsStage(IntentMerger(scales)),
            RecalculateStage(Recalculator(engine, scales)),
            WriteChangesStage(ChangeWriter(store)),
        ]
        for stage in stages:
            reg.add(PipelineStage, stage)

    async def start(self) -> None:
        """预读已发布实体的表的列定义，读完才返回（平台在全部插件 start 之后才接受请求）；再启动后台检查（`warmup.py`）。
        排在 config 之后 start（依赖 `ContextProvider`、`EntityDirectory`），这时配置已预热。"""
        await asyncio.to_thread(self._warmup.start)

    async def stop(self) -> None:
        await asyncio.to_thread(self._warmup.stop)
