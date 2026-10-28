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
    EscapeHatch,
    ImportReport,
    InsertRows,
    MenuItem,
    OperationConfig,
    PackHandle,
    PageView,
    PlatformError,
    RoleApprover,
    RoleConfig,
    UpdateRecords,
    UpdateTargets,
    parse_config_content,
)
from ._script import Scripted

_T = TypeVar("_T")


def _accessible_menus(items: list[MenuItem], pages: set[str]) -> list[MenuItem]:
    """去掉指向角色不能访问的页面的菜单项；分组保留，其中的子项同样处理。"""
    kept = []
    for item in items:
        if item.kind == "page" and item.page_code not in pages:
            continue
        kept.append(item.model_copy(update={"children": _accessible_menus(item.children, pages)}))
    return kept


def _references(config_type: str, content: Any) -> list[tuple[str, str, str]]:
    """配置内容按编码引用的其他配置项：（类型、编码、引用在内容中的位置）。位置按 C03 的写法，以 `.` 开头，
    例如 `.master.entity`、`.levels[0].entries[1].approvers[0].role`。只看配置项之间的引用，不看字段、表和列。"""
    refs: list[tuple[str, str, str]] = []

    def actions(steps: Iterable[Any], at: str) -> None:
        for i, step in enumerate(steps):
            here = f"{at}[{i}]"
            if isinstance(step, UpdateTargets):
                for j, target in enumerate(step.targets):
                    refs.append(("entity", target.entity, f"{here}.targets[{j}].entity"))
                    if target.detail_entity:
                        refs.append(("entity", target.detail_entity, f"{here}.targets[{j}].detailEntity"))
            elif isinstance(step, UpdateRecords):
                refs.append(("entity", step.find.entity, f"{here}.find.entity"))
            elif isinstance(step, InsertRows):
                refs.append(("entity", step.entity, f"{here}.entity"))
            elif isinstance(step, EscapeHatch):
                refs.append(("operation", step.operation, f"{here}.operation"))

    if config_type == "entity":
        refs += [("entity", d.entity, f".details[{i}].entity") for i, d in enumerate(content.details)]
        refs += [("page", p, f".approvalRequired[{i}].sourcePages[{j}]")
                 for i, rule in enumerate(content.approval_required) for j, p in enumerate(rule.source_pages)]
    elif config_type == "page":
        refs.append(("operation", content.save_operation, ".saveOperation"))
        areas = [(".master", content.master), *((f".details[{i}]", d) for i, d in enumerate(content.details))]
        for at, area in areas:
            refs.append(("entity", area.entity, f"{at}.entity"))
            refs += [("operation", b.operation, f"{at}.buttons[{j}].operation") for j, b in enumerate(area.buttons) if b.operation]
            for name, setting in area.fields.items():
                if setting.lookup:
                    refs.append(("lookup", setting.lookup.code, f"{at}.fields.{name}.lookup.code"))
                if setting.dict_type:
                    refs.append(("dict", setting.dict_type, f"{at}.fields.{name}.dictType"))
    elif config_type == "operation":
        refs += [("entity", e, f".writableFields.{e}") for e in content.writable_fields]
        refs += [("entity", e, f".impact[{i}]") for i, e in enumerate(content.impact)]
        actions(content.actions, ".actions")
    elif config_type == "rule":
        refs.append(({"entity": "entity", "operation": "operation", "page": "page"}[content.layer], content.target, ".target"))
    elif config_type == "approvalFlow":
        refs.append(("operation", content.source_operation, ".sourceOperation"))
        refs += [("entity", e, f".trigger.changedFields.{e}") for e in content.trigger.changed_fields]
        refs += [("role", a.role, f".levels[{i}].entries[{j}].approvers[{k}].role")
                 for i, level in enumerate(content.levels) for j, entry in enumerate(level.entries)
                 for k, a in enumerate(entry.approvers) if isinstance(a, RoleApprover)]
        refs += [("entity", f.entity, f".freeze[{i}].entity") for i, f in enumerate(content.freeze)]
        if content.display:
            if content.display.source:
                refs += [("entity", d.entity, f".display.source.details[{i}].entity")
                         for i, d in enumerate(content.display.source.details)]
            for i, block in enumerate(content.display.affected):
                refs.append(("entity", block.find.entity, f".display.affected[{i}].find.entity"))
                actions(block.actions, f".display.affected[{i}].actions")
    elif config_type == "role":
        refs += [("page", p, f".pages.{p}") for p in content.pages]
    elif config_type == "menu":
        def walk(items: Iterable[MenuItem], at: str) -> None:
            for i, item in enumerate(items):
                if item.page_code:
                    refs.append(("page", item.page_code, f"{at}[{i}].pageCode"))
                walk(item.children, f"{at}[{i}].children")
        walk(content.items, ".items")
    elif config_type == "export":
        refs.append(("page", content.page, ".page"))
    return refs


class FakeConfigSnapshot(Scripted):
    """`ConfigSnapshot`：内容在创建时给出，之后不变（C04：命令执行期间配置快照不变）。

    页面视图、菜单和规则包句柄由 config 生成，这里直接给出生成后的结果；直接构造时 `menus` 应已去掉该角色不能访问的页面
    （`from_items` 会按角色去掉）。替代实现没有缓存，取不到时直接按 C08 第 4 节回查后仍取不到的情况处理：
    - `page_view`：配置中存在（在 `pages` 中）、但角色配置中没有的页面为 403 PERMISSION_DENIED；配置和角色配置中都没有的
      为 404 NOT_FOUND；角色可以访问、却没有给出页面视图，是准备测试数据时漏了，抛 ValueError；
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
        menu 项的 `items` 作为菜单，去掉角色配置中没有的页面（CF-12）。"""
        found: dict[str, dict[str, Any]] = {"entity": {}, "operation": {}, "approvalFlow": {}, "role": {}, "menu": {}, "page": {}}
        for item in items:
            if item.type in found:
                found[item.type][item.key] = parse_config_content(item.type, item.content)
        if role_code not in found["role"]:
            raise ValueError(f"配置项中没有角色 {role_code}")
        role: RoleConfig = found["role"][role_code]
        menus = _accessible_menus([entry for menu in found["menu"].values() for entry in menu.items], set(role.pages))
        return cls(version=version, role_code=role_code, role=role, page_views=page_views, pages=found["page"],
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
        if page_code in self._role.pages:
            raise ValueError(f"替代实现没有给出角色可以访问的页面 {page_code} 的页面视图")
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
    """`ConfigImporter`：按 C08 第 4 节整批导入。

    同一批中类型和编码相同的项都不通过，与已有配置项相同时也一样。其余各项中，与已有配置项类型和编码相同的不覆盖，
    列入 `skipped`，也不校验；剩下的检查两件事：内容符合 C06 的结构；按编码引用的配置项（实体、操作、页面、角色、
    Lookup、字典）在已有配置或本批其他项中存在。有一项不通过时抛 422 VALIDATION_FAILED，明细按本批中的顺序列出每个
    不通过的项，说明用中文，`path` 以 `items[<序号>]` 开头，什么都不写。已有的配置项可以用 `put` 预设。

    结构不合法和引用不存在的明细，`path` 在 `items[<序号>]` 后面接内容中的位置；同批重复只有 `items[<序号>]`。
    限制：结构不合法的项只列出第一处错误。

    C06 第 10 节的其余校验（字段、表和列、表达式、SQL 等）由 config 负责，这里不做。
    """

    scriptable = ('import_items',)

    def __init__(self) -> None:
        super().__init__()
        self.items: dict[tuple[str, str], ConfigDraft] = {}

    def put(self, item: ConfigDraft) -> None:
        self.items[(item.type, item.key)] = item

    def import_items(self, items: list[ConfigDraft]) -> ImportReport:
        self._record("import_items", items)
        positions: dict[tuple[str, str], list[int]] = {}
        for index, item in enumerate(items):
            positions.setdefault((item.type, item.key), []).append(index)
        problems: list[tuple[int, ErrorDetail]] = []
        for (config_type, config_key), found in positions.items():
            if len(found) > 1:
                problems += [(index, ErrorDetail(message=f"同一批中有 {len(found)} 项的类型和编码相同，无法判断该保留哪一项",
                                                 config_type=config_type, config_key=config_key, path=f"items[{index}]"))
                             for index in found]
        unique = [(index, item) for index, item in enumerate(items) if len(positions[(item.type, item.key)]) == 1]
        skipped = [item for _, item in unique if (item.type, item.key) in self.items]
        new = [(index, item) for index, item in unique if (item.type, item.key) not in self.items]
        available = set(self.items) | set(positions)
        for index, item in new:
            try:
                content = parse_config_content(item.type, item.content)
            except ValidationError as e:
                first = e.errors()[0]
                problems.append((index, ErrorDetail(message=_structure_message(first["type"], first["loc"]), config_type=item.type,
                                                    config_key=item.key, path=_item_path(index, first["loc"]))))
                continue
            for ref_type, ref_key, at in _references(item.type, content):
                if (ref_type, ref_key) not in available:
                    problems.append((index, ErrorDetail(message=f"引用的 {ref_type} {ref_key} 不存在", config_type=item.type,
                                                        config_key=item.key, path=f"items[{index}]{at}")))
        if problems:
            raise PlatformError(ErrorCode.VALIDATION_FAILED, "配置校验不通过",
                                [detail for _, detail in sorted(problems, key=lambda p: p[0])])
        for _, item in new:
            self.put(item)
        return ImportReport(imported=len(new),
                            skipped=[(f"config:{item.type}/{item.key}", "已有同类型、同编码的配置项，没有覆盖") for item in skipped])


def _loc_text(loc: Iterable[int | str]) -> str:
    """内容中的位置，C03 的写法：`.levels[0].entries`。"""
    return "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in loc)


def _item_path(index: int, loc: Iterable[int | str]) -> str:
    """错误明细的 `path`：本批中的位置 `items[<序号>]`，后面接内容中的位置，例如 `items[3].levels[0].entries`（C08 第 4 节）。"""
    return f"items[{index}]{_loc_text(loc)}"


def _structure_message(kind: str, loc: Iterable[int | str]) -> str:
    """内容不符合 C06 结构时给用户看的中文说明（C03 第 1 节），迁移的拒绝清单直接使用（MG-11）。"""
    where = _loc_text(loc).lstrip(".") or "内容"
    if kind == "missing":
        return f"缺少 {where}"
    if kind == "extra_forbidden":
        return f"不允许出现 {where}"
    return f"{where} 的值不合法"
