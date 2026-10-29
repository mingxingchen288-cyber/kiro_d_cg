"""authz 插件（plugin-spec 第 2、5 节）：setup 注册 `PermissionChecker` 和"操作权限"阶段。"""

from __future__ import annotations

from typing import Any

from cost_platform.authz.checker import RolePermissionChecker
from cost_platform.authz.plugin import AuthzPlugin
from cost_platform.authz.stage import OperationPermissionStage
from cost_platform.contracts.ports import PermissionChecker, PipelineStage
from cost_platform.contracts.registry import PluginView, Registry


class Probe:
    """只声明 requires 的插件：在 setup 中取出被测插件注册的实现（boot 结束后注册表冻结，不能再取）。"""

    name = "probe"
    provides: tuple[type, ...] = ()
    requires = (PermissionChecker, PipelineStage)

    def __init__(self) -> None:
        self.got: dict[type, Any] = {}

    def setup(self, reg: PluginView) -> None:
        self.got = {PermissionChecker: reg.get(PermissionChecker), PipelineStage: reg.all(PipelineStage)}


def test_setup_registers_checker_and_stage() -> None:
    probe = Probe()
    ordered = Registry().boot([probe, AuthzPlugin()])
    assert [p.name for p in ordered] == ["authz", "probe"]
    assert isinstance(probe.got[PermissionChecker], RolePermissionChecker)
    [stage] = probe.got[PipelineStage]
    assert isinstance(stage, OperationPermissionStage) and stage.name == "操作权限"
