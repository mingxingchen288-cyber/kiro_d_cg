"""operations 的两个阶段通过管道阶段的契约测试（C08 第 6、14 节）：只写阶段表中自己负责的字段。

- "确定涉及的单据"：写 `involved`、`actions`；
- "展开动作"：写 `intents`、`prompts`、`skipped`。
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest

from cost_platform.contracts import types as t

from ..contracts.test_pipeline_stage import PipelineStageContract, StageCase
from .support import (
    D,
    MASTER,
    MATERIAL,
    SYNC,
    Bench,
    command,
    cost_doc,
    detail_sql_finder,
    material,
    operation,
    ref,
    snapshot,
)

SYNC_DETAILS = {"action": "updateRecords", "find": t.dump_wire(t.TargetFinder, detail_sql_finder()),
                "fieldMapping": [{"from": f"{MATERIAL}.PRICE", "to": "PRICE"}]}


class OperationsStageHarness:
    """成本单 D 上的按钮"同步单价"：确定涉及的单据；展开 updateRecords（D 中 115 找到 A 的 6101）。
    不通过的场景：按钮命令带了 documents（400）；D 有两行 115、单价不同，同一目标行被写成两个值（422）。"""

    kinds = frozenset({"确定涉及的单据", "展开动作"})

    def __init__(self) -> None:
        self._benches: list[Bench] = []

    def close(self) -> None:
        for bench in self._benches:
            bench.close()

    def _bench(self, *, two_rows_of_115: bool = False) -> Bench:
        bench = Bench(snapshot({SYNC: operation([SYNC_DETAILS])}))
        if two_rows_of_115:
            bench.docs[ref(D)] = cost_doc(D, [material("5001", D, 115, "80"), material("5003", D, 115, "82")])
        bench.related.respond_rows(detail_sql_finder(), [{"DOC_ID": Decimal(2551), "DTL_ID": Decimal(6101)}],
                                   binds={"goodsId": Decimal(115), "docId": Decimal(D)})
        self._benches.append(bench)
        return bench

    def _involved(self, cmd: t.Command) -> StageCase:
        bench = self._bench()
        return StageCase(kind="确定涉及的单据", stage=bench.involved, state=t.CommandState(command=cmd), ctx=bench.ctx(),
                         uow=bench.uow)

    def _actions(self, **kwargs: bool) -> StageCase:
        bench = self._bench(**kwargs)
        state = bench.prepare(command(SYNC, [(MASTER, D)]))
        assert bench.stage is not None
        return StageCase(kind="展开动作", stage=bench.stage, state=state, ctx=bench.ctx(), uow=bench.uow)

    def cases(self) -> list[StageCase]:
        return [self._involved(command(SYNC, [(MASTER, D)])), self._actions()]

    def failing_cases(self) -> list[StageCase]:
        patch = {"entity": MASTER, "master": {"op": "modify", "rowKey": D, "changes": {"MEMO": "x"}}, "details": []}
        return [self._involved(command(SYNC, [(MASTER, D)], documents=[patch])), self._actions(two_rows_of_115=True)]


class TestOperationsStages(PipelineStageContract):
    @pytest.fixture
    def harness(self) -> Iterator[OperationsStageHarness]:
        harness = OperationsStageHarness()
        yield harness
        harness.close()


def test_action_stage_writes_intents_for_the_found_rows() -> None:
    """契约测试的"展开动作"场景确实展开出了修改：A 的 6101 写 80。"""
    harness = OperationsStageHarness()
    case = harness.cases()[1]
    case.stage.run(case.uow, case.state, case.ctx)
    assert [(i.document, i.entity, i.row_key, i.values) for i in case.state.intents] == \
        [(ref("2551"), MATERIAL, "6101", {"PRICE": Decimal(80)})]
    harness.close()
