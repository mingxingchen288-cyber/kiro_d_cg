"""authz 的真实实现通过 `PermissionChecker` 和管道阶段的契约测试（C08 第 6、7、14 节）。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack

import pytest

from cost_platform.authz import OperationPermissionStage, RolePermissionChecker
from cost_platform.contracts.fakes import FakeUnitOfWorkFactory
from cost_platform.contracts.types import CommandState, ExecutionContext, RoleConfig

from ..contracts.support import sample_command
from ..contracts.test_permission_checker import PermissionCheckerContract
from ..contracts.test_pipeline_stage import PipelineStageContract, StageCase
from .samples import (
    COST_GOODS_PRICE,
    COST_MATERIAL,
    COST_PINGGU,
    EXPORT,
    GOODS_PRICE_MANAGE,
    SAVE,
    SYNC_PRICE,
    context,
    role,
    snapshot,
)


class RolePermissionCheckerHarness:
    """技术中心（cmx 真实权限）在成本核算页。契约要求的两项 cmx 中的技术中心没有，在真实权限上补上：
    行权限换成引用 `${userId}` 的自定义 SQL，按钮加上 001 才有的 `export:cost-pinggu-export`。"""

    allowed = (SAVE, COST_PINGGU)
    denied = (SYNC_PRICE, COST_PINGGU)
    unrestricted = (GOODS_PRICE_MANAGE, COST_GOODS_PRICE)
    restricted = (COST_PINGGU, COST_PINGGU)
    editable = (COST_PINGGU, COST_MATERIAL)
    export_allowed = (COST_PINGGU, EXPORT)
    export_denied = (COST_PINGGU, "other-export")

    def __init__(self) -> None:
        self.checker = RolePermissionChecker()
        buttons = [*role("技术中心").pages[COST_PINGGU].buttons, f"export:{EXPORT}"]
        granted = role("技术中心", **{COST_PINGGU: {"buttons": buttons, "rows": "CREATE_USER_ID = ${userId}"}})
        self._ctx = context(snapshot("技术中心", granted))

    def context(self) -> ExecutionContext:
        return self._ctx


class TestRolePermissionChecker(PermissionCheckerContract):
    @pytest.fixture
    def harness(self) -> RolePermissionCheckerHarness:
        return RolePermissionCheckerHarness()


class OperationPermissionStageHarness:
    """C02 第 1 节的保存命令（主表修改，原辅料明细新增、修改、删除）：ADMIN（`*`）通过；只有保存和原辅料修改的角色
    （端到端场景 3 新建的角色）不能改主表、不能增删原辅料，被拒。"""

    kinds = frozenset({"操作权限"})

    def __init__(self) -> None:
        self._stack = ExitStack()
        self._uow = self._stack.enter_context(FakeUnitOfWorkFactory().begin())
        self._stage = OperationPermissionStage(RolePermissionChecker())

    def close(self) -> None:
        self._stack.close()

    def _case(self, role_code: str, granted: RoleConfig | None = None) -> StageCase:
        return StageCase(kind="操作权限", stage=self._stage, state=CommandState(command=sample_command()),
                         ctx=context(snapshot(role_code, granted)), uow=self._uow)

    def cases(self) -> list[StageCase]:
        return [self._case("ADMIN")]

    def failing_cases(self) -> list[StageCase]:
        save_and_modify = role("技术中心", **{COST_PINGGU: {"buttons": ["system:save", f"{COST_MATERIAL}:modify"]}})
        return [self._case("技术中心", save_and_modify)]


class TestOperationPermissionStage(PipelineStageContract):
    @pytest.fixture
    def harness(self) -> Iterator[OperationPermissionStageHarness]:
        harness = OperationPermissionStageHarness()
        yield harness
        harness.close()
