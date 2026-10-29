"""审批数据（模块说明第 2 节）在内存中的结构，以及存进 CLOB 列时的 JSON 编码。

一个审批：所属页面、来源单据、发起人、提交时间、状态、提交时命中的各审批流定义（AP-13）、触发本审批的行、待审修改
（含新增行提交时取得的主键）、各级各节点进度、各级填写的参数、执行结果。受影响单据的行和处理记录各有一张表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from cost_platform.contracts.decimal_text import format_decimal
from cost_platform.contracts.types import ApprovalFlowConfig, DocumentPatch, DocumentRef, RowOp, Value

from .routing import Member, Node, Progress


@dataclass
class TriggerRow:
    """来源单据中保存时被判断的一行；`flows` 为这一行在第 1 级成立的审批流（为空表示随审批等待，只用于显示）。"""

    id: int
    entity: str
    op: RowOp
    row_key: str | None
    """已有的行为它的主键；新增行为提交时取得的主键（AP-02）。"""
    client_row_id: str | None
    flows: list[str]


@dataclass
class FlowSnapshot:
    """提交时命中的审批流定义，审批按它走完（AP-13）。"""

    code: str
    name: str
    config: ApprovalFlowConfig


@dataclass
class AffectedRow:
    """受影响单据的一行（C06 7.5）：修改表的主键、找到它的触发行、是否勾选、记录是否已不存在（AP-21）。

    `data` 为提交时查到的值（同一主键的第一行）；记录已不存在的行在详情中显示这些值。"""

    flow: str
    block: str
    seq: int
    target_table: str
    key: str | None
    missing: bool
    triggers: list[int]
    checked: bool
    data: dict[str, Value]


ActionKind = Literal["pass", "reject", "withdraw"]


@dataclass
class ProcessRecord:
    """一条处理记录：处理人、时间、通过/驳回/撤回、勾选、参数、意见（AP-11、AP-20）。"""

    seq: int
    level: int
    user_id: str
    user_name: str
    action: ActionKind
    at: datetime
    comment: str | None
    checked: list[dict[str, str]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


PendingStatus = Literal["pending", "applied", "void"]


@dataclass
class ApprovalRecord:
    approval_id: str
    page: str
    page_title: str
    operation: str
    operation_label: str
    source: DocumentRef
    source_label: str | None
    applicant_id: str
    applicant_name: str
    applicant_department: str | None
    submitted_at: datetime
    flows: list[FlowSnapshot]
    triggers: list[TriggerRow]
    patch: DocumentPatch
    """待审修改：本命令对这张单据的全部修改（AP-01）。"""
    key_map: dict[str, str]
    """新增行的临时编号 -> 提交时取得的主键（AP-02）。"""
    progress: Progress
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    """各级填写的人工参数：键为级别文本，最终批准时填写的为 `final`（AP-20）。"""
    pending_status: PendingStatus = "pending"
    result: list[dict[str, Any]] = field(default_factory=list)
    """执行结果：最终批准时每一步写入或跳过（AP-21 的"记录已不存在"）。"""
    finished_at: datetime | None = None

    @property
    def status(self) -> str:
        return self.progress.status

    @property
    def level(self) -> int:
        return self.progress.level

    def flow(self, code: str) -> FlowSnapshot:
        return next(f for f in self.flows if f.code == code)

    def triggers_of(self, flow: str) -> list[TriggerRow]:
        return [r for r in self.triggers if flow in r.flows]


# ---------------------------------------------------------------- JSON 编码

def encode_value(value: Value) -> Any:
    """后端内部的值转成可以放进 JSON 的值；Decimal、日期、日期时间加标记，读回时类型不变。"""
    if isinstance(value, Decimal):
        return {"$d": format_decimal(value)}
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    return value


def decode_value(value: Any) -> Value:
    if isinstance(value, dict):
        if "$d" in value:
            return Decimal(value["$d"])
        if "$dt" in value:
            return datetime.fromisoformat(value["$dt"])
        if "$date" in value:
            return date.fromisoformat(value["$date"])
    return value  # type: ignore[no-any-return]


def encode_values(values: dict[str, Value]) -> dict[str, Any]:
    return {k: encode_value(v) for k, v in values.items()}


def decode_values(values: dict[str, Any]) -> dict[str, Value]:
    return {k: decode_value(v) for k, v in values.items()}


def _time(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse_time(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def encode_progress(progress: Progress) -> dict[str, Any]:
    return {
        "status": progress.status, "level": progress.level, "flows": list(progress.flows), "ended": dict(progress.ended),
        "nodes": [{"flow": n.flow, "level": n.level, "index": n.index, "name": n.name, "mode": n.mode, "status": n.status,
                   "members": [{"kind": m.kind, "id": m.id, "name": m.name, "status": m.status, "processedBy": m.processed_by,
                                "processedByName": m.processed_by_name, "processedAt": _time(m.processed_at),
                                "comment": m.comment} for m in n.members]} for n in progress.nodes],
    }


def decode_progress(data: dict[str, Any]) -> Progress:
    nodes = [Node(flow=n["flow"], level=n["level"], index=n["index"], name=n["name"], mode=n["mode"], status=n["status"],
                  members=[Member(kind=m["kind"], id=m["id"], name=m["name"], status=m["status"], processed_by=m["processedBy"],
                                  processed_by_name=m["processedByName"], processed_at=_parse_time(m["processedAt"]),
                                  comment=m["comment"]) for m in n["members"]]) for n in data["nodes"]]
    return Progress(status=data["status"], level=data["level"], flows=list(data["flows"]), nodes=nodes,
                    ended={k: int(v) for k, v in data["ended"].items()})
