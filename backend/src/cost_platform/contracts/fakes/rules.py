"""rules-core 的 `RulesEngine` 替代实现（C08 第 8 节，输入输出见 C07）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..types import EvalComputed, EvalEntry, EvalError, EvalFailure, EvaluationRequest, EvaluationResult, RulesPack, dump_wire, parse_wire
from ._script import Scripted


@dataclass(frozen=True, eq=False)
class FakePack:
    """`load_pack` 返回的句柄。"""

    pack: RulesPack


@dataclass(frozen=True)
class _Preset:
    result: Any
    purpose: str | None
    operation: str | None
    flow: str | None
    level: int | None

    def matches(self, request: EvaluationRequest) -> bool:
        # 计算结果只用于计算请求，入口结果只用于审批入口请求；失败结果两种都可以
        if isinstance(self.result, EvalComputed) and request.purpose != "operation":
            return False
        if isinstance(self.result, EvalEntry) and request.purpose != "approvalEntry":
            return False
        return all(want is None or want == got for want, got in (
            (self.purpose, request.purpose), (self.operation, request.operation), (self.flow, request.flow), (self.level, request.level)))


def _failure(code: str, message: str) -> str:
    return json.dumps(dump_wire(EvaluationResult, EvalFailure(ok=False, error=EvalError(code=code, message=message))), ensure_ascii=False)


class FakeRulesEngine(Scripted):
    """`RulesEngine`：不执行规则，求值结果由 `respond` 预设。

    - `load_pack` 按 C07 第 1 节解析规则包，返回 `FakePack`。
    - `evaluate` 按 C07 第 2 节解析请求；请求不合法时返回 INPUT_INVALID，句柄不是本实例加载的时返回 PACK_INVALID。
      否则返回最近一条条件匹配的预设结果；没有匹配时，计算结果为空（`{"ok": true, "rows": [], "effects": []}`），
      审批入口为满足（`{"ok": true, "satisfied": true}`）。
    - `requests` 按顺序记录解析后的求值请求。
    """

    scriptable = ('load_pack', 'evaluate', 'core_version')

    def __init__(self, core_version: str = "0.1.0") -> None:
        super().__init__()
        self._core_version = core_version
        self._presets: list[_Preset] = []
        self.packs: list[FakePack] = []
        self.requests: list[EvaluationRequest] = []

    def respond(self, result: EvalComputed | EvalEntry | EvalFailure, *, purpose: str | None = None, operation: str | None = None,
                flow: str | None = None, level: int | None = None) -> None:
        """预设结果：只对 purpose、operation、flow、level 都匹配（没给出的不限）的请求生效；
        计算结果只用于 `operation` 请求，入口结果只用于 `approvalEntry` 请求。"""
        self._presets.append(_Preset(result, purpose, operation, flow, level))

    def load_pack(self, pack_json: bytes) -> FakePack:
        self._record("load_pack", pack_json)
        pack = FakePack(parse_wire(RulesPack, json.loads(pack_json)))
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
        default: EvalComputed | EvalEntry = (EvalEntry(ok=True, satisfied=True) if request.purpose == "approvalEntry"
                                             else EvalComputed(ok=True, rows=[], effects=[]))
        return json.dumps(dump_wire(EvaluationResult, default), ensure_ascii=False)

    def core_version(self) -> str:
        self._record("core_version")
        return self._core_version
