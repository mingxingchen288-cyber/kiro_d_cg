"""write-pipeline 的管道阶段（C08 第 6 节，`.reports/modules/plugin-spec.md` 第 3 节）。

阶段的 `name` 是 orchestration `STAGE_ORDER` 中的位置名；同一位置的几个实现由各自的 `applies` 决定这次执行哪个。

| 位置 | 阶段 | applies | run |
|---|---|---|---|
| 确定涉及的单据 | `loader.PageSaveInvolved` | `command.documents` 不为空 | 每张单据一项 |
| 加锁读取 | `LockStage` | `involved` 或 `intents` 所属单据中有还没读入 `current` 的已有单据 | `DocumentLoader.lock` |
| 合并修改 | `MergePatchesStage` | `command.documents` 不为空 | `DocumentMerger.merge_patches` |
| 合并意图 | `MergeIntentsStage` | `intents` 不为空 | `IntentMerger.absorb`（不加锁、不做冻结检查） |
| 计算与规则 | `RecalculateStage` | `changes.rows` 不为空 | `lookups.fill_lookup_fields` + `Recalculator.run` + `check_required` |
| 写入变更 | `WriteChangesStage` | `changes.rows` 不为空 | `ChangeWriter.apply` |

按钮的每个动作一轮："展开动作 → 加锁读取 → 冻结检查（只查这一轮新读入的单据）→ 合并意图 → 计算与规则"，由编排执行；
没有动作的命令这几步执行一次。阶段实例不存命令级的状态，一个命令的数据都在 `CommandState` 中。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    BusinessValue,
    CommandState,
    DetailAdd,
    DetailModify,
    DocumentRef,
    ExecutionContext,
    MasterAdd,
    MasterDelete,
    MasterModify,
)

from .calc import Recalculator, check_required, patch_needs_details
from .loader import DocumentLoader, document_ref, is_new_document, known_missing, sort_key
from .lookups import fill_lookup_fields
from .merge import DocumentMerger, IntentMerger, RowRef
from .plan import find_change
from .writer import ChangeWriter


def _unread(state: CommandState) -> list[DocumentRef]:
    """`involved` 和 `intents` 所属单据中还没有读入 `current` 的已有单据（新增的单据没有可读的行）。"""
    wanted = dict.fromkeys([*state.involved, *(i.document for i in state.intents)])
    return [r for r in wanted if not is_new_document(state, r) and r not in state.current and not known_missing(state, r)]


def _needs_details(state: CommandState, ctx: ExecutionContext) -> Callable[[DocumentRef], bool]:
    """Patch 里的单据按 `calc.patch_needs_details`（只改规则不读的字段时不读明细，WP-08、WP-10）；其余单据（按钮的动作、
    审批找到的）都读明细。"""
    in_patch = {document_ref(p.entity, p.master) for p in state.command.documents}
    from_patch = patch_needs_details(state, ctx)
    return lambda ref: from_patch(ref) if ref in in_patch else True


class LockStage:
    """加锁读取（WP-03、WP-05、WP-18）：先把 `intents` 所属的、不在 `involved` 中的已有单据按（实体、主键）排序加入
    `involved`，再把 `involved` 中还没读入的单据按统一顺序加锁读入 `current`（`DocumentLoader.lock`）。动作轮次中新找到的
    单据只能排在已持有的锁之后（往后找）；往前、同层找到的已在"确定涉及的单据"一起锁住（operations、approval），这里再锁
    一次并读出。已不存在的单据按 `rowNotFound` 处理（写 `skipped` 或 409）。"""

    name = "加锁读取"

    def __init__(self, loader: DocumentLoader) -> None:
        self._loader = loader

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return bool(_unread(state))

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        outside = {r for r in _unread(state) if r not in state.involved}
        state.involved.extend(sorted(outside, key=sort_key))
        self._loader.lock(uow, state, ctx, needs_details=_needs_details(state, ctx))


class MergePatchesStage:
    """合并修改（WP-04–WP-06、WP-14–WP-16）：把 `command.documents` 合并进 `candidate`，写入 `changes`。"""

    name = "合并修改"

    def __init__(self, merger: DocumentMerger) -> None:
        self._merger = merger

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return bool(state.command.documents)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        self._merger.merge_patches(state, ctx)


class MergeIntentsStage:
    """合并意图（WP-18）：把动作、审批展开出的 `intents` 合并进 `candidate` 并清空。所属单据已由这一轮的"加锁读取"
    读入、由"冻结检查"检查过，这里不再加锁。"""

    name = "合并意图"

    def __init__(self, intents: IntentMerger) -> None:
        self._intents = intents

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return bool(state.intents)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        self._intents.absorb(uow, state, ctx)


def _still_changed(state: CommandState, entity: str, row_key: str, changes: Mapping[str, BusinessValue]) -> bool:
    change = find_change(state.changes, entity, row_key)
    return change is not None and change.op == "modify" and bool(set(changes) & set(change.values))


def patched_rows(state: CommandState) -> set[RowRef]:
    """本次 Patch 新增、修改的行（WP-07 必填检查的范围），由 `command` 和变更计划推出，与 `DocumentMerger.merge_patches`
    的返回相同：新增的行；Patch 修改、并且改的字段现在仍有变化的行。删除整张单据时它的明细不算。"""
    found: set[RowRef] = set()
    for patch in state.command.documents:
        master = patch.master
        if isinstance(master, MasterDelete):
            continue
        if isinstance(master, MasterAdd):
            found.add((patch.entity, master.client_row_id))
        elif isinstance(master, MasterModify) and _still_changed(state, patch.entity, master.row_key, master.changes):
            found.add((patch.entity, master.row_key))
        for detail in patch.details:
            if isinstance(detail, DetailAdd):
                found.add((detail.entity, detail.client_row_id))
            elif isinstance(detail, DetailModify) and _still_changed(state, detail.entity, detail.row_key, detail.changes):
                found.add((detail.entity, detail.row_key))
    return found


class RecalculateStage:
    """计算与规则（WP-07、WP-08、WP-15）：新增的行、换了 Lookup 字段值的行先按 Lookup 带出没有物理列的字段
    （`lookups.fill_lookup_fields`）；对有变化的单据按 commit 阶段求值，计算带出的变化并入 `changes`，提示写入
    `prompts`、效果写入 `effects`；再检查本次 Patch 新增、修改的行的必填字段。规则拒绝时 422 RULE_REJECTED，必填为空时
    422 VALIDATION_FAILED。"""

    name = "计算与规则"

    def __init__(self, calc: Recalculator) -> None:
        self._calc = calc

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return bool(state.changes.rows)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        fill_lookup_fields(uow, state, ctx)
        field_states = self._calc.run(state, ctx)
        check_required(state, ctx, patched_rows(state), field_states)


class WriteChangesStage:
    """写入变更（WP-06、WP-09）：按变更计划写业务表，提交审批的单据不写；新增行取得的主键写回 `changes`。"""

    name = "写入变更"

    def __init__(self, writer: ChangeWriter) -> None:
        self._writer = writer

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return bool(state.changes.rows)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        self._writer.apply(uow, state, ctx)
