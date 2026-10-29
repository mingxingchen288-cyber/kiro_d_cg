"""rules-core 的 `RulesEngine` 替代实现（C08 第 8 节，输入输出见 C07）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..types import (
    EvalComputed,
    EvalError,
    EvalFailure,
    EvaluationRequest,
    EvaluationResult,
    PackInvalidError,
    RulesPack,
    dump_wire,
    parse_wire,
)
from ._script import Scripted


@dataclass(frozen=True, eq=False)
class FakePack:
    """`load_pack` 返回的句柄。"""

    pack: RulesPack


@dataclass(frozen=True)
class _Preset:
    result: Any
    operation: str | None

    def matches(self, request: EvaluationRequest) -> bool:
        return self.operation is None or self.operation == request.operation


def _failure(code: str, message: str) -> str:
    return json.dumps(dump_wire(EvaluationResult, EvalFailure(ok=False, error=EvalError(code=code, message=message))), ensure_ascii=False)


class FakeRulesEngine(Scripted):
    """`RulesEngine`：不执行规则，求值结果由 `respond` 预设。

    - `load_pack` 按 C07 第 1 节解析规则包，返回 `FakePack`；不符合时抛 `PackInvalidError`（不检查依赖成环）。
    - `evaluate` 按 C07 第 2 节解析请求；请求不合法时返回 INPUT_INVALID，句柄不是本实例加载的时返回 PACK_INVALID。
      否则返回最近一条条件匹配的预设结果；没有匹配时，计算结果为空（`{"ok": true, "rows": [], "effects": []}`）。
    - `requests` 按顺序记录解析后的求值请求。
    """

    scriptable = ('load_pack', 'evaluate', 'core_version')

    def __init__(self, core_version: str = "0.1.0") -> None:
        super().__init__()
        self._core_version = core_version
        self._presets: list[_Preset] = []
        self.packs: list[FakePack] = []
        self.requests: list[EvaluationRequest] = []

    def respond(self, result: EvalComputed | EvalFailure, *, operation: str | None = None) -> None:
        """预设结果：只对 operation 匹配（没给出的不限）的请求生效。"""
        self._presets.append(_Preset(result, operation))

    def load_pack(self, pack_json: bytes) -> FakePack:
        self._record("load_pack", pack_json)
        try:
            pack = FakePack(parse_wire(RulesPack, json.loads(pack_json)))
        except (ValueError, ValidationError) as e:
            raise PackInvalidError(f"规则包不符合 C07 第 1 节：{type(e).__name__}") from None
        self.packs.append(pack)
        return pack

    def evaluate(self, handle: object, request_json: str) -> str:
        self._record("evaluate", handle, request_json)
        if not any(handle is p for p in self.packs):
            return _failure("PACK_INVALID", "规则包没有加载")
        try:
            request = parse_wire(EvaluationRequest, json.loads(request_json))
        except (ValueError, ValidationError):
            return _failure("INPUT_INVALID", "求值请求不符合 C07 第 2 节")
        self.requests.append(request)
        for preset in reversed(self._presets):
            if preset.matches(request):
                return json.dumps(dump_wire(EvaluationResult, preset.result), ensure_ascii=False)
        default = EvalComputed(ok=True, rows=[], effects=[])
        return json.dumps(dump_wire(EvaluationResult, default), ensure_ascii=False)

    def core_version(self) -> str:
        self._record("core_version")
        return self._core_version
