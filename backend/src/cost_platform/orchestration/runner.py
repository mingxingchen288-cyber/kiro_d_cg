"""命令执行（`CommandExecutor`，C08 第 5 节）：一个命令一个事务，按 `STAGE_ORDER` 执行各模块的管道阶段。

管道阶段的顺序只在这里定义（用户 2026-10-29 定）。每个阶段的 `name` 是下面的一个位置名；同一位置的几个实现（例如
"确定涉及的单据"由 write-pipeline、operations、approval 各实现一个）由各自的 `applies` 决定这次执行哪个。不用数字顺序号。

一个命令：
1. `CommandRecorder.begin`：判重（WP-01）；同一请求键已完成且内容相同时直接返回原结果。
2. 按 `STAGE_ORDER` 执行各位置上 `applies` 为真的阶段。架构第 7 节第 7 步"每个动作一轮"：到"展开动作"时，只要有展开动作的
   阶段 applies，就一轮轮执行 `ACTION_ROUND`——展开动作 → 加锁读取 → 冻结检查（只查这一轮新读入的单据，WP-18）→ 合并意图
   → 计算与规则；没有动作的命令（页面保存、审批处理）这几步（不含展开动作）执行一次。
3. `CommandRecorder.complete`：命令结果、审计、逃生舱调用记录、命令记录（WP-11、WP-12、OP-04）；结果为 unchanged 时不提交
   （事务回滚，命令记录一起撤销）。
4. 提交后投递：`DeliveryDispatcher.dispatch_now`（DL-02）。"投递"不是阶段位置。

第 1–3 步和提交或回滚包在 `CommandMonitor.watch` 中（命令审查 WP-17，C08 第 5a 节）：成功、被拒绝、出错的命令都在事务结束
之后记一条；投递在 watch 之后，不算在命令里。判重、命令结果和审计、提交是命令事务本身，不是阶段位置（C08 第 6 节）。
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from cost_platform.contracts.ports import (
    CommandMonitor,
    CommandRecorder,
    DeliveryDispatcher,
    PipelineStage,
    UnitOfWork,
    UnitOfWorkFactory,
)
from cost_platform.contracts.types import Command, CommandResult, CommandState, ExecutionContext

STAGE_ORDER: tuple[str, ...] = (
    "操作权限",          # 架构第 7 节第 2 步：authz
    "确定涉及的单据",     # 第 3 步：write-pipeline（页面保存）、operations（按钮）、approval（审批处理）
    "加锁读取",          # 第 4 步：write-pipeline
    "冻结检查",          # 第 5 步：approval
    "审批处理",          # 第 6 步：approval
    "合并修改",          # 第 7 步：write-pipeline（页面保存的 Patch）
    "展开动作",          # 第 7 步：operations（按钮的通用动作），每个动作一轮
    "合并意图",          # 第 7 步：write-pipeline
    "计算与规则",         # 第 7 步：write-pipeline（rules-core 求值、必填）
    "触发审批",          # 第 8 步：approval
    "强制审批检查",       # 第 8 步：approval
    "写入变更",          # 第 9 步：write-pipeline
    "登记通知",          # 第 11 步：delivery
)
"""管道阶段的位置，按执行的先后（架构第 7 节）。"""

ACTION_ROUND: tuple[str, ...] = ("展开动作", "加锁读取", "冻结检查", "合并意图", "计算与规则")
"""第 7 步每个动作一轮执行的位置（都在 `STAGE_ORDER` 中）。"""


def stage_problems(stages: Sequence[PipelineStage]) -> list[str]:
    """阶段与 `STAGE_ORDER` 对不上的地方：阶段的 name 不在列表里；列表里某个位置没有任何实现。"""
    names = {s.name for s in stages}
    problems = [f"管道阶段 {type(s).__module__}.{type(s).__qualname__} 的 name「{s.name}」不在 STAGE_ORDER 中"
                for s in stages if s.name not in STAGE_ORDER]
    problems += [f"STAGE_ORDER 的位置「{name}」没有任何实现" for name in STAGE_ORDER if name not in names]
    return problems


class CommandRunner:
    """`CommandExecutor`。`stages` 为各模块注册的全部管道阶段（注册表的 `all(PipelineStage)`），按位置分组，
    同一位置内保持注册的先后；`monitor` 为命令审查。"""

    def __init__(self, uow_factory: UnitOfWorkFactory, recorder: CommandRecorder, monitor: CommandMonitor,
                 dispatcher: DeliveryDispatcher, stages: Sequence[PipelineStage]) -> None:
        self._uow = uow_factory
        self._recorder = recorder
        self._monitor = monitor
        self._dispatcher = dispatcher
        self._at = {name: [s for s in stages if s.name == name] for name in STAGE_ORDER}

    def execute(self, command: Command, ctx: ExecutionContext) -> CommandResult:
        with self._monitor.watch(command, ctx):
            result, deliveries = self._transaction(command, ctx)
        if deliveries:
            self._dispatcher.dispatch_now(deliveries)
        return result

    def _transaction(self, command: Command, ctx: ExecutionContext) -> tuple[CommandResult, list[str]]:
        """命令事务：判重 → 各阶段 → complete → 提交。返回命令结果和提交后要投递的编号；判重命中、结果为 unchanged
        （不提交，事务回滚）时没有要投递的。"""
        with self._uow.begin() as uow:
            replay = self._recorder.begin(uow, ctx.identity.user_id, command, ctx.now)
            if replay is not None:
                return replay, []
            state = CommandState(command=command)
            self._run(uow, state, ctx)
            result = self._recorder.complete(uow, state, ctx)
            if result.outcome == "unchanged":
                return result, []
            uow.commit()
        return result, list(state.delivery_ids)

    # ---------------------------------------------------------------- 按 STAGE_ORDER 执行

    def _position(self, name: str, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        for stage in self._at[name]:
            if stage.applies(state, ctx):
                stage.run(uow, state, ctx)

    def _round_tail(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        """一轮中展开动作之后的几步：新找到的单据先加锁读取、再做冻结检查，通过后才合并（WP-18）。"""
        before = set(state.current)
        self._position("加锁读取", uow, state, ctx)
        loaded = [ref for ref in state.current if ref not in before]
        if loaded:
            self._position("冻结检查", uow, dataclasses.replace(state, involved=loaded), ctx)
        self._position("合并意图", uow, state, ctx)
        self._position("计算与规则", uow, state, ctx)

    def _run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        first, last = STAGE_ORDER.index(ACTION_ROUND[0]), STAGE_ORDER.index(ACTION_ROUND[-1])
        for name in STAGE_ORDER[:first]:
            self._position(name, uow, state, ctx)
        expanders = self._at[ACTION_ROUND[0]]
        rounds = 0
        while any(stage.applies(state, ctx) for stage in expanders):
            self._position(ACTION_ROUND[0], uow, state, ctx)
            self._round_tail(uow, state, ctx)
            rounds += 1
        if rounds == 0:
            self._round_tail(uow, state, ctx)
        for name in STAGE_ORDER[last + 1:]:
            self._position(name, uow, state, ctx)
