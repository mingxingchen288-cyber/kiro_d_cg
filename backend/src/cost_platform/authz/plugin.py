"""authz 插件（`.reports/modules/plugin-spec.md` 第 2 节）：`PermissionChecker` 和管道阶段"操作权限"。

权限是纯计算，只读执行上下文中的配置快照，不依赖别的端口；阶段和检查器用同一个 `RolePermissionChecker`。
"""

from __future__ import annotations

from cost_platform.contracts.ports import PermissionChecker, PipelineStage
from cost_platform.contracts.registry import PluginView

from .checker import RolePermissionChecker
from .stage import OperationPermissionStage

__all__ = ["AuthzPlugin"]


class AuthzPlugin:
    name = "authz"
    provides = (PermissionChecker, PipelineStage)
    requires = ()

    def setup(self, reg: PluginView) -> None:
        checker = RolePermissionChecker()
        reg.provide(PermissionChecker, checker)
        reg.add(PipelineStage, OperationPermissionStage(checker))
