"""按单据提交（`split.py`，C02 v10 第 1 节，模拟验证；用户 2026-10-31："我也是要求一单一单的提交啊……100个单据 失败了1个，
就全部失败"是不可以的）。

场景：成本核算页面一次保存成本单 2550、2551 两张单据，或在主表选中这两行点按钮。各模块的阶段用 `FakeStage`，
"确定涉及的单据"把子命令的单据记入 `involved`；命令记录用 test_runner 的内存实现，结果中每张单据带出主表行。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from cost_platform.contracts.fakes import FakeCommandMonitor, FakeDeliveryDispatcher, FakeStage, FakeUnitOfWorkFactory
from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    Command,
    CommandResult,
    CommandState,
    DocumentRef,
    ErrorCode,
    ExecutionContext,
    MasterAdd,
    PlatformError,
    ResultRow,
    dump_wire,
    parse_wire,
)
from cost_platform.orchestration.runner import STAGE_ORDER, CommandRunner
from cost_platform.orchestration.split import sub_request_key

from ..contracts.support import context
from .test_runner import MemoryRecorder

PAGE, SAVE, BUTTON = "COST_PINGGU", "COST_PINGGU.save", "COST_PINGGU.calc"
REQUEST_KEY = "3f2b6c1e-8a4d-4c2e-9b1a-0d6e5f7a8b9c"
NEW_DOC = "tmp-6a1f2c3d-0b4e-4f5a-8c7d-9e0f1a2b3c4d"


def save(*masters: dict[str, Any]) -> Command:
    return parse_wire(Command, {"requestKey": REQUEST_KEY, "page": PAGE, "operation": SAVE, "params": {},
                                "documents": [{"entity": PAGE, "master": m, "details": []} for m in masters]})


def modify(key: str) -> dict[str, Any]:
    return {"op": "modify", "rowKey": key, "changes": {"MEMO": "测试"}}


def button(*rows: tuple[str, str]) -> Command:
    return parse_wire(Command, {"requestKey": REQUEST_KEY, "page": PAGE, "operation": BUTTON, "documents": [],
                                "params": {"selectedRows": [{"entity": e, "rowKey": k} for e, k in rows]}})


class Recorder(MemoryRecorder):
    """命令结果中每张单据带出主表行；新增的单据取得主键 9001。"""

    def complete(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> CommandResult:
        result = super().complete(uow, state, ctx)
        rows, id_map = [], {}
        for ref in state.involved:
            key = ref.record_key
            if key.startswith("tmp-"):
                id_map[key], key = "9001", "9001"
            rows.append(ResultRow(entity=ref.entity, row_key=key, values={"MEMO": "测试"}, frozen=None))
        result = result.model_copy(update={"rows": rows, "id_map": id_map})
        if result.outcome != "unchanged":
            self.done[(ctx.identity.user_id, state.command.request_key)] = (state.command.content_digest(), result)
        return result


class Harness:
    """`fail` 中的单据在"冻结检查"失败（键为主键或 clientRowId，值为要抛的异常）。"""

    def __init__(self) -> None:
        self.fail: dict[str, Exception] = {}
        self.ran: list[str] = []
        self.factory = FakeUnitOfWorkFactory()
        self.monitor = FakeCommandMonitor()

        def involve(_uow: UnitOfWork, state: CommandState, _ctx: ExecutionContext) -> None:
            command = state.command
            if command.documents:
                [document] = command.documents
                master = document.master
                key = master.client_row_id if isinstance(master, MasterAdd) else master.row_key
                state.involved.append(DocumentRef(document.entity, key))
            for row in command.params.get("selectedRows", []):
                ref = DocumentRef(PAGE, row["rowKey"])
                if ref not in state.involved:
                    state.involved.append(ref)
            self.ran.append(",".join(r.record_key for r in state.involved))

        def check(_uow: UnitOfWork, state: CommandState, _ctx: ExecutionContext) -> None:
            for ref in state.involved:
                if ref.record_key in self.fail:
                    raise self.fail[ref.record_key]

        effects = {"确定涉及的单据": involve, "冻结检查": check}
        stages = [FakeStage(name, effect=effects.get(name)) for name in STAGE_ORDER if name != "展开动作"]
        stages.append(FakeStage("展开动作", applies=False))
        self.runner = CommandRunner(self.factory, Recorder(), self.monitor, FakeDeliveryDispatcher(), stages)

    def execute(self, command: Command, ctx: ExecutionContext | None = None) -> CommandResult:
        return self.runner.execute(command, ctx or context())


def page_context() -> ExecutionContext:
    """成本核算页面的主表实体为 COST_PINGGU（按钮拆分只看这一项）。"""
    view = SimpleNamespace(master=SimpleNamespace(entity=PAGE))
    return context(config=SimpleNamespace(version=13, page_view=lambda code: view))


FROZEN = PlatformError(ErrorCode.FROZEN_BY_APPROVAL, "单据已被审批冻结", details=[])


def test_two_documents_one_fails_the_other_is_committed() -> None:
    """成本单 2550、2551 一起保存，2551 被审批冻结：2550 照常提交，2551 记入 `failed`（C03 错误体），整个请求不报错。
    两张单据各一个事务、各一个子请求键，命令审查各记一条。"""
    h = Harness()
    h.fail["2551"] = FROZEN
    result = h.execute(save(modify("2550"), modify("2551")))
    assert result.request_key == REQUEST_KEY and result.outcome == "saved"
    assert [r.row_key for r in result.rows] == ["2550"]
    [failure] = result.failed
    assert (failure.entity, failure.row_key, failure.client_row_id) == (PAGE, "2551", None)
    assert failure.error.code is ErrorCode.FROZEN_BY_APPROVAL and failure.error.message == "单据已被审批冻结"
    assert [(u.committed, u.rolled_back) for u in h.factory.units] == [(True, False), (False, True)]
    keys = [sub_request_key(REQUEST_KEY, PAGE, "2550"), sub_request_key(REQUEST_KEY, PAGE, "2551")]
    assert h.monitor.watched == [(keys[0], None), (keys[1], ErrorCode.FROZEN_BY_APPROVAL)]
    [wire] = dump_wire(CommandResult, result)["failed"]
    assert {k: wire[k] for k in ("entity", "rowKey")} == {"entity": PAGE, "rowKey": "2551"} and "clientRowId" not in wire
    assert (wire["error"]["code"], wire["error"]["message"]) == ("FROZEN_BY_APPROVAL", "单据已被审批冻结")


def test_replay_returns_committed_documents_and_reruns_failed_ones() -> None:
    """同一请求重发（例如网络断了前端重试）：已提交的 2550 按命令记录返回原结果、不再执行；上次失败的 2551 重新执行，
    这次通过。"""
    h = Harness()
    h.fail["2551"] = FROZEN
    command = save(modify("2550"), modify("2551"))
    h.execute(command)
    del h.fail["2551"]
    result = h.execute(command)
    assert h.ran == ["2550", "2551", "2551"]
    assert [r.row_key for r in result.rows] == ["2550", "2551"] and result.failed == []
    assert "failed" not in dump_wire(CommandResult, result)  # 没有失败的单据时不输出


def test_new_document_failure_carries_client_row_id() -> None:
    """新增的单据失败时按 clientRowId 指出；成功的新增单据取得主键，`idMap` 合在一起。"""
    h = Harness()
    h.fail["2550"] = PlatformError(ErrorCode.VALIDATION_FAILED, "保存失败", details=[])
    result = h.execute(save(modify("2550"), {"op": "add", "clientRowId": NEW_DOC, "values": {"MEMO": "新建"}}))
    assert result.id_map == {NEW_DOC: "9001"}
    [failure] = result.failed
    assert (failure.row_key, failure.client_row_id, failure.error.code) == ("2550", None, ErrorCode.VALIDATION_FAILED)
    assert sub_request_key(REQUEST_KEY, PAGE, NEW_DOC) == h.monitor.watched[1][0]


def test_unexpected_error_of_one_document_does_not_hide_the_others() -> None:
    """2550 已提交，2551 出现意外错误（不是 PlatformError）：记为 INTERNAL_ERROR，不抛出，2550 的结果照常返回。"""
    h = Harness()
    h.fail["2550"] = RuntimeError("连接断开")
    result = h.execute(save(modify("2551"), modify("2550")))
    assert [r.row_key for r in result.rows] == ["2551"]
    [failure] = result.failed
    assert failure.row_key == "2550" and failure.error.code is ErrorCode.INTERNAL_ERROR
    assert failure.error.message == "保存这张单据时出现内部错误，请联系管理员"


def test_all_documents_failed() -> None:
    """两张都失败：请求本身不报错，没有写入（unchanged），`failed` 按提交的顺序列出两张。"""
    h = Harness()
    h.fail["2550"] = h.fail["2551"] = FROZEN
    result = h.execute(save(modify("2550"), modify("2551")))
    assert result.outcome == "unchanged" and [f.row_key for f in result.failed] == ["2550", "2551"]


def test_single_document_still_raises() -> None:
    """只有一张单据时照原来执行：失败抛错，HTTP 错误响应（前端的冻结弹窗、定位明细按这个处理）。"""
    h = Harness()
    h.fail["2550"] = FROZEN
    with pytest.raises(PlatformError) as caught:
        h.execute(save(modify("2550")))
    assert caught.value.code is ErrorCode.FROZEN_BY_APPROVAL
    assert h.monitor.watched == [(REQUEST_KEY, ErrorCode.FROZEN_BY_APPROVAL)]


def test_button_on_two_selected_master_rows_runs_per_document() -> None:
    """主表选中成本单 2550、2551 点按钮：每行一个子命令，`selectedRows` 只留这一行；2551 失败不影响 2550。"""
    h = Harness()
    h.fail["2551"] = FROZEN
    result = h.execute(button((PAGE, "2550"), (PAGE, "2551")), page_context())
    assert h.ran == ["2550", "2551"]
    assert [r.row_key for r in result.rows] == ["2550"] and [f.row_key for f in result.failed] == ["2551"]


def test_button_on_detail_rows_is_not_split() -> None:
    """明细区选中两行物料：都属于明细区显示的那一张单据，一个命令。"""
    h = Harness()
    rows = (("COST_MATERIAL", "5001"), ("COST_MATERIAL", "5002"))
    h.execute(parse_wire(Command, {"requestKey": REQUEST_KEY, "page": PAGE, "operation": BUTTON, "documents": [],
                                   "params": {"selectedRows": [{"entity": e, "rowKey": k} for e, k in rows]}}),
              page_context())
    assert len(h.monitor.watched) == 1 and h.monitor.watched[0][0] == REQUEST_KEY


def test_button_on_one_selected_row_is_not_split() -> None:
    h = Harness()
    h.execute(button((PAGE, "2550")), page_context())
    assert h.monitor.watched == [(REQUEST_KEY, None)]


def test_sub_request_keys_are_stable_and_distinct() -> None:
    first = sub_request_key(REQUEST_KEY, PAGE, "2550")
    assert first == sub_request_key(REQUEST_KEY, PAGE, "2550")
    assert first != sub_request_key(REQUEST_KEY, PAGE, "2551")
    assert first != REQUEST_KEY
