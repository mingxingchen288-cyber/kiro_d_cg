"""E01 经本模块的管道阶段：与 plugin.py 相同的组装（`RowStore` 为 `OracleDocumentStore(5)`），按 orchestration 的执行方式
（`STAGE_ORDER`，plugin-spec 第 3 节）完成 E01 的保存，发出的语句为 4 条。

原来测的是 orchestration 的 `SaveFlow`、`CommandRunner`（2026-10-29 删除）；场景和断言不变。E01 中 MEMO 不是保存时规则读取的
字段（用户 2026-10-29 选定只改这类字段时不读明细、不求值，WP-08），所以快照的 `rule_fields` 为空。

只核对语句（不连数据库）；E01 在 d_cg 上的真实联调见 `backend/tests/e2e/test_e01.py`。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

from cost_platform.contracts import types as t
from cost_platform.contracts.ports import PipelineStage
from cost_platform.pipeline.calc import Recalculator
from cost_platform.pipeline.command_log import OracleCommandRecorder
from cost_platform.pipeline.document_store import OracleDocumentStore
from cost_platform.pipeline.loader import DocumentLoader, PageSaveInvolved
from cost_platform.pipeline.merge import DocumentMerger, IntentMerger
from cost_platform.pipeline.stages import LockStage, MergeIntentsStage, MergePatchesStage, RecalculateStage, WriteChangesStage
from cost_platform.pipeline.writer import ChangeWriter

from .recording import RecordingUnitOfWork
from .support import PAGE, Setup, command, master_modify, run_stages


class Factory:
    def __init__(self) -> None:
        self.units: list[RecordingUnitOfWork] = []

    @contextmanager
    def begin(self) -> Iterator[RecordingUnitOfWork]:
        uow = RecordingUnitOfWork()
        uow.connection.results = [[(Decimal(1001), "250mg乙酰唑胺片", None, Decimal(100000), Decimal("54.00"), "王五", "草稿",
                                    datetime(2026, 1, 5, 9, 0))]]
        self.units.append(uow)
        yield uow


def test_e01_through_pipeline_stages() -> None:
    setup = Setup(rule_fields={PAGE: {}})
    store = OracleDocumentStore(5)
    loader = DocumentLoader(store, setup.permission)
    stages: list[PipelineStage] = [
        PageSaveInvolved(), LockStage(loader), MergePatchesStage(DocumentMerger(setup.permission)),
        MergeIntentsStage(IntentMerger(loader)), RecalculateStage(Recalculator(setup.engine)), WriteChangesStage(ChangeWriter(store))]
    recorder = OracleCommandRecorder()
    factory = Factory()
    cmd = command([master_modify("1001", {"MEMO": "测试"})])
    ctx = setup.context()
    with factory.begin() as uow:
        assert recorder.begin(uow, ctx.identity.user_id, cmd, ctx.now) is None
        state = t.CommandState(command=cmd)
        run_stages(stages, uow, state, ctx)
        result = recorder.complete(uow, state, ctx)
    assert result.outcome == "saved" and result.rows[0].values["MEMO"] == "测试"  # type: ignore[union-attr]
    assert setup.engine.calls_to("evaluate") == []  # 只改了规则不读的字段，不求值
    [uow] = factory.units
    assert [s.split(" ")[0] for s in uow.connection.sql] == ["INSERT", "SELECT", "UPDATE", "UPDATE"]
    assert uow.connection.sql[2] == "UPDATE T_COST_PINGGU SET MEMO = :v0 WHERE DOCID = :pk"
