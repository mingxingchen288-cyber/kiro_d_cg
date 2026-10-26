"""命令信封与命令结果：写入管道唯一入口的输入输出。

适用哪些规则和审批条件由 operation（操作）决定；entry 只记录从哪里发起，用于审计，
不改变规则（换入口不会让规则消失）。
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, StrictBool

from .common import Code, Contract, FrozenMapping, Identifier, Parameters, canonical_json
from .patch import Patch


class EntryKind(StrEnum):
    PAGE = "page"
    """页面上的保存或按钮。"""
    IMPORT = "import"
    API = "api"
    APPROVAL = "approval"
    """审批批准后的动作。"""
    OPERATION = "operation"
    """另一个操作内部调用。"""


class CommandEntry(Contract):
    kind: EntryKind = EntryKind.PAGE
    page_code: Code | None = None
    button_code: Code | None = None


class SelectionRef(Contract):
    """操作针对的选中行（例如批量更新、审批勾选）。"""

    entity: Code
    row_key: Identifier


class CommandEnvelope(Contract):
    contract_version: Literal["1"] = "1"
    request_key: UUID = Field(description="客户端为每次提交生成一个新键，用于判重和查询本次提交的结果")
    operation: Code = Field(description="操作编码，决定适用的规则与审批条件")
    record_key: Identifier | None = Field(default=None, description="目标单据主键；为空表示新建")
    patch: Patch = Field(default_factory=Patch)
    parameters: Parameters = Field(default_factory=dict)
    selections: tuple[SelectionRef, ...] = ()
    entry: CommandEntry = Field(default_factory=CommandEntry)
    client_config_version: Identifier | None = Field(
        default=None, description="客户端当前看到的配置版本，仅用于提示；服务端以自己的快照为准"
    )

    def digest(self) -> str:
        """内容摘要：同一请求键的重试必须摘要相同，否则视为键被复用。"""
        return command_digest(self)


def command_digest(envelope: CommandEnvelope) -> str:
    body = {
        "operation": envelope.operation,
        "recordKey": envelope.record_key,
        "patch": envelope.patch.model_dump(mode="json"),
        "parameters": envelope.parameters,
        "selections": [item.model_dump(mode="json") for item in envelope.selections],
        "entry": envelope.entry.model_dump(mode="json"),
    }
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


class CommandStatus(StrEnum):
    APPLIED = "applied"
    """已写入业务表。"""
    PENDING_APPROVAL = "pending_approval"
    """已送审：修改保存为待审修改，相关数据已冻结。"""


class MessageLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class RuleMessage(Contract):
    level: MessageLevel
    text: str
    code: Code | None = None
    entity: Code | None = None
    row_key: Identifier | None = None
    client_row_id: Identifier | None = None
    field: Code | None = None


class RowImage(Contract):
    """写入后的行：本次写入以及计算带出的行的最新值，供前端逐行比对、局部刷新。"""

    entity: Code
    row_key: Identifier
    client_row_id: Identifier | None = None
    values: FrozenMapping[str, JsonValue] = Field(default_factory=dict)
    deleted: StrictBool = False


class RefreshScope(StrEnum):
    ROWS = "rows"
    """rows 中已给出全部受影响的行。"""
    CURRENT_PAGE = "current_page"
    """影响范围未知，前端需重查当前页或当前数据块（不重建表格）。"""


class CommandResult(Contract):
    contract_version: Literal["1"] = "1"
    request_key: UUID
    operation: Code
    status: CommandStatus
    record_key: Identifier | None = None
    rows: tuple[RowImage, ...] = ()
    id_map: FrozenMapping[str, str] = Field(default_factory=dict, description="新增行的临时编号 → 正式主键")
    refresh: RefreshScope = RefreshScope.ROWS
    messages: tuple[RuleMessage, ...] = ()
    approval_id: Identifier | None = None
    audit_id: Identifier | None = None
    config_version: Identifier
    replayed: StrictBool = Field(default=False, description="true 表示这是同一请求键先前已完成的结果")
