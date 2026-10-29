"""`PageSaveInvolved`（"确定涉及的单据"的页面保存部分）通过 `PipelineStage` 的契约测试（C08 第 6、14 节）：只写 `involved`。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack

import pytest

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeUnitOfWorkFactory
from cost_platform.pipeline.loader import PageSaveInvolved
from tests.contracts.test_pipeline_stage import PipelineStageContract, StageCase

from .support import MASTER, MATERIAL, TMP_1, Setup, command, master_modify, master_none


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
