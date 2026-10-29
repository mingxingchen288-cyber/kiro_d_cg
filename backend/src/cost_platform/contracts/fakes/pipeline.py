"""write-pipeline 的 `CommandExecutor` 和管道阶段的替代实现（C08 第 5、6 节）。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from ..ports import UnitOfWork
from ..types import Command, CommandResult, CommandState, ErrorCode, ExecutionContext, PlatformError
from ._script import Scripted

Responder = Callable[[Command, ExecutionContext], CommandResult]


def unchanged(command: Command, ctx: ExecutionContext) -> CommandResult:
    """默认的结果：没有写入任何内容。"""
    return CommandResult(request_key=command.request_key, outcome="unchanged", rows=[], id_map={}, prompts=[], skipped=[],
                         approvals=[])


class FakeCommandExecutor(Scripted):
    """`CommandExecutor`：结果由 `respond` 给出，默认为 `unchanged`。

    按 C02 第 3 节判重：同一用户、同一请求键已完成且内容摘要相同时返回原结果，不再调用 `respond`；
    摘要不同时抛 422 IDEMPOTENCY_KEY_REUSED。执行失败（预设的错误，或 `respond` 抛出的 PlatformError）
    时不留下结果，同一请求键可以重新提交（write-pipeline 的 WP-02）。`executed` 记录真正执行过的命令。
    """

    scriptable = ('execute',)

    def __init__(self, respond: Responder = unchanged) -> None:
        super().__init__()
        self.respond = respond
        self._done: dict[tuple[str, str], tuple[str, CommandResult]] = {}
        self.executed: list[tuple[Command, ExecutionContext]] = []

    def execute(self, command: Command, ctx: ExecutionContext) -> CommandResult:
        self._record("execute", command, ctx)
        key = (ctx.identity.user_id, command.request_key)
        digest = command.content_digest()
        if key in self._done:
            done_digest, result = self._done[key]
            if done_digest != digest:
                raise PlatformError(ErrorCode.IDEMPOTENCY_KEY_REUSED, "同一请求键提交了不同的内容")
            return result
        result = self.respond(command, ctx)
        self._done[key] = (digest, result)
        self.executed.append((command, ctx))
        return result


class FakeCommandMonitor(Scripted):
    """`CommandMonitor`：`watched` 按结束的先后记下（请求键、错误码），成功的命令错误码为 None，不是 PlatformError 的异常
    记为 INTERNAL_ERROR。异常照常抛出。"""

    scriptable = ('watch',)

    def __init__(self) -> None:
        super().__init__()
        self.watched: list[tuple[str, ErrorCode | None]] = []

    @contextmanager
    def watch(self, command: Command, ctx: ExecutionContext) -> Iterator[None]:
        self._record("watch", command, ctx)
        try:
            yield
        except PlatformError as error:
            self.watched.append((command.request_key, error.code))
            raise
        except BaseException:
            self.watched.append((command.request_key, ErrorCode.INTERNAL_ERROR))
            raise
        self.watched.append((command.request_key, None))


StageEffect = Callable[[UnitOfWork, CommandState, ExecutionContext], None]


class FakeStage(Scripted):
    """`PipelineStage`：`applies` 的结论和 `run` 对 `CommandState` 的修改由参数给出。

    `effect` 只应写 C08 第 6 节表中该阶段负责的字段；阶段失败时预设错误，例如
    `fail("run", PlatformError(ErrorCode.FROZEN_BY_APPROVAL, "单据已被冻结"))`。
    """

    scriptable = ('applies', 'run')

    def __init__(self, name: str, *, applies: bool | Callable[[CommandState, ExecutionContext], bool] = True,
                 effect: StageEffect | None = None) -> None:
        super().__init__()
        self.name = name
        self._applies = applies
        self._effect = effect

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        self._record("applies", state, ctx)
        return self._applies(state, ctx) if callable(self._applies) else self._applies

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        self._record("run", uow, state, ctx)
        if self._effect is not None:
            self._effect(uow, state, ctx)
