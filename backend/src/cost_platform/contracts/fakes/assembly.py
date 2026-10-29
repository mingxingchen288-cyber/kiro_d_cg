"""assembly 提供的 `ContextProvider` 的替代实现（C08 第 15 节）。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..types import ExecutionContext
from ._script import Scripted


class FakeContextProvider(Scripted):
    """`ContextProvider`：执行上下文由 `context_of(request, is_write)` 给出，或固定为 `ctx`。

    各模块的 HTTP 路由用它代替 assembly 的会话、来源和 CSRF 校验；要模拟"没登录""CSRF 不对"等，用
    `fail("context", PlatformError(...))`。`is_write` 按调用的先后记在 `writes` 中。"""

    scriptable = ('context',)

    def __init__(self, ctx: ExecutionContext | None = None, *,
                 context_of: Callable[[Any, bool], ExecutionContext] | None = None) -> None:
        super().__init__()
        if (ctx is None) == (context_of is None):
            raise ValueError("ctx 和 context_of 给一个")
        self._ctx = ctx
        self._context_of = context_of
        self.writes: list[bool] = []

    def context(self, request: Any, is_write: bool) -> ExecutionContext:
        self._record("context", is_write)
        self.writes.append(is_write)
        if self._context_of is not None:
            return self._context_of(request, is_write)
        assert self._ctx is not None
        return self._ctx
