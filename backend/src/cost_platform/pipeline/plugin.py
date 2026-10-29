"""write-pipeline 的插件（架构 6.1，`.reports/modules/plugin-spec.md` 第 1、2 节）。

提供：`CommandRecorder`（判重、命令结果、命令记录）、`TableWriter`（审批通过后写没注册的表，交给 approval）、
管道阶段"确定涉及的单据"（页面保存）、"加锁读取"、"合并修改"、"合并意图"、"计算与规则"、"写入变更"（`stages.py`）。

没有接的：命令审查（WP-17）的 `review.ReviewedCommandExecutor` 要包在编排的 `CommandExecutor` 外面，还要 Redis 和请求上下文，
这次不注册（plugin-spec 第 4 节）。
"""

from __future__ import annotations

from pathlib import Path

from cost_platform.contracts.ports import (
    CommandRecorder,
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
from .merge import DocumentMerger, IntentMerger
from .stages import LockStage, MergeIntentsStage, MergePatchesStage, RecalculateStage, WriteChangesStage
from .table_writer import OracleTableWriter
from .values import ColumnScales
from .writer import ChangeWriter

MIGRATIONS = Path(migrations.__file__).parent
"""PF_COMMAND 的迁移脚本目录（assembly 的 `platform db` 用）。"""


class PipelinePlugin:
    name = "pipeline"
    provides = (CommandRecorder, TableWriter, PipelineStage)
    requires = (PermissionChecker, RulesEngine, SchemaInspector)

    def __init__(self, lock_wait_seconds: int, request_wait_seconds: int) -> None:
        """`lock_wait_seconds`：加锁读取等锁的秒数（`FOR UPDATE WAIT n`）；`request_wait_seconds`：同一请求键仍在处理时
        等待的秒数（WP-01）。"""
        self._lock_wait = lock_wait_seconds
        self._request_wait = request_wait_seconds

    def setup(self, reg: PluginView) -> None:
        permission = reg.get(PermissionChecker)
        engine = reg.get(RulesEngine)
        inspector = reg.get(SchemaInspector)
        scales = ColumnScales(inspector)
        store = OracleDocumentStore(self._lock_wait)
        loader = DocumentLoader(store, permission)
        tables = OracleTableWriter(self._lock_wait, inspector)
        reg.provide(TableWriter, tables)
        reg.provide(CommandRecorder, OracleCommandRecorder(self._request_wait, tables))
        stages: list[PipelineStage] = [
            PageSaveInvolved(),
            LockStage(loader),
            MergePatchesStage(DocumentMerger(permission, scales)),
            MergeIntentsStage(IntentMerger(loader, scales)),
            RecalculateStage(Recalculator(engine, scales)),
            WriteChangesStage(ChangeWriter(store)),
        ]
        for stage in stages:
            reg.add(PipelineStage, stage)
