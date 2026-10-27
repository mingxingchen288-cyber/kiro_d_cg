"""authz 的 `PermissionChecker` 替代实现（C08 第 7 节）。"""

from __future__ import annotations

from collections.abc import Iterable

from ..types import ExecutionContext, SqlCondition
from ._script import Scripted


class FakePermissionChecker(Scripted):
    """`PermissionChecker`：判断结果由预设给出，不读角色配置。

    - `can_run`、`can_export`：按 `allow`/`deny`、`allow_export`/`deny_export` 的预设；没有预设时取 `allow_all`。
    - `row_condition`：按 `set_rows` 的预设，没有预设时为 None（可以访问全部行）。
    - `writable_fields`：按 `set_writable` 的预设，没有预设时为空集合。
    """

    scriptable = ('can_run', 'row_condition', 'writable_fields', 'can_export')

    def __init__(self, *, allow_all: bool = True) -> None:
        super().__init__()
        self.allow_all = allow_all
        self._run: dict[tuple[str, str | None], bool] = {}
        self._export: dict[tuple[str, str], bool] = {}
        self._rows: dict[tuple[str, str], SqlCondition | None] = {}
        self._writable: dict[tuple[str, str], frozenset[str]] = {}

    def allow(self, operation: str, page: str | None) -> None:
        self._run[(operation, page)] = True

    def deny(self, operation: str, page: str | None) -> None:
        self._run[(operation, page)] = False

    def allow_export(self, page: str, export_code: str) -> None:
        self._export[(page, export_code)] = True

    def deny_export(self, page: str, export_code: str) -> None:
        self._export[(page, export_code)] = False

    def set_rows(self, page: str, entity: str, condition: SqlCondition | None) -> None:
        self._rows[(page, entity)] = condition

    def set_writable(self, page: str, entity: str, fields: Iterable[str]) -> None:
        self._writable[(page, entity)] = frozenset(fields)

    def can_run(self, ctx: ExecutionContext, operation: str, page: str | None) -> bool:
        self._record("can_run", ctx, operation, page)
        return self._run.get((operation, page), self.allow_all)

    def row_condition(self, ctx: ExecutionContext, page: str, entity: str) -> SqlCondition | None:
        self._record("row_condition", ctx, page, entity)
        return self._rows.get((page, entity))

    def writable_fields(self, ctx: ExecutionContext, page: str, entity: str) -> frozenset[str]:
        self._record("writable_fields", ctx, page, entity)
        return self._writable.get((page, entity), frozenset())

    def can_export(self, ctx: ExecutionContext, page: str, export_code: str) -> bool:
        self._record("can_export", ctx, page, export_code)
        return self._export.get((page, export_code), self.allow_all)
