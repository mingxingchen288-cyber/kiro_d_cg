"""按角色配置判断权限（AZ-01、AZ-03、AZ-04）。纯计算，只读执行上下文中的配置快照。"""

from __future__ import annotations

import re

from cost_platform.contracts.types import ExecutionContext, SqlCondition

_PLACEHOLDER = re.compile(r"\$\{(userId|username)\}")


class RolePermissionChecker:
    def _buttons(self, ctx: ExecutionContext, page: str | None) -> set[str]:
        grant = ctx.config.role().pages.get(page) if page else None
        return set(grant.buttons) if grant else set()

    def can_run(self, ctx: ExecutionContext, operation: str, page: str | None) -> bool:
        """页面保存需要 `system:save`（AZ-01）。目前只开放页面保存。"""
        if page is None or ctx.config.page_view(page).save_operation != operation:
            return False
        buttons = self._buttons(ctx, page)
        return "*" in buttons or "system:save" in buttons

    def row_condition(self, ctx: ExecutionContext, page: str, entity: str) -> SqlCondition | None:
        """AZ-03：没有行权限时为 None；占位符换成绑定变量。"""
        grant = ctx.config.role().pages.get(page)
        rows = grant.rows if grant else None
        if rows is None:
            return None
        sql = rows if isinstance(rows, str) else rows.sql
        values = {"userId": ctx.identity.user_id, "username": ctx.identity.username}
        return SqlCondition(sql=_PLACEHOLDER.sub(lambda m: f":rp_{m.group(1)}", sql),
                            binds={f"rp_{name}": value for name, value in values.items()})

    def writable_fields(self, ctx: ExecutionContext, page: str, entity: str) -> frozenset[str]:
        """AZ-04：页面视图中可编辑的字段，再与页面保存操作的 writableFields 取交集。"""
        view = ctx.config.page_view(page)
        editable = {f.name for f in view.master.fields if f.editable} if view.master.entity == entity else set()
        allowed = set(ctx.config.operation(view.save_operation).writable_fields.get(entity, []))
        return frozenset(editable & allowed)

    def can_export(self, ctx: ExecutionContext, page: str, export_code: str) -> bool:
        buttons = self._buttons(ctx, page)
        return "*" in buttons or f"export:{export_code}" in buttons
