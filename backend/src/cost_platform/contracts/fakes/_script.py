"""替代实现共用的调用记录和预设错误（CT-03）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class Call:
    """替代实现收到的一次调用。"""

    method: str
    args: tuple[Any, ...]


class Scripted:
    """记录每次调用；`fail` 让某个方法的后续调用抛出预设的错误。

    子类在 `scriptable` 中列出端口的方法，只有这些方法可以预设错误，也只有它们被记录。
    """

    scriptable: ClassVar[tuple[str, ...]] = ()

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._failures: dict[str, list[list[Any]]] = {}

    def fail(self, method: str, error: BaseException, times: int | None = 1) -> None:
        """让 `method` 接下来的 `times` 次调用抛出 `error`；`times` 为 None 时一直抛出，直到调用 `recover`。"""
        if method not in self.scriptable:
            raise AttributeError(f"{type(self).__name__} 没有可以预设错误的方法 {method}")
        if times is not None and times < 1:
            raise ValueError("times 至少为 1")
        self._failures.setdefault(method, []).append([error, times])

    def recover(self, method: str | None = None) -> None:
        """撤销预设的错误：给出 `method` 时只撤销这个方法的。"""
        if method is None:
            self._failures.clear()
        else:
            self._failures.pop(method, None)

    def calls_to(self, method: str) -> list[Call]:
        return [c for c in self.calls if c.method == method]

    def _record(self, method: str, *args: Any) -> None:
        """记录调用；有预设的错误时抛出。"""
        self.calls.append(Call(method, args))
        queue = self._failures.get(method)
        if not queue:
            return
        error, times = queue[0]
        if times is not None:
            if times == 1:
                queue.pop(0)
            else:
                queue[0][1] = times - 1
        raise error
