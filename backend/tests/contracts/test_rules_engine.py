"""`RulesEngine` 的契约测试（C08 第 8 节，输入输出见 C07）。

真实实现（rules-core 的 Python 包）的测试继承 `RulesEngineContract`，提供 `harness` fixture，实现 `RulesEngineHarness`。
计算结果是否正确由 rules-core 的样例集（C07 第 6 节）验证；这里检查接口的形状和出错时的结果。
"""

from __future__ import annotations

import json
from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeRulesEngine
from cost_platform.contracts.ports import RulesEngine
from cost_platform.contracts.types import EvalComputed, EvalEntry, EvalFailure, EvaluationResult, PackInvalidError, parse_wire

from .support import doc_json


class RulesEngineHarness(Protocol):
    engine: RulesEngine

    def pack(self) -> bytes:
        """一个能加载的规则包（C07 第 1 节）。"""
        ...

    def operation_request(self) -> str:
        """对这个规则包的一个计算请求（`purpose` 为 `operation`）。"""
        ...

    def entry_request(self) -> str:
        """对这个规则包的一个审批入口请求（`purpose` 为 `approvalEntry`）。"""
        ...

    def invalid_pack(self) -> bytes:
        """一个不合法的规则包（真实实现用依赖成环的规则包）。"""
        ...


def _result(text: str) -> EvalComputed | EvalEntry | EvalFailure:
    return parse_wire(EvaluationResult, json.loads(text))


class RulesEngineContract:
    @pytest.fixture
    def harness(self) -> RulesEngineHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_core_version(self, harness: RulesEngineHarness) -> None:
        version = harness.engine.core_version()
        assert isinstance(version, str) and version

    def test_invalid_pack(self, harness: RulesEngineHarness) -> None:
        """不合法的规则包由 load_pack 抛 PackInvalidError，消息说明原因（C08 第 8 节）。"""
        with pytest.raises(PackInvalidError) as caught:
            harness.engine.load_pack(harness.invalid_pack())
        assert caught.value.message
        assert "Traceback" not in caught.value.message and "panicked" not in caught.value.message

    def test_operation_result_shape(self, harness: RulesEngineHarness) -> None:
        handle = harness.engine.load_pack(harness.pack())
        assert isinstance(_result(harness.engine.evaluate(handle, harness.operation_request())), EvalComputed)

    def test_entry_result_shape(self, harness: RulesEngineHarness) -> None:
        handle = harness.engine.load_pack(harness.pack())
        assert isinstance(_result(harness.engine.evaluate(handle, harness.entry_request())), EvalEntry)

    @pytest.mark.parametrize("broken", ["not json", "{}", "[]"], ids=["not-json", "empty-object", "array"])
    def test_invalid_request(self, harness: RulesEngineHarness, broken: str) -> None:
        """请求本身有问题时返回 INPUT_INVALID，不返回部分结果，不含 panic 信息和调用栈（C07 第 3 节）。"""
        handle = harness.engine.load_pack(harness.pack())
        result = _result(harness.engine.evaluate(handle, broken))
        assert isinstance(result, EvalFailure)
        assert result.error.code == "INPUT_INVALID"
        assert "Traceback" not in result.error.message and "panicked" not in result.error.message

    def test_foreign_handle(self, harness: RulesEngineHarness) -> None:
        """evaluate 收到不是本引擎加载的句柄时，返回 PACK_INVALID 的结果（C08 第 8 节）。"""
        harness.engine.load_pack(harness.pack())
        result = _result(harness.engine.evaluate(object(), harness.operation_request()))
        assert isinstance(result, EvalFailure)
        assert result.error.code == "PACK_INVALID"

    def test_request_missing_required_field(self, harness: RulesEngineHarness) -> None:
        handle = harness.engine.load_pack(harness.pack())
        request = json.loads(harness.operation_request())
        del request["phase"]
        result = _result(harness.engine.evaluate(handle, json.dumps(request)))
        assert isinstance(result, EvalFailure)
        assert result.error.code == "INPUT_INVALID"


class FakeRulesEngineHarness:
    def __init__(self) -> None:
        self.engine = FakeRulesEngine()

    def pack(self) -> bytes:
        return json.dumps(doc_json("C07", 0), ensure_ascii=False).encode("utf-8")

    def operation_request(self) -> str:
        return json.dumps(doc_json("C07", 1), ensure_ascii=False)

    def entry_request(self) -> str:
        return json.dumps({**doc_json("C07", 1), "purpose": "approvalEntry", "flow": "COST_TO_GOODS", "level": 1}, ensure_ascii=False)

    def invalid_pack(self) -> bytes:
        broken = doc_json("C07", 0)
        del broken["rules"]
        return json.dumps(broken).encode("utf-8")


class TestFakeRulesEngine(RulesEngineContract):
    @pytest.fixture
    def harness(self) -> FakeRulesEngineHarness:
        return FakeRulesEngineHarness()


def test_fake_presets_and_requests() -> None:
    """替代实现：按条件预设结果，记录解析后的请求。"""
    harness = FakeRulesEngineHarness()
    engine = harness.engine
    handle = engine.load_pack(harness.pack())
    engine.respond(EvalEntry(ok=True, satisfied=False), purpose="approvalEntry", flow="COST_TO_GOODS")
    computed = parse_wire(EvaluationResult, doc_json("C07", 2))
    engine.respond(computed, operation="COST_PINGGU.save")
    assert _result(engine.evaluate(handle, harness.entry_request())) == EvalEntry(ok=True, satisfied=False)
    assert _result(engine.evaluate(handle, harness.operation_request())) == computed
    assert [r.purpose for r in engine.requests] == ["approvalEntry", "operation"]
