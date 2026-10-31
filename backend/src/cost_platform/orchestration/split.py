"""按单据提交（C02 v10 第 1 节；用户 2026-10-31："我也是要求一单一单的提交啊……100个单据 失败了1个，就全部失败"
是不可以的）：一个命令涉及几张单据时，拆成每张单据一个子命令，各自一个事务，各自成功或失败。

同旧系统：`cost-web/src/v3/composables/meta-v3/useWorkingSetStore.ts` 第 960–1080 行逐张单据发保存请求，失败的记下原因、
继续下一张；后端 `DynamicDataService.save` 一张单据一个事务。新平台在后端拆：前端仍是一个请求。

- 页面保存带 2 张及以上单据：每张单据一个子命令，按提交的顺序。
- 按钮的 `params.selectedRows` 有 2 行及以上、都是页面主表实体的行：每行一个子命令，`selectedRows` 只留这一行。
  明细区的选中行都属于明细区显示的那一张单据，不拆。
- 其余命令（一张单据、不选行的按钮、审批处理）不拆，照原来的单命令执行。
- 子命令的请求键由原请求键和单据决定（UUID 第 5 版），同一请求重发时得到相同的子请求键：已提交的单据按命令记录
  返回原结果、不再执行，失败的单据（已回滚、没有命令记录）重新执行（WP-01、WP-02）。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from cost_platform.contracts.types import (
    Command,
    CommandResult,
    DocumentFailure,
    ExecutionContext,
    MasterAdd,
    Outcome,
    PlatformError,
)


@dataclass(frozen=True)
class Part:
    """一张单据的子命令。`row_key`、`client_row_id` 给出一个：新增的单据为 clientRowId。"""

    command: Command
    entity: str
    row_key: str | None
    client_row_id: str | None


def sub_request_key(request_key: str, entity: str, identity: str) -> str:
    """子命令的请求键：原请求键为名字空间，"实体/主键或 clientRowId"为名字，UUID 第 5 版。"""
    return str(uuid.uuid5(uuid.UUID(request_key), f"{entity}/{identity}"))


def _selected(command: Command) -> list[dict[str, Any]] | None:
    """`params.selectedRows` 中格式正确的项，按提交的顺序去重；格式不对时为 None（不拆，由 operations 照常报错）。"""
    raw = command.params.get("selectedRows")
    if not isinstance(raw, list):
        return None
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            return None
        entity, row_key = item.get("entity"), item.get("rowKey")
        if not isinstance(entity, str) or not isinstance(row_key, str) or not entity or not row_key:
            return None
        if (entity, row_key) not in seen:
            seen.add((entity, row_key))
            rows.append(item)
    return rows


def split_by_document(command: Command, ctx: ExecutionContext) -> list[Part] | None:
    """拆成每张单据一个子命令；不用拆时为 None。"""
    if command.documents:
        if len(command.documents) < 2:
            return None
        parts: list[Part] = []
        for document in command.documents:
            master = document.master
            if isinstance(master, MasterAdd):
                row_key, client_row_id, identity = None, master.client_row_id, master.client_row_id
            else:
                row_key, client_row_id, identity = master.row_key, None, master.row_key
            sub = command.model_copy(update={
                "request_key": sub_request_key(command.request_key, document.entity, identity), "documents": [document]})
            parts.append(Part(sub, document.entity, row_key, client_row_id))
        return parts
    if command.page is None:
        return None
    rows = _selected(command)
    if rows is None or len(rows) < 2:
        return None
    try:
        master_entity = ctx.config.page_view(command.page).master.entity
    except PlatformError:
        return None  # 页面不存在、不能访问：照原来的单命令执行，由各阶段照常报错
    if any(row["entity"] != master_entity for row in rows):
        return None
    return [Part(command.model_copy(update={
                "request_key": sub_request_key(command.request_key, row["entity"], row["rowKey"]),
                "params": {**command.params, "selectedRows": [row]}}),
            row["entity"], row["rowKey"], None)
            for row in rows]


def _outcome(results: Sequence[CommandResult]) -> Outcome:
    """合并后的 `outcome`：有单据提交了审批为 approvalSubmitted；否则有写入的为 saved；否则 unchanged。"""
    outcomes = {r.outcome for r in results}
    if "approvalSubmitted" in outcomes:
        return "approvalSubmitted"
    if "saved" in outcomes:
        return "saved"
    return "unchanged"


def merge_results(command: Command, done: Sequence[CommandResult], failed: Sequence[DocumentFailure]) -> CommandResult:
    """各张单据的结果按提交的顺序合在一起，请求键为原请求键。"""
    id_map: dict[str, str] = {}
    for result in done:
        id_map.update(result.id_map)
    return CommandResult(
        request_key=command.request_key,
        outcome=_outcome(done),
        rows=[row for result in done for row in result.rows],
        id_map=id_map,
        prompts=[prompt for result in done for prompt in result.prompts],
        skipped=[skip for result in done for skip in result.skipped],
        approvals=[approval for result in done for approval in result.approvals],
        failed=list(failed),
    )
