"""按钮命令的选中行（C02 第 1 节 `params.selectedRows`）和它们所属的单据（OP-05、OP-08）。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from cost_platform.contracts.ports import RelatedQuery, UnitOfWork
from cost_platform.contracts.types import (
    Command,
    DocumentData,
    DocumentRef,
    ErrorCode,
    ExecutionContext,
    PageView,
    PlatformError,
    RelationKeyFinder,
    Row,
)
from cost_platform.contracts.values import from_wire


@dataclass(frozen=True)
class SelectedRow:
    """一行选中的数据：实体和主键（C02 第 1 节）。"""

    entity: str
    row_key: str


def selected_rows(command: Command) -> list[SelectedRow]:
    """`params.selectedRows`，按提交的顺序，重复的只算一次；没有这一项时为空。格式不对时 400 INVALID_REQUEST。"""
    raw = command.params.get("selectedRows")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PlatformError(ErrorCode.INVALID_REQUEST, "params.selectedRows 必须是数组")
    rows: list[SelectedRow] = []
    for item in raw:
        entity = item.get("entity") if isinstance(item, dict) else None
        key = item.get("rowKey") if isinstance(item, dict) else None
        if not isinstance(entity, str) or not entity or not isinstance(key, str) or not key:
            raise PlatformError(ErrorCode.INVALID_REQUEST, "params.selectedRows 的每一项为 {entity, rowKey}")
        row = SelectedRow(entity, key)
        if row not in rows:
            rows.append(row)
    return rows


def requires_selection(view: PageView, operation: str) -> bool:
    """页面上引用这个操作的业务按钮都要求选中行时为 True（C06 第 3 节 `requiresSelection`，OP-05）。

    页面视图只列出当前角色有权限的按钮；没有按钮引用这个操作时为 False，有没有权限由操作权限阶段判断。"""
    buttons = [b for area in (view.master, *view.details) for b in area.buttons if b.operation == operation]
    return bool(buttons) and all(b.requires_selection for b in buttons)


def sort_key(ref: DocumentRef) -> tuple[str, int, int, str]:
    """按（实体、主键）排序，数字主键按数值，与 write-pipeline 加锁的顺序相同（WP-03）。"""
    key = ref.record_key
    if key.lstrip("-").isdigit():
        return (ref.entity, 0, int(key), "")
    return (ref.entity, 1, 0, key)


class SelectionResolver:
    """找出选中行所属的单据（OP-08）。

    - 页面主表实体的行就是单据本身（单表页为这一行）。
    - 明细实体的行：经 `RelatedQuery` 按关联键查这个明细实体（目标键、来源键都是明细主键），找到的对象的
      `record_key` 是所属主单的主键（C08 第 9 节）。查不到的行在点按钮前已被删除，不属于任何单据，由动作执行阶段
      按操作的 `rowNotFound` 处理（WP-05）。
    - 不属于本页面的实体：400 INVALID_REQUEST。
    """

    def __init__(self, related: RelatedQuery) -> None:
        self._related = related

    def documents(self, uow: UnitOfWork, ctx: ExecutionContext, view: PageView,
                  rows: Sequence[SelectedRow]) -> list[DocumentRef]:
        """选中行所属的单据，按选中的先后，同一单据只出现一次。"""
        master = view.master.entity
        details = {d.entity: d for d in view.details}
        found: list[DocumentRef] = []
        detail_keys: dict[str, list[str]] = {}
        for row in rows:
            if row.entity == master:
                _add(found, [DocumentRef(master, row.row_key)])
            elif row.entity in details:
                detail_keys.setdefault(row.entity, []).append(row.row_key)
            else:
                raise PlatformError(ErrorCode.INVALID_REQUEST, f"选中的行不属于页面 {view.page_code}：{row.entity}")
        owners: dict[tuple[str, str], DocumentRef] = {}
        for entity, keys in detail_keys.items():
            owners.update(self._owners(uow, ctx, master, entity, details[entity].primary_key, keys))
        for row in rows:
            owner = owners.get((row.entity, row.row_key))
            if owner is not None:
                _add(found, [owner])
        return found

    def _owners(self, uow: UnitOfWork, ctx: ExecutionContext, master: str, entity: str, primary_key: str,
                keys: list[str]) -> dict[tuple[str, str], DocumentRef]:
        field_type = next((f.type for f in ctx.config.entity(entity).fields if f.name == primary_key), "text")
        finder = RelationKeyFinder(kind="relationKey", entity=entity, target_key=primary_key,
                                   source_key=f"{entity}.{primary_key}", rows="all")
        try:
            rows = [Row(entity=entity, row_key=k, client_row_id=None, values={primary_key: from_wire(field_type, k)})
                    for k in keys]
        except ValueError:
            raise PlatformError(ErrorCode.INVALID_REQUEST, f"选中的 {entity} 行的主键格式不对") from None
        source = DocumentData(ref=DocumentRef(master, ""),
                              master=Row(entity=master, row_key=None, client_row_id=None, values={}),
                              details={entity: rows})
        owners: dict[tuple[str, str], DocumentRef] = {}
        for target in self._related.find(uow, finder, source):
            if target.missing or target.record_key is None:
                continue
            for row_key in target.row_keys:
                owners[(entity, row_key)] = DocumentRef(master, target.record_key)
        return owners


def _add(found: list[DocumentRef], refs: Iterable[DocumentRef]) -> None:
    for ref in refs:
        if ref not in found:
            found.append(ref)
