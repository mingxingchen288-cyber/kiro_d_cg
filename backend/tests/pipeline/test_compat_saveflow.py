"""兼容性：orchestration 现有的 `SaveFlow`、`CommandRunner` 用本模块的 `OracleCommandRecorder()`、`OracleDocumentStore(n)`、
`PatchMerger()`（assembly/wiring.py 的组装方式）仍能完成 E01 的保存，发出的语句为 4 条。

只核对语句（不连数据库）；E01 在 d_cg 上的真实联调见 `backend/tests/e2e/test_e01.py`。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

from cost_platform.orchestration.commands import CommandRunner, SaveFlow
from cost_platform.pipeline.command_log import OracleCommandRecorder
from cost_platform.pipeline.document_store import OracleDocumentStore
from cost_platform.pipeline.merge import PatchMerger

from .recording import RecordingUnitOfWork
from .support import Setup, command, master_modify


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


def test_e01_through_existing_saveflow() -> None:
    setup = Setup()
    log = OracleCommandRecorder()
    flows = {"save": SaveFlow(OracleDocumentStore(5), PatchMerger(), setup.permission, log)}
    factory = Factory()
    runner = CommandRunner(factory, log, setup.permission, flows)  # type: ignore[arg-type]
    result = runner.execute(command([master_modify("1001", {"MEMO": "测试"})]), setup.context())
    assert result.outcome == "saved" and result.rows[0].values["MEMO"] == "测试"  # type: ignore[union-attr]
    [uow] = factory.units
    assert [s.split(" ")[0] for s in uow.connection.sql] == ["INSERT", "SELECT", "UPDATE", "UPDATE"]
    assert uow.connection.sql[2] == "UPDATE T_COST_PINGGU SET MEMO = :v0 WHERE DOCID = :pk"
