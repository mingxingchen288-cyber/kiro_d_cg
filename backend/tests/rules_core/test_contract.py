"""rules-core 的 Python 包通过 `RulesEngine` 的契约测试（C08 第 8 节、第 14 节）。"""

from __future__ import annotations

import pytest

# 没有装 rules-core 的 wheel 时（backend 依赖里还没有它，由 assembly 接入），整个模块跳过，不影响 backend 其余测试的收集
pytest.importorskip("cost_rules_core", reason="需要 rules-core 的 wheel：uv run --with <wheel> pytest tests/rules_core")

from cost_rules_core import RulesEngine  # noqa: E402

from ..contracts.test_rules_engine import RulesEngineContract  # noqa: E402
from .support import case, pack_bytes, request_text


class CostRulesCoreHarness:
    def __init__(self) -> None:
        self.engine = RulesEngine()

    def pack(self) -> bytes:
        return pack_bytes("packs/cost-pinggu.json")

    def operation_request(self) -> str:
        return request_text(case("E02-包材批量-preview")["request"])

    def invalid_pack(self) -> bytes:
        return pack_bytes("packs/cycle.json")


class TestCostRulesCore(RulesEngineContract):
    @pytest.fixture
    def harness(self) -> CostRulesCoreHarness:
        return CostRulesCoreHarness()
