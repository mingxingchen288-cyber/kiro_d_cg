"""写入管道的"操作权限"阶段（C08 第 6 节，架构第 7 节第 2 步）：只读 `command` 和 ctx，不写 CommandState。"""

from __future__ import annotations

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import CommandState, ErrorCode, ExecutionContext, PlatformError

from .checker import RolePermissionChecker, is_approval_operation


class OperationPermissionStage:
    """AZ-01：每个命令执行一次。

    - 审批处理（`approval.*`）和来源为审批的写入：只确认已选定角色（处理人由 approval 判断；写入不按某个人的权限）。
    - 其余命令：操作本身要有权限（页面保存 `system:save`，按钮操作要有引用它的按钮键，见 `can_run`），Patch 中的
      新增行、修改的已有行、删除行要有所在区域的对应权限（`patch_denials`）。不通过时抛 403 PERMISSION_DENIED，
      明细定位到行。
    """

    name = "操作权限"

    def __init__(self, checker: RolePermissionChecker | None = None) -> None:
        self._checker = checker or RolePermissionChecker()

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return True

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        command = state.command
        if not ctx.identity.role_code:
            raise PlatformError(ErrorCode.ROLE_SELECTION_REQUIRED, "请先选择角色")
        if is_approval_operation(command.operation) or ctx.origin.kind == "approval":
            return
        if not self._checker.can_run(ctx, command.operation, command.page):
            raise PlatformError(ErrorCode.PERMISSION_DENIED, f"没有执行操作 {command.operation} 的权限")
        denials = self._checker.patch_denials(ctx, command)
        if denials:
            raise PlatformError(ErrorCode.PERMISSION_DENIED, "没有新增、修改或删除这些行的权限", denials)
