"""审批数据的读写（模块说明第 2 节），经调用方给出的 `UnitOfWork`：提交审批、处理审批都在命令事务中，详情只读。

审批编号取序列 `PF_APPROVAL_SEQ`（Oracle）；替代事务（SQLite）没有序列，取当前最大编号加一。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    ApprovalFlowConfig,
    ApprovalView,
    DocumentPatch,
    DocumentRef,
    ErrorCode,
    ErrorDetail,
    FreezeEntry,
    PlatformError,
    dump_wire,
    parse_wire,
)

from .model import (
    AffectedRow,
    ApprovalRecord,
    FlowSnapshot,
    ProcessRecord,
    TriggerRow,
    decode_progress,
    decode_values,
    encode_progress,
    encode_values,
)
from .sql import key_text
from .tables import APPROVAL_SEQUENCE, pf_approval, pf_approval_affected, pf_approval_freeze, pf_approval_record


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _id(approval_id: str) -> Decimal:
    return Decimal(approval_id)


def _record_row(record: ApprovalRecord) -> dict[str, Any]:
    return {
        "status": record.progress.status,
        "current_level": record.progress.level,
        "progress": _dumps(encode_progress(record.progress)),
        "params": _dumps(record.params),
        "pending_status": record.pending_status,
        "result": _dumps(record.result),
        "finished_at": record.finished_at,
        "final_view": None if record.final_view is None else _dumps(dump_wire(ApprovalView, record.final_view)),
    }


def _to_record(row: Any) -> ApprovalRecord:
    flows = [FlowSnapshot(f["code"], f["name"], parse_wire(ApprovalFlowConfig, f["config"])) for f in json.loads(row.flows)]
    triggers = [TriggerRow(**t) for t in json.loads(row.triggers)]
    pending = json.loads(row.pending)
    return ApprovalRecord(
        approval_id=key_text(row.approval_id), page=row.page, page_title=row.page_title, operation=row.operation,
        operation_label=row.operation_label, source=DocumentRef(row.source_entity, row.source_key), source_label=row.source_label,
        applicant_id=row.applicant_id, applicant_name=row.applicant_name, applicant_department=row.applicant_dept,
        submitted_at=row.submitted_at, flows=flows, triggers=triggers, patch=parse_wire(DocumentPatch, pending["patch"]),
        key_map=dict(pending["keyMap"]), progress=decode_progress(json.loads(row.progress)), params=json.loads(row.params),
        pending_status=row.pending_status, result=json.loads(row.result), finished_at=row.finished_at,
        final_view=None if row.final_view is None else parse_wire(ApprovalView, json.loads(row.final_view)),
    )


class ApprovalStore:
    # ---------------------------------------------------------------- 审批实例

    def next_id(self, uow: UnitOfWork) -> str:
        conn = uow.connection
        if conn.dialect.name == "oracle":
            return key_text(conn.execute(text(f"SELECT {APPROVAL_SEQUENCE}.NEXTVAL FROM DUAL")).scalar_one())
        current = conn.execute(sa.select(sa.func.max(pf_approval.c.approval_id))).scalar()
        return key_text(Decimal(current or 0) + 1)

    def insert(self, uow: UnitOfWork, record: ApprovalRecord, affected: Sequence[AffectedRow]) -> None:
        conn = uow.connection
        conn.execute(sa.insert(pf_approval).values(
            approval_id=_id(record.approval_id), page=record.page, page_title=record.page_title, operation=record.operation,
            operation_label=record.operation_label, source_entity=record.source.entity, source_key=record.source.record_key,
            source_label=record.source_label, applicant_id=record.applicant_id, applicant_name=record.applicant_name,
            applicant_dept=record.applicant_department, submitted_at=record.submitted_at,
            flows=_dumps([{"code": f.code, "name": f.name, "config": dump_wire(ApprovalFlowConfig, f.config)} for f in record.flows]),
            triggers=_dumps([vars(t) for t in record.triggers]),
            pending=_dumps({"patch": dump_wire(DocumentPatch, record.patch), "keyMap": record.key_map}),
            **_record_row(record),
        ))
        if affected:
            conn.execute(sa.insert(pf_approval_affected), [{
                "approval_id": _id(record.approval_id), "flow": a.flow, "block": a.block, "seq": a.seq, "target_table": a.target_table,
                "row_key": a.key, "missing": 1 if a.missing else 0, "triggers": _dumps(a.triggers), "checked": 1 if a.checked else 0,
                "row_data": _dumps(encode_values(a.data)),
            } for a in affected])

    def update(self, uow: UnitOfWork, record: ApprovalRecord) -> None:
        uow.connection.execute(sa.update(pf_approval).where(pf_approval.c.approval_id == _id(record.approval_id))
                               .values(**_record_row(record)))

    def load(self, uow: UnitOfWork, approval_id: str) -> ApprovalRecord | None:
        """读出审批记录，不加锁。处理审批时，审批记录先经 `BusinessLocker` 加锁（`FOR UPDATE WAIT n`，秒数同
        `PLATFORM_LOCK_WAIT_SECONDS`，排在所有业务数据之前；`process.ResolveStage`），同一审批的处理命令依次执行。"""
        try:
            key = _id(approval_id)
        except ArithmeticError:
            return None
        row = uow.connection.execute(sa.select(pf_approval).where(pf_approval.c.approval_id == key)).first()
        return None if row is None else _to_record(row)

    def _list(self, uow: UnitOfWork, condition: Any) -> list[ApprovalRecord]:
        rows = uow.connection.execute(sa.select(pf_approval).where(condition).order_by(pf_approval.c.approval_id.desc()))
        return [_to_record(r) for r in rows]

    def pending(self, uow: UnitOfWork) -> list[ApprovalRecord]:
        """未结束的审批，按编号倒序（待办列表按审批人筛选）。"""
        return self._list(uow, pf_approval.c.status == "pending")

    def by_applicant(self, uow: UnitOfWork, user_id: str) -> list[ApprovalRecord]:
        """某人发起的全部审批，按编号倒序。"""
        return self._list(uow, pf_approval.c.applicant_id == user_id)

    def everything(self, uow: UnitOfWork) -> list[ApprovalRecord]:
        """全部审批，按编号倒序（"全部审批"页签按审批人筛选）。"""
        return self._list(uow, sa.true())

    def by_source(self, uow: UnitOfWork, entity: str, record_key: str) -> list[ApprovalRecord]:
        """来源为这张单据（实体、主键）的全部审批，按编号倒序。"""
        return self._list(uow, sa.and_(pf_approval.c.source_entity == entity, pf_approval.c.source_key == record_key))

    def by_ids(self, uow: UnitOfWork, approval_ids: Sequence[str]) -> list[ApprovalRecord]:
        """这些编号的审批，按编号倒序。"""
        if not approval_ids:
            return []
        return self._list(uow, pf_approval.c.approval_id.in_([_id(i) for i in dict.fromkeys(approval_ids)]))

    # ---------------------------------------------------------------- 受影响单据的行

    def affected(self, uow: UnitOfWork, approval_id: str) -> list[AffectedRow]:
        rows = uow.connection.execute(sa.select(pf_approval_affected)
                                      .where(pf_approval_affected.c.approval_id == _id(approval_id))
                                      .order_by(pf_approval_affected.c.flow, pf_approval_affected.c.block,
                                                pf_approval_affected.c.seq))
        return [AffectedRow(flow=r.flow, block=r.block, seq=int(r.seq), target_table=r.target_table, key=r.row_key,
                            missing=bool(r.missing), triggers=[int(i) for i in json.loads(r.triggers)], checked=bool(r.checked),
                            data=decode_values(json.loads(r.row_data))) for r in rows]

    def set_checked(self, uow: UnitOfWork, approval_id: str, rows: Sequence[AffectedRow]) -> None:
        t = pf_approval_affected
        for row in rows:
            uow.connection.execute(sa.update(t).where(t.c.approval_id == _id(approval_id), t.c.flow == row.flow,
                                                      t.c.block == row.block, t.c.seq == row.seq)
                                   .values(checked=1 if row.checked else 0))

    # ---------------------------------------------------------------- 处理记录

    def add_record(self, uow: UnitOfWork, approval_id: str, record: ProcessRecord) -> None:
        uow.connection.execute(sa.insert(pf_approval_record).values(
            approval_id=_id(approval_id), seq=record.seq, level_no=record.level, user_id=record.user_id,
            user_name=record.user_name, action=record.action, acted_at=record.at, remark=record.comment,
            checked=_dumps(record.checked), params=_dumps(record.params)))

    def records(self, uow: UnitOfWork, approval_id: str) -> list[ProcessRecord]:
        t = pf_approval_record
        rows = uow.connection.execute(sa.select(t).where(t.c.approval_id == _id(approval_id)).order_by(t.c.seq))
        return [ProcessRecord(seq=int(r.seq), level=int(r.level_no), user_id=r.user_id, user_name=r.user_name, action=r.action,
                              at=r.acted_at if isinstance(r.acted_at, datetime) else datetime.fromisoformat(str(r.acted_at)),
                              comment=r.remark, checked=json.loads(r.checked), params=json.loads(r.params)) for r in rows]

    # ---------------------------------------------------------------- 冻结记录（AP-03、AP-06）

    def freeze(self, uow: UnitOfWork, entries: Sequence[FreezeEntry]) -> None:
        """登记冻结记录。只登记在本事务已锁住的单据和行上（触发审批先按统一顺序加锁、锁后单独查冻结，AP-02、AP-06），
        所以两个命令不会同时登记同一条；（根表、主键）已有记录时返回 409 FROZEN_BY_APPROVAL。"""
        conn = uow.connection
        for entry in entries:
            try:
                conn.execute(sa.insert(pf_approval_freeze).values(root_table=entry.table, record_key=entry.record_key,
                                                                  approval_id=_id(entry.approval_id)))
            except IntegrityError:
                raise PlatformError(ErrorCode.FROZEN_BY_APPROVAL, "要冻结的数据已在另一个未结束的审批中", [
                    ErrorDetail(message=f"{entry.table} 中主键为 {entry.record_key} 的数据已被另一个审批冻结",
                                row_key=entry.record_key)]) from None

    def frozen(self, uow: UnitOfWork, table: str, record_keys: Sequence[str]) -> dict[str, FreezeEntry]:
        keys = list(dict.fromkeys(record_keys))
        found: dict[str, FreezeEntry] = {}
        t = pf_approval_freeze
        for start in range(0, len(keys), 1000):
            chunk = keys[start:start + 1000]
            for row in uow.connection.execute(sa.select(t).where(t.c.root_table == table, t.c.record_key.in_(chunk))):
                found[row.record_key] = FreezeEntry(approval_id=key_text(row.approval_id), table=row.root_table,
                                                    record_key=row.record_key)
        return found

    def freezes_of(self, uow: UnitOfWork, approval_id: str) -> list[FreezeEntry]:
        t = pf_approval_freeze
        rows = uow.connection.execute(sa.select(t).where(t.c.approval_id == _id(approval_id)).order_by(t.c.root_table, t.c.record_key))
        return [FreezeEntry(approval_id=approval_id, table=r.root_table, record_key=r.record_key) for r in rows]

    def release(self, uow: UnitOfWork, approval_id: str) -> None:
        """审批结束（通过、驳回或撤回）时解除本审批的全部冻结。"""
        uow.connection.execute(sa.delete(pf_approval_freeze).where(pf_approval_freeze.c.approval_id == _id(approval_id)))
