"""config 端口的替代实现（C08 第 4 节）。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypeVar

from pydantic import ValidationError

from ..types import (
    ApprovalFlowConfig,
    ConfigDraft,
    EntityConfig,
    ErrorCode,
    ErrorDetail,
    ImportReport,
    MenuItem,
    OperationConfig,
    PackHandle,
    PageView,
    PlatformError,
    RoleConfig,
    parse_config_content,
)
from ._script import Scripted

_T = TypeVar("_T")


class FakeConfigSnapshot(Scripted):
    """`ConfigSnapshot`：内容在创建时给出，之后不变（C04：命令执行期间配置快照不变）。

    页面视图、菜单和规则包句柄由 config 生成，这里直接给出生成后的结果；`menus` 应已去掉该角色不能访问的页面。
    替代实现没有缓存，取不到时直接按 C08 第 4 节回查后仍取不到的情况处理：
    - `page_view`：`page_views` 中没有、但在 `pages`（配置中存在的页面）中的，为 403 PERMISSION_DENIED；两处都没有的为 404 NOT_FOUND；
    - `entity`、`operation`、`approval_flow`、`rules_pack`：为 500 INTERNAL_ERROR。
    """

    scriptable = ('page_view', 'entity', 'operation', 'approval_flows', 'approval_flow', 'role', 'menus', 'rules_pack')

    def __init__(
        self,
        *,
        version: int,
        role_code: str,
        role: RoleConfig,
        page_views: Mapping[str, PageView] | None = None,
        pages: Iterable[str] = (),
        entities: Mapping[str, EntityConfig] | None = None,
        operations: Mapping[str, OperationConfig] | None = None,
        approval_flows: Mapping[str, ApprovalFlowConfig] | None = None,
        menus: Sequence[MenuItem] = (),
        packs: Mapping[str, PackHandle] | None = None,
    ) -> None:
        super().__init__()
        self.version = version
        self.role_code = role_code
        self._role = role
        self._page_views = dict(page_views or {})
        self._pages = set(pages) | set(self._page_views)
        self._entities = dict(entities or {})
        self._operations = dict(operations or {})
        self._flows = dict(approval_flows or {})
        self._menus = list(menus)
        self._packs = dict(packs or {})

    @classmethod
    def from_items(cls, *, version: int, role_code: str, items: Iterable[ConfigDraft],
                   page_views: Mapping[str, PageView] | None = None, packs: Mapping[str, PackHandle] | None = None) -> FakeConfigSnapshot:
        """由 C06 的配置项建快照：编码为 `role_code` 的角色是快照所属角色；page 项的编码作为配置中存在的页面；
        menu 项的 `items` 原样作为菜单。"""
        found: dict[str, dict[str, Any]] = {"entity": {}, "operation": {}, "approvalFlow": {}, "role": {}, "menu": {}, "page": {}}
        for item in items:
            if item.type in found:
                found[item.type][item.key] = parse_config_content(item.type, item.content)
        if role_code not in found["role"]:
            raise ValueError(f"配置项中没有角色 {role_code}")
        menus = [entry for menu in found["menu"].values() for entry in menu.items]
        return cls(version=version, role_code=role_code, role=found["role"][role_code], page_views=page_views, pages=found["page"],
                   entities=found["entity"], operations=found["operation"], approval_flows=found["approvalFlow"],
                   menus=menus, packs=packs)

    def _get(self, method: str, table: Mapping[str, _T], code: str) -> _T:
        self._record(method, code)
        if code not in table:
            raise PlatformError(ErrorCode.INTERNAL_ERROR, f"已发布的配置中没有 {code}（{method}）")
        return table[code]

    def page_view(self, page_code: str) -> PageView:
        self._record("page_view", page_code)
        if page_code in self._page_views:
            return self._page_views[page_code]
        if page_code in self._pages:
            raise PlatformError(ErrorCode.PERMISSION_DENIED, f"当前角色不能访问页面 {page_code}")
        raise PlatformError(ErrorCode.NOT_FOUND, f"页面 {page_code} 不存在")

    def entity(self, code: str) -> EntityConfig:
        return self._get("entity", self._entities, code)

    def operation(self, code: str) -> OperationConfig:
        return self._get("operation", self._operations, code)

    def approval_flows(self, operation: str) -> list[ApprovalFlowConfig]:
        self._record("approval_flows", operation)
        return sorted((f for f in self._flows.values() if f.source_operation == operation), key=lambda f: f.created_seq)

    def approval_flow(self, code: str) -> ApprovalFlowConfig:
        return self._get("approval_flow", self._flows, code)

    def role(self) -> RoleConfig:
        self._record("role")
        return self._role

    def menus(self) -> list[MenuItem]:
        self._record("menus")
        return list(self._menus)

    def rules_pack(self, pack_id: str) -> PackHandle:
        return self._get("rules_pack", self._packs, pack_id)


class FakeConfigSnapshotReader(Scripted):
    """`ConfigSnapshotReader`：按角色返回 `put` 放入的快照。

    - 没有该角色的快照（角色已被删除，`remove`）时抛 401 SESSION_ROLE_REVOKED。
    - 配置不可用时预设错误：`fail("read", PlatformError(ErrorCode.CONFIG_UNAVAILABLE, "读不到配置"), times=None)`。
    - 放入新快照或删除角色，不改变已经返回的快照。
    """

    scriptable = ('read',)

    def __init__(self, snapshots: Iterable[FakeConfigSnapshot] = ()) -> None:
        super().__init__()
        self._snapshots: dict[str, FakeConfigSnapshot] = {}
        for snapshot in snapshots:
            self.put(snapshot)

    def put(self, snapshot: FakeConfigSnapshot) -> None:
        self._snapshots[snapshot.role_code] = snapshot

    def remove(self, role_code: str) -> None:
        self._snapshots.pop(role_code, None)

    def read(self, role_code: str) -> FakeConfigSnapshot:
        self._record("read", role_code)
        if role_code not in self._snapshots:
            raise PlatformError(ErrorCode.SESSION_ROLE_REVOKED, f"角色 {role_code} 已被删除，请重新选择角色")
        return self._snapshots[role_code]


class FakeConfigImporter(Scripted):
    """`ConfigImporter`：按 C08 第 4 节整批导入，只检查内容符合 C06 的结构（第 10 节的其余校验和引用由 config 负责）。

    与 `items` 中已有配置项类型和编码相同的项不覆盖，列入 `skipped`，也不校验；其余各项有一项不符合时抛
    422 VALIDATION_FAILED，明细列出每个不符合的项，什么都不写。已有的配置项可以用 `put` 预设。
    """

    scriptable = ('import_items',)

    def __init__(self) -> None:
        super().__init__()
        self.items: dict[tuple[str, str], ConfigDraft] = {}

    def put(self, item: ConfigDraft) -> None:
        self.items[(item.type, item.key)] = item

    def import_items(self, items: list[ConfigDraft]) -> ImportReport:
        self._record("import_items", items)
        skipped = [item for item in items if (item.type, item.key) in self.items]
        new = [item for item in items if (item.type, item.key) not in self.items]
        details = []
        for item in new:
            try:
                parse_config_content(item.type, item.content)
            except ValidationError as e:
                first = e.errors()[0]
                details.append(ErrorDetail(message=str(first["msg"]), config_type=item.type, config_key=item.key,
                                           path=".".join(str(p) for p in first["loc"])))
        if details:
            raise PlatformError(ErrorCode.VALIDATION_FAILED, "配置校验不通过", details)
        for item in new:
            self.put(item)
        return ImportReport(imported=len(new),
                            skipped=[(f"config:{item.type}/{item.key}", "已有同类型、同编码的配置项，没有覆盖") for item in skipped])
