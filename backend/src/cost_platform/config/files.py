"""从目录中的配置项文件读取配置快照（链路 0 手写的配置，T-CF-1 的最小部分）。

每个文件是一个配置项 `{"type", "key", "name", "content"}`（C06 第 1 节）。以后换成 PF_CONFIG_ITEM 和 Redis 时，
只替换本文件的读取部分，快照的接口不变。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cost_platform.contracts.types import (
    ApprovalFlowConfig,
    ConfigDraft,
    EntityConfig,
    ErrorCode,
    MenuConfig,
    MenuItem,
    OperationConfig,
    PackHandle,
    PageConfig,
    PageView,
    PlatformError,
    RoleConfig,
    parse_config_content,
    parse_wire,
)

from .page_view import build_page_view


def _visible_menus(items: list[MenuItem], role: RoleConfig) -> list[MenuItem]:
    """ID-09：去掉角色不能访问的页面，以及因此变空的分组。"""
    result: list[MenuItem] = []
    for item in items:
        if item.kind == "group":
            children = _visible_menus(item.children, role)
            if children:
                result.append(item.model_copy(update={"children": children}))
        elif item.kind == "page" and item.page_code in role.pages:
            result.append(item)
        elif item.kind in ("config", "admin") and role.admin:
            result.append(item)
    return result


class FileConfigSnapshot:
    def __init__(self, version: int, role_code: str, items: dict[tuple[str, str], Any]) -> None:
        self.version = version
        self.role_code = role_code
        self._items = items
        self._views: dict[str, PageView] = {}

    def _get(self, config_type: str, key: str) -> Any:
        found = self._items.get((config_type, key))
        if found is None:
            raise PlatformError(ErrorCode.NOT_FOUND, f"配置不存在：{config_type} {key}")
        return found

    def page_view(self, page_code: str) -> PageView:
        if page_code not in self._views:
            page: PageConfig = self._get("page", page_code)
            role = self.role()
            if page_code not in role.pages:
                raise PlatformError(ErrorCode.PERMISSION_DENIED, "没有访问这个页面的权限")
            entities = {k: v for (t, k), v in self._items.items() if t == "entity"}
            self._views[page_code] = build_page_view(page_code, page, entities, role, self.version)
        return self._views[page_code]

    def entity(self, code: str) -> EntityConfig:
        return self._get("entity", code)

    def operation(self, code: str) -> OperationConfig:
        return self._get("operation", code)

    def approval_flows(self, page: str) -> list[ApprovalFlowConfig]:
        return []

    def approval_flow(self, code: str) -> ApprovalFlowConfig:
        return self._get("approvalFlow", code)

    def role(self) -> RoleConfig:
        return self._get("role", self.role_code)

    def menus(self) -> list[MenuItem]:
        menu: MenuConfig | None = self._items.get(("menu", "main"))
        return _visible_menus(menu.items, self.role()) if menu else []

    def rules_pack(self, pack_id: str) -> PackHandle:
        raise PlatformError(ErrorCode.NOT_FOUND, f"规则包不存在：{pack_id}")


class FileConfigSnapshotReader:
    """`ConfigSnapshotReader`：启动时读入目录中的全部配置项，版本号固定为 `version`。"""

    def __init__(self, directory: Path, version: int = 1) -> None:
        self.version = version
        self._items: dict[tuple[str, str], Any] = {}
        for path in sorted(directory.glob("*.json")):
            draft: ConfigDraft = parse_wire(ConfigDraft, json.loads(path.read_text(encoding="utf-8")))
            self._items[(draft.type, draft.key)] = parse_config_content(draft.type, draft.content)

    def read(self, role_code: str) -> FileConfigSnapshot:
        return FileConfigSnapshot(self.version, role_code, self._items)

    def role(self, role_code: str) -> RoleConfig:
        return self._items[("role", role_code)]
