"""已结束、结束时没有保存修改内容的审批：按已有记录还原结束那一刻的修改内容（C06 7.6"已结束的审批"），由迁移 ap_0003
执行一次，写进 `pf_approval.final_view`。

ap_0002 之前结束的审批没有存 `final_view`。能还原的只有已通过的，依据都是当时写下的记录，不按现在的数据重算：
- 来源单据的修改前：提交审批的那条命令（PF_COMMAND 中 `result.outcome` 为 approvalSubmitted、`approvals` 中有本审批）返回的行，
  即提交时数据库中的值；这些行带着本审批的冻结标记，审批期间没人能改（AP-03），提交时的值就是结束时的修改前。
- 来源单据的修改后：最终通过的那条命令（`approval.pass`，`approvals` 中本审批为 approved）返回的行，即写入后的值。
- 受影响单据的修改前：`pf_approval_affected.row_data`（提交时查到的值）；修改表在审批流的冻结表中，审批期间不会变。
- 受影响单据的修改后：通过命令的审计差异中这张表、这一行的新值（没注册的表经 TableWriter 写入，审计按表名记）；
  不是要写的列，修改后等于修改前。
- 来源单据的小数位：显示列的 `precision`，没写时取实体配置（PF_CONFIG_ITEM 中的实体）字段的 `scale`，同 `view.py`；
  受影响单据（修改表没注册）只取 `precision`。

还原不了、保持为空的（详情显示"结束时的值没有保存"）：驳回、撤回的审批（结束时没有算修改后，哪里都没有存）；找不到提交
或通过的命令，或命令中没有要显示的行、行上没有本审批的冻结标记；`master`、`detail` 块写了条件，或者两种块都没有配置（要按
当时的数据判断显示哪些行和字段）；受影响单据有 `master.` 列、不在冻结表中，或者勾选的行在审计中找不到写入记录（修改表
注册过时审计按实体记）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy import Connection

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    ApprovalView,
    DeleteRows,
    DisplayBlock,
    EntityConfig,
    MasterAdd,
    MasterDelete,
    MasterModify,
    Row,
    RowRef,
    Value,
    ViewAffectedTable,
    ViewCell,
    ViewDetailTable,
    ViewMasterTable,
    ViewRow,
    dump_wire,
    parse_config_content,
)

from .calc import coerce
from .model import AffectedRow, ApprovalRecord
from .patch import bill_key, values_of
from .store import ApprovalStore
from .tables import pf_approval
from .view import Evaluator, _columns, cell

# 只读的其他模块的表：write-pipeline 的命令记录、config 的配置项
_command = sa.table("pf_command", sa.column("operation", sa.String), sa.column("result", sa.Text),
                    sa.column("audit_diff", sa.Text), sa.column("created_at", sa.DateTime))
_config_item = sa.table("pf_config_item", sa.column("config_type", sa.String), sa.column("config_key", sa.String),
                        sa.column("content", sa.Text))

_MARGIN = timedelta(minutes=1)
"""按时间找命令时前后多放的余量：审批的提交、结束时间精确到秒，命令的创建时间带小数秒。"""


@dataclass
class _Uow:
    """`ApprovalStore` 只用事务的连接；迁移中没有 UnitOfWork，用迁移的连接。"""

    connection: Connection


@dataclass
class _Commands:
    """一个审批的提交命令和最终通过命令的结果。"""

    before: dict[tuple[str, str], dict[str, Any]]
    """提交命令返回的行：（实体、主键）→ 行（values、frozen）。"""
    after: dict[tuple[str, str], dict[str, Any]]
    """通过命令返回的行。"""
    written: dict[tuple[str, str], dict[str, Any]]
    """通过命令的审计差异：（表或实体的大写名、主键）→ 列的大写名 → 新值。"""


def restore_final_views(connection: Connection) -> list[tuple[str, bool]]:
    """对已结束、`final_view` 为空的审批逐个还原；返回（审批编号、是否还原）。"""
    uow = cast(UnitOfWork, _Uow(connection))
    store = ApprovalStore()
    ids = [str(r[0]) for r in connection.execute(
        sa.select(pf_approval.c.approval_id).where(pf_approval.c.status != "pending", pf_approval.c.final_view.is_(None))
        .order_by(pf_approval.c.approval_id))]
    entities = _entities(connection) if ids else {}
    done: list[tuple[str, bool]] = []
    for approval_id in ids:
        record = store.load(uow, approval_id)
        assert record is not None
        view = restore_view(connection, record, store.affected(uow, approval_id), entities)
        if view is not None:
            connection.execute(sa.update(pf_approval).where(pf_approval.c.approval_id == Decimal(approval_id))
                               .values(final_view=json.dumps(dump_wire(ApprovalView, view), ensure_ascii=False,
                                                             separators=(",", ":"))))
        done.append((record.approval_id, view is not None))
    return done


def _entities(connection: Connection) -> dict[str, EntityConfig]:
    rows = connection.execute(sa.select(_config_item.c.config_key, _config_item.c.content)
                              .where(_config_item.c.config_type == "entity"))
    return {r.config_key: cast(EntityConfig, parse_config_content("entity", json.loads(r.content))) for r in rows}


def _commands(connection: Connection, record: ApprovalRecord) -> _Commands | None:
    assert record.finished_at is not None
    rows = connection.execute(sa.select(_command.c.operation, _command.c.result, _command.c.audit_diff)
                              .where(_command.c.created_at.between(record.submitted_at - _MARGIN, record.finished_at + _MARGIN))
                              .order_by(_command.c.created_at))
    submit = final = None
    for row in rows:
        if row.result is None:
            continue
        result = json.loads(row.result)
        mine = [a for a in result.get("approvals") or [] if a.get("approvalId") == record.approval_id]
        if not mine:
            continue
        if submit is None and result.get("outcome") == "approvalSubmitted":
            submit = result
        if row.operation == "approval.pass" and mine[0].get("status") == "approved":
            final = (result, json.loads(row.audit_diff) if row.audit_diff else [])
    if submit is None or final is None:
        return None
    written: dict[tuple[str, str], dict[str, Any]] = {}
    for change in final[1]:
        fields = {name.upper(): value.get("new") for name, value in (change.get("fields") or {}).items()}
        written.setdefault((str(change.get("entity")).upper(), str(change.get("rowKey"))), {}).update(fields)
    return _Commands(before={(r["entity"], r["rowKey"]): r for r in submit.get("rows") or []},
                     after={(r["entity"], r["rowKey"]): r for r in final[0].get("rows") or []}, written=written)


def _like(before: Value, value: Any, precision: int | None) -> Value:
    """审计中的新值是文本；修改前是数值或者列写了小数位时按数值显示。"""
    if value is None or isinstance(value, bool):
        return value  # type: ignore[no-any-return]
    if isinstance(before, Decimal) or precision is not None:
        return coerce("number", value)
    return value  # type: ignore[no-any-return]


def restore_view(connection: Connection, record: ApprovalRecord, affected: Sequence[AffectedRow],
                 entities: Mapping[str, EntityConfig]) -> ApprovalView | None:
    """按提交、通过的命令和提交时的受影响行还原结束那一刻的 `view`；还原不了时为 None（范围见文件说明）。"""
    if record.progress.status != "approved" or record.finished_at is None:
        return None
    blocks = [(flow, b) for flow in record.flows for b in flow.config.display]
    source_blocks = [b for _, b in blocks if b.region in ("master", "detail")]
    if not source_blocks or any(b.condition is not None for b in source_blocks):
        return None
    commands = _commands(connection, record)
    if commands is None:
        return None
    source = _SourceRows(record, commands, entities)
    master = source.master(source_blocks)
    details = source.details(source_blocks)
    if master is None or details is None or source.failed:
        return None
    freeze = {f.table.upper() for flow in record.flows for f in flow.config.freeze}
    tables = []
    for flow, block in blocks:
        if block.region != "affected" or block.selection == "hidden":
            continue
        found = _affected(record, flow.code, block, affected, commands, freeze=freeze)
        if found is None:
            return None
        tables.append(found)
    return ApprovalView(master=master, details=details, affected=tables)


class _SourceRows:
    """来源单据的修改前（提交命令返回的行）、修改后（通过命令返回的行），对照 `Evaluator._source_tables`。"""

    def __init__(self, record: ApprovalRecord, commands: _Commands, entities: Mapping[str, EntityConfig]) -> None:
        self.record, self.commands, self.entities = record, commands, entities
        self.failed = False
        self.flows_of = {(t.entity, t.row_key or t.client_row_id or ""): list(t.flows) for t in record.triggers}

    def _row(self, side: Mapping[tuple[str, str], dict[str, Any]], code: str, key: str, *, frozen: bool) -> Row | None:
        found = side.get((code, key))
        entity = self.entities.get(code)
        if found is None or entity is None or (frozen and (found.get("frozen") or {}).get("approvalId") != self.record.approval_id):
            self.failed = True
            return None
        # 命令结果中的值是接口格式（数值为文本），按实体字段的类型转成后端内部的值，再按 `view.cell` 显示
        return Row(entity=code, row_key=key, client_row_id=None, values=values_of(entity, found.get("values") or {}))

    def master(self, blocks: Sequence[DisplayBlock]) -> ViewMasterTable | None:
        record = self.record
        master_blocks = [b for b in blocks if b.region == "master"]
        if not master_blocks:
            return ViewMasterTable(key="master", title=record.page_title, columns=[], rows=[])
        code = record.source.entity
        entity = self.entities.get(code)
        if entity is None:
            return None
        patch = record.patch.master
        bill = bill_key(record.patch, record.key_map)
        op = "add" if isinstance(patch, MasterAdd) else "delete" if isinstance(patch, MasterDelete) else (
            "modify" if isinstance(patch, MasterModify) else None)
        before = None if op == "add" else self._row(self.commands.before, code, bill, frozen=True)
        after = None if op == "delete" else self._row(self.commands.after, code, bill, frozen=False)
        columns = _columns(master_blocks)
        first = master_blocks[0]
        row = Evaluator._source_row(columns, entity, before, after, op, self.flows_of.get((code, bill), []))
        return ViewMasterTable(key=first.key, title=first.title, columns=[c.label for c in columns], rows=[row])

    def details(self, blocks: Sequence[DisplayBlock]) -> list[ViewDetailTable] | None:
        record = self.record
        by_source: dict[str, list[DisplayBlock]] = {}
        for block in blocks:
            if block.region == "detail":
                by_source.setdefault(block.source, []).append(block)
        tables = []
        for code, group in by_source.items():
            entity = self.entities.get(code)
            if entity is None:
                return None
            columns = _columns(group)
            rows = []
            for change in record.patch.details:
                if change.entity != code:
                    continue
                key = change.row_key if change.op != "add" else record.key_map.get(change.client_row_id, "")  # type: ignore[union-attr]
                before = None if change.op == "add" else self._row(self.commands.before, code, key, frozen=True)
                after = None if change.op == "delete" else self._row(self.commands.after, code, key, frozen=False)
                rows.append(Evaluator._source_row(columns, entity, before, after, change.op, self.flows_of.get((code, key), [])))
            lead = group[0]
            tables.append(ViewDetailTable(key=lead.key, title=lead.title, columns=[c.label for c in columns], rows=rows))
        return tables


def _affected(record: ApprovalRecord, flow: str, block: DisplayBlock, affected: Sequence[AffectedRow], commands: _Commands,
              *, freeze: set[str]) -> ViewAffectedTable | None:
    """受影响单据的一块：修改前为提交时查到的值，修改后为通过命令写入的值，对照 `Evaluator._affected_table`。
    写入的值按审计中"表名 + 主键"找（没注册的表经 TableWriter 写，审计按表名记）；勾选的行找不到写入记录时（例如修改表
    注册过，审计按实体记，或者 `master.` 列要按所属单据重算）还原不了。"""
    target = (block.target_table or block.source).upper()
    if target not in freeze or any(c.field.startswith("master.") for c in block.columns):
        return None
    selection = block.selection or "checked"
    writes = bool(block.actions)
    deleting = any(isinstance(a, DeleteRows) for a in block.actions)
    rows = sorted((a for a in affected if a.flow == flow and a.block == block.key), key=lambda a: a.seq)
    view_rows: list[ViewRow] = []
    for row in [a for a in rows if not a.missing] + [a for a in rows if a.missing]:
        if row.missing:
            cells = [ViewCell(before=cell(row.data.get(c.field.upper()), c.precision), after=cell(row.data.get(c.field.upper()),
                                                                                                c.precision))
                     for c in block.columns]
            view_rows.append(ViewRow(op="none", cells=cells, missing=True))
            continue
        chosen = selection == "all" or row.checked
        updates: dict[str, Any] = {}
        if chosen and writes:
            found = commands.written.get((target, row.key or ""))
            if found is None:
                return None
            updates = found
        cells = []
        for column in block.columns:
            before = row.data.get(column.field.upper())
            name = (column.target_column or column.field).upper()
            after = _like(before, updates[name], column.precision) if name in updates else before
            cells.append(ViewCell(before=cell(before, column.precision),
                                  after=None if chosen and deleting else cell(after, column.precision)))
        op = "none" if not chosen else "delete" if deleting else "modify" if any(c.before != c.after for c in cells) else "none"
        view_rows.append(ViewRow(op=op, cells=cells, ref=RowRef(key=row.key or ""), checked=chosen))  # type: ignore[arg-type]
    title = f"{block.title}（{record.flow(flow).name}）" if len(record.flows) > 1 else block.title
    return ViewAffectedTable(flow=flow, key=block.key, title=title, selection=selection,  # type: ignore[arg-type]
                             editable=False, columns=[c.label for c in block.columns], rows=view_rows)


__all__ = ["restore_final_views", "restore_view"]
