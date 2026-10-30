"""orchestration 的 `CommandRunner`（模拟验证）：按 STAGE_ORDER 执行各位置的阶段、按钮每个动作一轮、提交后投递、
命令事务包在命令审查（`FakeCommandMonitor`）中，以及 `CommandExecutor` 的契约测试。各模块的阶段用 contracts 的替代阶段 `FakeStage`；命令记录用本文件的内存实现
（`CommandRecorder` 没有替代实现，真实实现在 tests/pipeline 中验证）。"""

from __future__ import annotations

from typing import Any

import pytest

from cost_platform.contracts.fakes import FakeCommandMonitor, FakeDeliveryDispatcher, FakeStage, FakeUnitOfWorkFactory
from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    Command,
    CommandResult,
    CommandState,
    DocumentData,
    DocumentRef,
    ErrorCode,
    ExecutionContext,
    LockScopeChanged,
    PlatformError,
    Row,
    RowIntent,
)
from cost_platform.orchestration.runner import ACTION_ROUND, STAGE_ORDER, CommandRunner, stage_problems

from ..contracts.support import context, sample_command
from ..contracts.test_command_executor import CommandExecutorContract

DOC = DocumentRef(entity="COST_PINGGU", record_key="200680")
OTHER = DocumentRef(entity="COST_PINGGU", record_key="2550")


class MemoryRecorder:
    """命令记录的内存实现：完成的命令按（用户、请求键）记住结果和内容摘要；结果为 unchanged 时不记。"""

    def __init__(self) -> None:
        self.done: dict[tuple[str, str], tuple[str, CommandResult]] = {}

    def begin(self, uow: UnitOfWork, user_id: str, command: Command, now: Any) -> CommandResult | None:
        found = self.done.get((user_id, command.request_key))
        if found is None:
            return None
        if found[0] != command.content_digest():
            raise PlatformError(ErrorCode.IDEMPOTENCY_KEY_REUSED, "请求键已用于另一个命令")
        return found[1]

    def finish(self, *args: Any) -> None:  # 编排不调用
        raise AssertionError("编排应调用 complete")

    def complete(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> CommandResult:
        outcome = "saved" if state.involved else "unchanged"
        result = CommandResult(request_key=state.command.request_key, outcome=outcome, rows=[], id_map={}, prompts=[],
                               skipped=[], approvals=[])
        if outcome != "unchanged":
            self.done[(ctx.identity.user_id, state.command.request_key)] = (state.command.content_digest(), result)
        return result


def _document(ref: DocumentRef) -> DocumentData:
    return DocumentData(ref=ref, master=Row(entity=ref.entity, row_key=ref.record_key, client_row_id=None, values={}), details={})


def _unread(state: CommandState) -> list[DocumentRef]:
    return [r for r in dict.fromkeys([*state.involved, *(i.document for i in state.intents)]) if r not in state.current]


def _lock(_uow: UnitOfWork, state: CommandState, _ctx: ExecutionContext) -> None:
    for ref in _unread(state):
        if ref not in state.involved:
            state.involved.append(ref)
        state.current[ref] = _document(ref)


class Stages:
    """每个位置一个替代阶段，按执行的先后记下（位置、冻结检查时的 involved）。"""

    def __init__(self, actions: list[DocumentRef] | None = None) -> None:
        self.log: list[str] = []
        self.frozen_checked: list[list[DocumentRef]] = []
        pending = list(actions or [])

        def noted(name: str, effect: Any = None) -> Any:
            def run(uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
                self.log.append(name)
                if name == "冻结检查":
                    self.frozen_checked.append(list(state.involved))
                if effect is not None:
                    effect(uow, state, ctx)
            return run

        def expand(_uow: UnitOfWork, state: CommandState, _ctx: ExecutionContext) -> None:
            ref = pending.pop(0)
            state.intents.append(RowIntent(document=ref, entity=ref.entity, op="modify", row_key=ref.record_key,
                                           client_row_id=None, values={"MEMO": "同步"}))

        special = {
            "确定涉及的单据": (True, lambda _u, s, _c: s.involved.append(DOC)),
            "加锁读取": (lambda s, _c: bool(_unread(s)), _lock),
            "展开动作": (lambda _s, _c: bool(pending), expand),
            "合并意图": (lambda s, _c: bool(s.intents), lambda _u, s, _c: s.intents.clear()),
            "登记通知": (True, lambda _u, s, _c: s.delivery_ids.append("00000000-0000-4000-8000-0000000000d1")),
        }
        self.stages = [FakeStage(name, applies=special.get(name, (True, None))[0],
                                 effect=noted(name, special.get(name, (True, None))[1])) for name in STAGE_ORDER]


def runner(stages: Stages, dispatcher: FakeDeliveryDispatcher | None = None,
           monitor: FakeCommandMonitor | None = None) -> CommandRunner:
    return CommandRunner(FakeUnitOfWorkFactory(), MemoryRecorder(), monitor or FakeCommandMonitor(),
                         dispatcher or FakeDeliveryDispatcher(), stages.stages)


# ---------------------------------------------------------------- 执行顺序

AFTER_ROUND = ["触发审批", "强制审批检查", "写入变更", "登记通知"]


def test_page_save_runs_each_position_once_in_order() -> None:
    """页面保存（没有动作）：按 STAGE_ORDER 各执行一次；第 7 步没有展开动作，加锁读取没有新单据要读、合并意图没有意图，
    这两步不再执行。"""
    stages = Stages()
    result = runner(stages).execute(sample_command(), context())
    assert result.outcome == "saved"
    assert stages.log == ["操作权限", "确定涉及的单据", "加锁读取", "冻结检查", "审批处理", "合并修改", "计算与规则",
                          *AFTER_ROUND]


def test_button_with_two_actions_runs_one_round_per_action() -> None:
    """按钮两个动作：每个动作一轮。第一个动作找到的成本单 2550 先加锁读取、再只对它做冻结检查，然后合并、计算；
    第二个动作的目标已经读入，不再加锁和检查。"""
    stages = Stages(actions=[OTHER, DOC])
    runner(stages).execute(sample_command(), context())
    round_one = ["展开动作", "加锁读取", "冻结检查", "合并意图", "计算与规则"]
    round_two = ["展开动作", "合并意图", "计算与规则"]
    assert stages.log == ["操作权限", "确定涉及的单据", "加锁读取", "冻结检查", "审批处理", "合并修改", *round_one, *round_two,
                          *AFTER_ROUND]
    assert stages.frozen_checked == [[DOC], [OTHER]]
    assert set(ACTION_ROUND) <= set(STAGE_ORDER)


def test_deliveries_dispatched_after_commit() -> None:
    dispatcher = FakeDeliveryDispatcher()
    runner(Stages(), dispatcher).execute(sample_command(), context())
    assert dispatcher.dispatched == [["00000000-0000-4000-8000-0000000000d1"]]


# ---------------------------------------------------------------- 命令审查（WP-17）

class _Dispatcher(FakeDeliveryDispatcher):
    """投递时记下命令审查已经记了几条：投递在 watch 之后。"""

    def __init__(self, monitor: FakeCommandMonitor) -> None:
        super().__init__()
        self._monitor = monitor
        self.watched_at_dispatch: list[int] = []

    def dispatch_now(self, delivery_ids: list[str]) -> None:
        self.watched_at_dispatch.append(len(self._monitor.watched))
        super().dispatch_now(delivery_ids)


def test_saved_command_goes_through_monitor_before_dispatch() -> None:
    """成本单 200680 保存成功：判重到提交整个事务包在 watch 中，记为成功；提交后的投递在 watch 之后。"""
    monitor = FakeCommandMonitor()
    dispatcher = _Dispatcher(monitor)
    command = sample_command()
    result = runner(Stages(), dispatcher, monitor).execute(command, context())
    assert result.outcome == "saved"
    assert monitor.watched == [(command.request_key, None)]
    assert dispatcher.watched_at_dispatch == [1]


def test_rejected_command_goes_through_monitor() -> None:
    """成本单 200680 被审批冻结，保存被拒绝：错误照常抛出，事务回滚，命令审查记下这个错误码；没有投递。"""
    monitor = FakeCommandMonitor()
    dispatcher = FakeDeliveryDispatcher()
    stages = Stages()
    next(s for s in stages.stages if s.name == "冻结检查").fail(
        "run", PlatformError(ErrorCode.FROZEN_BY_APPROVAL, "单据已被审批冻结"))
    command = sample_command()
    with pytest.raises(PlatformError) as caught:
        runner(stages, dispatcher, monitor).execute(command, context())
    assert caught.value.code is ErrorCode.FROZEN_BY_APPROVAL
    assert monitor.watched == [(command.request_key, ErrorCode.FROZEN_BY_APPROVAL)]
    assert dispatcher.dispatched == []


def test_lock_scope_changed_rolls_back_and_runs_the_command_again() -> None:
    """规则 4（WP-13 的例外）：加锁前读到的本命令单据在锁住时已被别人改了，"触发审批"抛 LockScopeChanged；整个事务回滚
    （第一次的事务没有提交），整条命令重来一次，第二次提交。命令审查只记一条。"""
    stages = Stages()
    next(s for s in stages.stages if s.name == "触发审批").fail("run", LockScopeChanged("物料清单 25 在加锁前读取之后被修改"))
    factory = FakeUnitOfWorkFactory()
    monitor = FakeCommandMonitor()
    command = sample_command()
    result = CommandRunner(factory, MemoryRecorder(), monitor, FakeDeliveryDispatcher(), stages.stages).execute(command, context())
    assert result.outcome == "saved"
    assert [(u.committed, u.rolled_back) for u in factory.units] == [(False, True), (True, False)]
    assert stages.log.count("确定涉及的单据") == 2 and stages.log.count("写入变更") == 1
    assert monitor.watched == [(command.request_key, None)]


def test_stage_names_checked_against_stage_order() -> None:
    """启动检查（orchestration 插件在 setup 中调用）：name 不在列表里、列表里的位置没有实现，都列出来。"""
    stages = [s for s in Stages().stages if s.name != "合并意图"] + [FakeStage("动作执行")]
    assert stage_problems(stages) == [
        "管道阶段 cost_platform.contracts.fakes.pipeline.FakeStage 的 name「动作执行」不在 STAGE_ORDER 中",
        "STAGE_ORDER 的位置「合并意图」没有任何实现"]
    assert stage_problems(Stages().stages) == []


# ---------------------------------------------------------------- CommandExecutor 的契约测试

class RunnerHarness:
    def __init__(self) -> None:
        self.stage_set = Stages()
        self.executor = runner(self.stage_set)
        self._merge = next(s for s in self.stage_set.stages if s.name == "合并修改")

    def context(self, user_id: str) -> ExecutionContext:
        return context(user_id)

    def command(self, request_key: str, *, variant: int = 0) -> Command:
        return sample_command(requestKey=request_key, params={"variant": variant})

    def fail_next(self, error: PlatformError) -> None:
        self._merge.fail("run", error)

    def executions(self) -> int:
        return self.stage_set.log.count("操作权限")


class TestCommandRunner(CommandExecutorContract):
    @pytest.fixture
    def harness(self) -> RunnerHarness:
        return RunnerHarness()
