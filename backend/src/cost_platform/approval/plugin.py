"""approval 的两个插件（架构 6.1，`.reports/modules/plugin-spec.md` 第 1、2 节）。

- `approval`：`FreezeReader` 和管道阶段"确定涉及的单据"（审批命令）、"冻结检查"、"审批处理"、"触发审批"、"强制审批检查"。
- `approval.service`：C09 第 6 节的接口（`APIRouter`）。审批的通过、驳回、撤回经 orchestration 的 `CommandExecutor` 执行，
  而 orchestration 要用上面的管道阶段，所以接口单独一个插件，避免成环。

两个插件各自创建自己的 `ApprovalDeps`（`ApprovalStore`、SQL 执行、取主键都没有状态），共享的只有数据库。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from cost_platform.contracts.ports import (
    CommandExecutor,
    ConfigSnapshotReader,
    ContextProvider,
    DirectoryReader,
    DocumentReader,
    EntityDirectory,
    FreezeReader,
    PipelineStage,
    RulesEngine,
    SchemaInspector,
    TableWriter,
    UnitOfWorkFactory,
)
from cost_platform.contracts.registry import PluginView

from . import migrations
from .catalog import catalog_of
from .deps import ApprovalDeps
from .module import create_approval
from .router import approval_router
from .service import ApprovalService

MIGRATIONS = Path(migrations.__file__).parent
"""PF_APPROVAL 等平台表的迁移脚本目录（assembly 的 `platform db` 用）。"""

_DEPS = (SchemaInspector, DirectoryReader, DocumentReader, RulesEngine, TableWriter, EntityDirectory, ConfigSnapshotReader)


def _deps(reg: PluginView) -> ApprovalDeps:
    return ApprovalDeps(catalog=catalog_of(reg.get(EntityDirectory), reg.get(ConfigSnapshotReader)),
                        schema=reg.get(SchemaInspector), directory=reg.get(DirectoryReader), documents=reg.get(DocumentReader),
                        rules=reg.get(RulesEngine), tables=reg.get(TableWriter))


class ApprovalPlugin:
    name = "approval"
    provides = (PipelineStage, FreezeReader)
    requires = _DEPS

    def setup(self, reg: PluginView) -> None:
        module = create_approval(_deps(reg))
        reg.provide(FreezeReader, module.freeze_reader)
        for stage in module.stages():
            reg.add(PipelineStage, stage)


class ApprovalServicePlugin:
    name = "approval.service"
    provides = (APIRouter,)
    requires = (*_DEPS, UnitOfWorkFactory, CommandExecutor, ContextProvider)

    def setup(self, reg: PluginView) -> None:
        service = ApprovalService(_deps(reg), reg.get(UnitOfWorkFactory), reg.get(CommandExecutor))
        reg.add(APIRouter, approval_router(service, reg.get(ContextProvider).context))
