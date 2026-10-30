"""按执行上下文中的角色配置判断权限（docs/模块/authz.md AZ-01～AZ-06，C08 第 7 节）。

纯计算，只读执行上下文中的配置快照：角色配置（C06 第 8 节）和页面视图（C05）。平台只使用会话选定的一个角色
（C04），快照中只有这个角色；旧系统按用户的全部角色取并集，新平台不合并。

对照旧系统（cost-server `auth` 包）：
- 按钮：`PagePermission.hasButton`，`*` 或包含该键；键的分组由组件表名改为区域编码（C06 第 8 节）。
- 新增、删除、修改：旧后端保存时只检查 save（`DynamicDataService.java` 第 1095 行）；新平台按用户 2026-10-30 的要求
  "权限可以按照新增 删除 修改 保存 这样给吗？控制到明细级别"，按区域检查（C06 v24 第 8 节、`patch_denials`）。
- 页面访问：`PermissionService.getPagePermission` 为 null（角色没有该页面）时拒绝查询、保存和导出。
- 行权限：`PermissionService.parseRowFilter`，可视化写法取 `sql`、自定义写法取整串；旧系统把 `${userId}`、
  `${username}` 拼进 SQL，这里换成绑定变量。只加在主表上（`DynamicDataService.query` 的 `isDetailTable`）。
- 管理员：旧后端没有代码级的绕过，ADMIN 角色在各页面配置为 `["*"]`、没有行权限；这里同样按角色配置判断。
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from cost_platform.contracts.types import (
    Command,
    DetailAdd,
    DetailDelete,
    DetailModify,
    EntityConfig,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    MasterAdd,
    MasterDelete,
    MasterModify,
    PageView,
    PlatformError,
    RolePage,
    SqlCondition,
    ViewDetail,
    ViewMaster,
)

ALL_BUTTONS = "*"
SAVE_KEY = "system:save"
MASTER_AREA = "master"
ADD_ACTION, COPY_ACTION, MODIFY_ACTION, DELETE_ACTION = "addRow", "copyRow", "modify", "deleteRow"
"""区域的新增、复制、修改、删除：权限键为 `<区域>:<动作>`（C06 v24 第 8 节）。"""

_BIND_NAMES = {"userId": "rp_user_id", "username": "rp_username"}
_PLACEHOLDER = re.compile(r"\$\{(userId|username)\}")


def is_approval_operation(operation: str) -> bool:
    """审批处理命令：`approval.pass`、`approval.reject`、`approval.withdraw`（C02 第 1 节）。"""
    return operation.startswith("approval.")


def _areas(view: PageView) -> Iterator[tuple[str, ViewMaster | ViewDetail]]:
    """页面视图的区域及其权限键前缀：主表为 `master`，明细为明细实体编码（C06 第 8 节）。"""
    yield MASTER_AREA, view.master
    for detail in view.details:
        yield detail.entity, detail


class RolePermissionChecker:
    """`PermissionChecker`（C08 第 7 节），另提供页面访问和 Patch 新增、删除行的检查，供"操作权限"阶段使用。"""

    # ------------------------------------------------------------ 角色在页面上的授权

    def _grant(self, ctx: ExecutionContext, page: str) -> RolePage | None:
        return ctx.config.role().pages.get(page)

    def can_access_page(self, ctx: ExecutionContext, page: str) -> bool:
        """AZ-02：角色配置中有这个页面才能访问它的页面视图、列表、单据和导出。"""
        return self._grant(ctx, page) is not None

    def has_button(self, ctx: ExecutionContext, page: str, key: str) -> bool:
        """角色在页面上有这个权限键，或为 `["*"]`（该页面的全部按钮和导出）。"""
        grant = self._grant(ctx, page)
        return grant is not None and (ALL_BUTTONS in grant.buttons or key in grant.buttons)

    def _require_page(self, ctx: ExecutionContext, page: str) -> RolePage:
        grant = self._grant(ctx, page)
        if grant is None:
            raise PlatformError(ErrorCode.PERMISSION_DENIED, f"当前角色不能访问页面 {page}")
        return grant

    # ------------------------------------------------------------ AZ-01 操作

    def can_run(self, ctx: ExecutionContext, operation: str, page: str | None) -> bool:
        """AZ-01：页面保存需要 `system:save`；按钮操作需要页面中引用这个操作的某个按钮的键。

        审批处理（`approval.*`）的处理人由 approval 判断，来源为审批的写入不按某个人的权限（架构 10.4），
        这两种只确认已选定角色。Patch 中新增、删除行的检查见 `patch_denials`。
        """
        if is_approval_operation(operation) or ctx.origin.kind == "approval":
            return bool(ctx.identity.role_code)
        if page is None or not self.can_access_page(ctx, page):
            return False
        view = ctx.config.page_view(page)
        if operation == view.save_operation:
            return self.has_button(ctx, page, SAVE_KEY)
        keys = [b.key for _, area in _areas(view) for b in area.buttons if b.operation == operation]
        return any(self.has_button(ctx, page, key) for key in keys)

    def patch_denials(self, ctx: ExecutionContext, command: Command) -> list[ErrorDetail]:
        """AZ-01：Patch 中的行按所在区域（主表为 `master`，明细为明细实体编码）检查（C06 v24 第 8 节）：
        - 新增行需要 `<区域>:addRow` 或 `<区域>:copyRow`（复制出的行在后端也是新增行）；
        - 已有行的修改（`changes` 不为空）需要 `<区域>:modify`；
        - 删除需要 `<区域>:deleteRow`；删除主表行连同明细（WP-06），只看 `master:deleteRow`，不看这张单据的明细。
        返回不满足的行，每行一条明细；都满足时为空。按钮动作展开的修改、审批通过时的写入不在 Patch 中，不在这里检查。"""
        page = command.page
        if page is None or not command.documents:
            return []
        denials: list[ErrorDetail] = []

        def allowed(area: str, *actions: str) -> bool:
            return any(self.has_button(ctx, page, f"{area}:{action}") for action in actions)

        def add(area: str, entity: str, client_row_id: str) -> None:
            if not allowed(area, ADD_ACTION, COPY_ACTION):
                denials.append(ErrorDetail(message=f"没有新增行的权限：需要 {area}:{ADD_ACTION} 或 {area}:{COPY_ACTION}",
                                           entity=entity, client_row_id=client_row_id))

        def modify(area: str, entity: str, row_key: str) -> None:
            if not allowed(area, MODIFY_ACTION):
                denials.append(ErrorDetail(message=f"没有修改行的权限：需要 {area}:{MODIFY_ACTION}", entity=entity,
                                           row_key=row_key))

        def delete(area: str, entity: str, row_key: str) -> None:
            if not allowed(area, DELETE_ACTION):
                denials.append(ErrorDetail(message=f"没有删除行的权限：需要 {area}:{DELETE_ACTION}", entity=entity,
                                           row_key=row_key))

        for patch in command.documents:
            master = patch.master
            if isinstance(master, MasterDelete):
                delete(MASTER_AREA, patch.entity, master.row_key)
                continue
            if isinstance(master, MasterAdd):
                add(MASTER_AREA, patch.entity, master.client_row_id)
            elif isinstance(master, MasterModify) and master.changes:
                modify(MASTER_AREA, patch.entity, master.row_key)
            for detail in patch.details:
                if isinstance(detail, DetailAdd):
                    add(detail.entity, detail.entity, detail.client_row_id)
                elif isinstance(detail, DetailModify) and detail.changes:
                    modify(detail.entity, detail.entity, detail.row_key)
                elif isinstance(detail, DetailDelete):
                    delete(detail.entity, detail.entity, detail.row_key)
        return denials

    # ------------------------------------------------------------ AZ-03 行权限

    def row_condition(self, ctx: ExecutionContext, page: str, entity: str) -> SqlCondition | None:
        """AZ-03：角色在该页面的 `rows` 转成 SQL 条件，`${userId}`、`${username}` 换成绑定变量，只放用到的绑定变量；
        条件加括号，调用方可以直接与其他条件用 AND 组合。

        没有 `rows`、`entity` 不是页面主表（明细随主表），或来源为审批（AZ-05）时为 None，表示可以访问全部行。
        角色不能访问该页面时抛 403 PERMISSION_DENIED（AZ-02）。
        """
        if ctx.origin.kind == "approval":
            return None
        rows = self._require_page(ctx, page).rows
        if rows is None or entity != ctx.config.page_view(page).master.entity:
            return None
        sql = rows if isinstance(rows, str) else rows.sql
        values = {"userId": ctx.identity.user_id, "username": ctx.identity.username}
        used = {name: values[name] for name in _PLACEHOLDER.findall(sql)}
        text = _PLACEHOLDER.sub(lambda m: f":{_BIND_NAMES[m.group(1)]}", sql)
        return SqlCondition(sql=f"({text})", binds={_BIND_NAMES[name]: value for name, value in used.items()})

    # ------------------------------------------------------------ AZ-04 可写字段

    def writable_fields(self, ctx: ExecutionContext, page: str, entity: str) -> frozenset[str]:
        """AZ-04：页面视图中可编辑的字段，加上可编辑字段的 Lookup 回填字段（`fillBack` 为 true 时），不含计算字段和
        `erpRow.column`，没有 `erpRow` 的实体也不含 ERP 列；再与页面保存操作的 `writableFields` 取交集（C06 第 4 节）。

        回填字段：旧前端回填时不看目标列能否编辑，旧后端照样保存（业务例子 E31 换物料时单价随回填），迁移也把回填
        目标列入保存操作的 `writableFields`（MG-10）。ERP 行上的 ERP 列由 write-pipeline 按行拒绝。

        来源为审批时（AZ-05）不按页面和角色，只去掉计算字段和 ERP 列，见 `_approval_writable`。
        """
        if ctx.origin.kind == "approval":
            return _approval_writable(ctx.config.entity(entity))
        view = ctx.config.page_view(page)
        area = next((a for _, a in _areas(view) if a.entity == entity), None)
        if area is None:
            return frozenset()
        fields = {f.name: f for f in area.fields}
        editable = [f for f in area.fields if f.editable]
        names = {f.name for f in editable}
        names |= {target for f in editable if f.lookup is not None and f.lookup.fill_back for target in f.lookup.fill}
        erp_column = area.erp_row.column if area.erp_row else None
        allowed = set(ctx.config.operation(view.save_operation).writable_fields.get(entity, []))
        return frozenset(
            name for name in names
            if name in fields and name in allowed and not fields[name].calculated and name != erp_column
            and (area.erp_row is not None or fields[name].source != "erp"))

    # ------------------------------------------------------------ AZ-06 导出

    def can_export(self, ctx: ExecutionContext, page: str, export_code: str) -> bool:
        """AZ-06：按导出配置导出需要 `export:<编码>` 或 `*`（旧 ExportConfigController 的"自定义导出:<编码>"）。"""
        return self.has_button(ctx, page, f"export:{export_code}")


def _approval_writable(entity: EntityConfig) -> frozenset[str]:
    """来源为审批的写入只拒绝计算字段和 ERP 列（C08 第 7 节、C06 7.5）：去掉计算字段、只在视图中的字段（`column`
    为 null，不写入）、`erpRow.column`；没有 `erpRow` 的实体去掉 ERP 列。主键、主从关联字段由 write-pipeline 处理。"""
    erp_column = entity.erp_row.column if entity.erp_row else None
    return frozenset(
        f.name for f in entity.fields
        if f.role != "calculated" and f.column is not None and f.name != erp_column
        and (entity.erp_row is not None or f.source != "erp"))
