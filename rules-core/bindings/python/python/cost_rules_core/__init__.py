"""rules-core 的 Python 包：`RulesEngine`（C08 第 8 节），输入输出见 C07。

只做 JSON 文本进出（RC-01）；规则求值都在 Rust 内核中。`PackInvalidError` 用 contracts 中的定义
（架构第 3 节：rules-core 只依赖 contracts）。
"""

from __future__ import annotations

from cost_platform.contracts.types import PackInvalidError

from . import _native
from ._native import PackHandle, compare_json, compile_count, numbers_consistent

__all__ = ["RulesEngine", "PackHandle", "PackInvalidError", "compare_json", "compile_count", "numbers_consistent"]


class RulesEngine:
    """C08 第 8 节的 `RulesEngine`。句柄由垃圾回收释放，没有 dispose（C07 第 5 节）。"""

    def load_pack(self, pack_json: bytes) -> PackHandle:
        """解析、检查并编译规则包，同一规则包只编译一次（RC-03）；不合法（包括依赖成环）时抛 PackInvalidError。"""
        try:
            return _native.load_pack(pack_json)
        except _native.PackInvalid as e:
            raise PackInvalidError(str(e)) from None

    def evaluate(self, handle: object, request_json: str) -> str:
        """求值，返回 C07 第 3 节的 JSON 文本；句柄不是 load_pack 返回的，返回 PACK_INVALID 的结果。"""
        if not isinstance(handle, PackHandle):
            return _native.failure("PACK_INVALID", "规则包没有加载")
        return _native.evaluate(handle, request_json)

    def core_version(self) -> str:
        return _native.core_version()
