"""`PipelineStage` 的契约测试（C08 第 6 节、第 14 节）：每个阶段只写 C08 第 6 节表中它负责的字段。

表中每个阶段可以写哪些字段，直接从 C08 读取。真实实现（authz、operations、approval、delivery）的测试继承
`PipelineStageContract`，提供 `harness` fixture，实现 `PipelineStageHarness`：给出一组场景，每个场景指明
阶段属于表中哪一行。
"""

from __future__ import annotations

import copy
import dataclasses
import re
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeStage, FakeUnitOfWorkFactory
from cost_platform.contracts.ports import PipelineStage, UnitOfWork
from cost_platform.contracts.types import (
    ApprovalState,
    ApplyPendingChanges,
    ChangePlan,
    CommandState,
    DocumentData,
    DocumentRef,
    ErrorCode,
    ExecutionContext,
    NotificationIntent,
    PlatformError,
    PromptEffect,
    RecordRef,
    Row,
    RowChange,
    SkippedRow,
)
from cost_platform.contracts.types import Prompt as PromptItem

from .support import DOCS, context, sample_command


def _stage_table() -> dict[str, frozenset[str]]:
    """C08 第 6 节的阶段表：阶段名称 -> 可以写的 CommandState 字段。"""
    text = next(DOCS.glob("C08-*.md")).read_text(encoding="utf-8")
    section = text.split("## 6. 管道阶段", 1)[1].split("\n## ", 1)[0]
    table: dict[str, frozenset[str]] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) != 4 or cells[0] in ("阶段", "---"):
            continue
        written = cells[3].split("；", 1)[0]
        table[cells[0]] = frozenset() if written.startswith("无") else frozenset(re.findall(r"`([a-z_]+)`", written))
    return table


STAGE_WRITES = _stage_table()
STATE_FIELDS = frozenset(f.name for f in dataclasses.fields(CommandState))
# 阶段失败时 C08 第 6 节写明的错误码
STAGE_ERRORS = {"操作权限": ErrorCode.PERMISSION_DENIED, "冻结检查": ErrorCode.FROZEN_BY_APPROVAL}


@dataclass
class StageCase:
    """一个场景：`stage` 属于阶段表中的 `kind`，在 `state`、`ctx` 下 `applies` 为 True。"""

    kind: str
    stage: PipelineStage
    state: CommandState
    ctx: ExecutionContext
    uow: UnitOfWork


class PipelineStageHarness(Protocol):
    def cases(self) -> list[StageCase]:
        """阶段运行成功的场景。"""
        ...

    def failing_cases(self) -> list[StageCase]:
        """阶段不通过、抛出 PlatformError 的场景；`操作权限`、`冻结检查` 的错误码必须是 C08 写明的。"""
        ...


def _changed_fields(before: CommandState, after: CommandState) -> set[str]:
    return {name for name in STATE_FIELDS if getattr(before, name) != getattr(after, name)}


class PipelineStageContract:
    @pytest.fixture
    def harness(self) -> PipelineStageHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_stage_kinds_are_in_table(self, harness: PipelineStageHarness) -> None:
        for case in harness.cases() + harness.failing_cases():
            assert case.kind in STAGE_WRITES, case.kind

    def test_stage_has_name(self, harness: PipelineStageHarness) -> None:
        for case in harness.cases():
            assert isinstance(case.stage.name, str) and case.stage.name

    def test_applies_does_not_change_state(self, harness: PipelineStageHarness) -> None:
        for case in harness.cases():
            before = copy.deepcopy(case.state)
            assert case.stage.applies(case.state, case.ctx) is True
            assert _changed_fields(before, case.state) == set(), case.kind

    def test_run_writes_only_own_fields(self, harness: PipelineStageHarness) -> None:
        for case in harness.cases():
            before = copy.deepcopy(case.state)
            case.stage.run(case.uow, case.state, case.ctx)
            extra = _changed_fields(before, case.state) - STAGE_WRITES[case.kind]
            assert extra == set(), f"{case.kind} 阶段写了不属于它的字段 {sorted(extra)}"

    def test_failure_is_platform_error(self, harness: PipelineStageHarness) -> None:
        for case in harness.failing_cases():
            with pytest.raises(PlatformError) as caught:
                case.stage.run(case.uow, case.state, case.ctx)
            if case.kind in STAGE_ERRORS:
                assert caught.value.code is STAGE_ERRORS[case.kind], case.kind


# ---------------------------------------------------------------- 替代实现：每个阶段写满表中它负责的字段

_REF = DocumentRef(entity="COST_PINGGU", record_key="1001")
_DOC = DocumentData(ref=_REF, master=Row(entity="COST_PINGGU", row_key="1001", client_row_id=None, values={"QTY": "12"}), details={})
_APPROVAL = ApprovalState(approval_id="203", document=RecordRef(entity="COST_PINGGU", record_key="1001"), status="pending", level=1,
                          flows=["COST_TO_GOODS"])
_NOTICE = NotificationIntent(event="approvalSubmitted", recipients=("111",), title="审批", body="", link="/approval/203")

_WRITERS = {
    "involved": lambda s: s.involved.append(_REF),
    "actions": lambda s: s.actions.append(ApplyPendingChanges(action="applyPendingChanges")),
    "candidate": lambda s: s.candidate.__setitem__(_REF, copy.deepcopy(_DOC)),
    "effects": lambda s: s.effects.append(PromptEffect(kind="prompt", rule="R1", message="提示")),
    "changes": lambda s: s.changes.rows.append(RowChange(document=_REF, entity="COST_PINGGU", op="modify", row_key="1001",
                                                         client_row_id=None, values={"QTY": "12"}, old={"QTY": "10"})),
    "prompts": lambda s: s.prompts.append(PromptItem(rule="R1", message="提示")),
    "skipped": lambda s: s.skipped.append(SkippedRow(entity="COST_MATERIAL", row_key="5003", reason="ROW_NOT_FOUND")),
    "approvals": lambda s: s.approvals.append(_APPROVAL),
    "pending_documents": lambda s: s.pending_documents.add(_REF),
    "outcome": lambda s: setattr(s, "outcome", "approvalSubmitted"),
    "notifications": lambda s: s.notifications.append(_NOTICE),
    "delivery_ids": lambda s: s.delivery_ids.append("00000000-0000-4000-8000-0000000000d1"),
}


def writing_stage(kind: str, fields: frozenset[str] | set[str]) -> FakeStage:
    """一个写 `fields` 中每个字段的替代阶段。"""
    def effect(uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        for field in sorted(fields):
            _WRITERS[field](state)
    return FakeStage(kind, effect=effect)


def fresh_state() -> CommandState:
    state = CommandState(command=sample_command())
    state.involved.append(_REF)
    state.current[_REF] = copy.deepcopy(_DOC)
    state.changes = ChangePlan()
    return state


class FakeStageHarness:
    """各场景共用一个打开的事务，`close` 时回滚。"""

    def __init__(self) -> None:
        self._stack = ExitStack()
        self._uow = self._stack.enter_context(FakeUnitOfWorkFactory().begin())

    def close(self) -> None:
        self._stack.close()

    def _case(self, kind: str, stage: FakeStage) -> StageCase:
        return StageCase(kind=kind, stage=stage, state=fresh_state(), ctx=context(), uow=self._uow)

    def cases(self) -> list[StageCase]:
        return [self._case(kind, writing_stage(kind, fields)) for kind, fields in STAGE_WRITES.items()]

    def failing_cases(self) -> list[StageCase]:
        cases = []
        for kind, code in STAGE_ERRORS.items():
            stage = FakeStage(kind)
            stage.fail("run", PlatformError(code, kind))
            cases.append(self._case(kind, stage))
        return cases


class TestFakeStage(PipelineStageContract):
    @pytest.fixture
    def harness(self) -> Iterator[FakeStageHarness]:
        harness = FakeStageHarness()
        yield harness
        harness.close()


def test_table_covers_every_stage_and_known_fields() -> None:
    """C08 第 6 节的表读出 8 个阶段，写入的字段都是 CommandState 的字段，替代实现能写每个字段。"""
    assert set(STAGE_WRITES) == {"操作权限", "确定涉及的单据", "冻结检查", "审批处理", "动作执行", "触发审批", "登记通知", "投递"}
    written = set().union(*STAGE_WRITES.values())
    assert written <= STATE_FIELDS
    assert written <= set(_WRITERS)
    assert STAGE_WRITES["冻结检查"] == frozenset()
    assert STAGE_WRITES["触发审批"] == frozenset({"approvals", "pending_documents", "outcome", "notifications"})


def test_detects_stage_writing_foreign_field() -> None:
    """契约测试能发现写了别的阶段字段的实现：冻结检查阶段写了 candidate。"""
    harness = FakeStageHarness()
    case = harness._case("冻结检查", writing_stage("冻结检查", {"candidate"}))
    before = copy.deepcopy(case.state)
    case.stage.run(case.uow, case.state, case.ctx)
    harness.close()
    assert _changed_fields(before, case.state) - STAGE_WRITES["冻结检查"] == {"candidate"}
