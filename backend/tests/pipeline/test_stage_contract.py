"""本模块的管道阶段通过 `PipelineStage` 的契约测试（C08 第 6、14 节）：每个阶段只写 C08 第 6 节表中它负责的字段。

- 确定涉及的单据（`PageSaveInvolved`）：只写 `involved`；
- 加锁读取（`LockStage`）：`involved`、`current`、`skipped`；
- 合并修改（`MergePatchesStage`）：`candidate`、`changes`；
- 合并意图（`MergeIntentsStage`）：`intents`、`candidate`、`changes`、`skipped`；
- 计算与规则（`RecalculateStage`）：`candidate`、`effects`、`changes`、`prompts`；
- 写入变更（`WriteChangesStage`）：`changes`。

场景取成本单 1001（业务例子 E01、E02 的形状），数据在 `MemoryStore` 中。"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import ExitStack
from decimal import Decimal

import pytest

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeUnitOfWorkFactory
from cost_platform.contracts.ports import PipelineStage
from cost_platform.pipeline.loader import PageSaveInvolved
from tests.contracts.test_pipeline_stage import PipelineStageContract, StageCase

from .support import MASTER, MATERIAL, TMP_1, Pipeline, Setup, command, master_modify, master_none


class InvolvedHarness:
    kinds = frozenset({"确定涉及的单据"})

    def __init__(self) -> None:
        self._stack = ExitStack()
        self._uow = self._stack.enter_context(FakeUnitOfWorkFactory().begin())

    def close(self) -> None:
        self._stack.close()

    def cases(self) -> list[StageCase]:
        cmd = command([master_modify("1002", {"MEMO": "b"}),
                       master_none("1001", [{"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {"PRICE": "3.80"}}]),
                       {"entity": MASTER, "master": {"op": "add", "clientRowId": TMP_1, "values": {}}, "details": []}])
        return [StageCase(kind="确定涉及的单据", stage=PageSaveInvolved(), state=t.CommandState(command=cmd),
                          ctx=Setup().context(), uow=self._uow)]

    def failing_cases(self) -> list[StageCase]:
        return []


class TestPageSaveInvolved(PipelineStageContract):
    @pytest.fixture
    def harness(self) -> Iterator[InvolvedHarness]:
        harness = InvolvedHarness()
        yield harness
        harness.close()


def test_involved_sorted_by_entity_and_key() -> None:
    case = InvolvedHarness().cases()[0]
    case.stage.run(case.uow, case.state, case.ctx)
    assert case.state.involved == [t.DocumentRef(MASTER, "1001"), t.DocumentRef(MASTER, "1002"), t.DocumentRef(MASTER, TMP_1)]


# ---------------------------------------------------------------- 加锁读取、合并修改、合并意图、计算与规则、写入变更

PRICE_CHANGE = [master_none("1001", [{"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {"PRICE": "3.80"}}])]


class StagesHarness:
    kinds = frozenset({"加锁读取", "合并修改", "合并意图", "计算与规则", "写入变更"})

    def __init__(self) -> None:
        self._stack = ExitStack()
        self._uow = self._stack.enter_context(FakeUnitOfWorkFactory().begin())

    def close(self) -> None:
        self._stack.close()

    def _stage(self, pipeline: Pipeline, name: str) -> PipelineStage:
        return next(s for s in pipeline.stages if s.name == name)

    def _state(self, pipeline: Pipeline, ctx: t.ExecutionContext, until: list[str],
               intents: Sequence[t.RowIntent] = ()) -> t.CommandState:
        """把 E02 形状的命令（改 1001 的 5001 的 PRICE）执行到 `until` 中的各阶段为止。"""
        state = t.CommandState(command=command(PRICE_CHANGE))
        for name in ["确定涉及的单据", *until]:
            self._stage(pipeline, name).run(self._uow, state, ctx)  # type: ignore[arg-type]
        state.intents.extend(intents)
        return state

    def cases(self) -> list[StageCase]:
        found = []
        for kind, until, intents in [
            ("加锁读取", [], []),
            ("合并修改", ["加锁读取"], []),
            ("合并意图", ["加锁读取"], [t.RowIntent(document=t.DocumentRef(MASTER, "1001"), entity=MATERIAL, op="modify",
                                                 row_key="5002", client_row_id=None, values={"PRICE": Decimal("46")})]),
            ("计算与规则", ["加锁读取", "合并修改"], []),
            ("写入变更", ["加锁读取", "合并修改", "计算与规则"], []),
        ]:
            pipeline = Pipeline()
            ctx = pipeline.setup.context()
            state = self._state(pipeline, ctx, until, intents)
            found.append(StageCase(kind=kind, stage=self._stage(pipeline, kind), state=state, ctx=ctx, uow=self._uow))
        return found

    def failing_cases(self) -> list[StageCase]:
        return []


class TestPipelineStages(PipelineStageContract):
    @pytest.fixture
    def harness(self) -> Iterator[StagesHarness]:
        harness = StagesHarness()
        yield harness
        harness.close()


def test_lock_stage_adds_intent_documents_sorted() -> None:
    """WP-18：intents 所属的单据 1002 不在 `involved` 中，"加锁读取"把它加入 `involved` 并读入（连同明细）。"""
    pipeline = Pipeline()
    ctx = pipeline.setup.context()
    harness = StagesHarness()
    state = harness._state(pipeline, ctx, ["加锁读取"], [
        t.RowIntent(document=t.DocumentRef(MASTER, "1002"), entity=MATERIAL, op="modify", row_key="5101", client_row_id=None,
                    values={"PRICE": Decimal("3.80")})])
    lock = harness._stage(pipeline, "加锁读取")
    assert lock.applies(state, ctx)
    lock.run(harness._uow, state, ctx)  # type: ignore[arg-type]
    harness.close()
    assert state.involved == [t.DocumentRef(MASTER, "1001"), t.DocumentRef(MASTER, "1002")]
    assert [r.row_key for r in state.current[t.DocumentRef(MASTER, "1002")].details[MATERIAL]] == ["5101"]
    assert pipeline.store.locked == [(MASTER, ["1001"]), (MASTER, ["1002"])]
    assert not lock.applies(state, ctx)
