"""契约类型：C02–C10 中跨模块使用的数据结构。

- 进出 JSON 的结构（C02、C03、C05、C06、C07、C09、C10）用 pydantic 模型：Python 中字段名为
  snake_case，JSON 中为 camelCase（C01 第 1 节）；不允许出现未定义的字段；模型创建后不可修改。
- 后端模块之间传递的结构（C04、C08）用 dataclass。
- 端口协议在 ports.py。

按契约编号分节，每节开头注明对应的文档。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    JsonValue,
    SecretStr,
    StrictBool,
    StrictStr,
    StringConstraints,
    Tag,
    TypeAdapter,
    model_validator,
)
from pydantic.alias_generators import to_camel

if TYPE_CHECKING:
    from .ports import ConfigSnapshot


# ============================================================ 基础（C01）

class Wire(BaseModel):
    """进出 JSON 的模型的基类。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="forbid",
        frozen=True,
    )


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

Uuid = Annotated[str, StringConstraints(pattern=rf"^{_UUID}$")]
"""小写 UUID：requestKey、eventId、deliveryId（C01 第 5 节）。"""

RequestKey = Uuid
ClientRowId = Annotated[str, StringConstraints(pattern=rf"^tmp-{_UUID}$")]
"""前端为新增行生成的临时编号：`tmp-` 加小写 UUID。"""

DecimalText = Annotated[str, StringConstraints(pattern=r"^-?[0-9]+(\.[0-9]+)?$")]
"""十进制文本（C01 第 2 节）。解析、格式化和一致判定见 decimal_text（T-CT-2）。"""

IdText = Annotated[str, StringConstraints(pattern=r"^[0-9]+$")]
"""十进制整数文本：approvalId、userId。"""

Key = Annotated[str, StringConstraints(min_length=1)]
"""rowKey、recordKey：主键列的值转成的文本。"""

Code = Annotated[str, StringConstraints(min_length=1)]
"""配置中的编码：实体、页面、操作、审批流、规则、角色等。"""

Fingerprint = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]

BusinessValue: TypeAlias = StrictStr | StrictBool | None
"""业务字段在 JSON 中的值：精确数值和文本都是字符串（C01），是非为布尔，空为 null。"""

FieldValues: TypeAlias = dict[str, BusinessValue]

Value: TypeAlias = str | Decimal | bool | date | datetime | None
"""业务字段在后端内部的值（C08 第 1 节）：精确数值为 Decimal。"""

_adapters: dict[int, tuple[Any, TypeAdapter[Any]]] = {}


def adapter(tp: Any) -> TypeAdapter[Any]:
    """返回某个模型或联合类型的 TypeAdapter，同一类型只创建一次。"""
    found = _adapters.get(id(tp))
    if found is None or found[0] is not tp:
        found = (tp, TypeAdapter(tp))
        _adapters[id(tp)] = found
    return found[1]


class RowOp(StrEnum):
    """行操作，对应命令中各行的 `op` 和审批流 `trigger.operations`。"""

    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"


FieldType = Literal["text", "number", "date", "datetime", "boolean"]
ColumnSource = Literal["erp", "own"]
FieldRole = Literal["input", "calculated", "system"]
Pinned = Literal["left", "right"]
PageLayout = Literal["single", "masterDetail"]
DetailMode = Literal["tabs", "stack"]


class RecordRef(Wire):
    """一张单据：主表实体和主单主键。"""

    entity: Code
    record_key: Key


# ============================================================ C03 错误

class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    SESSION_REQUIRED = "SESSION_REQUIRED"
    SESSION_ROLE_REVOKED = "SESSION_ROLE_REVOKED"
    LOGIN_FAILED = "LOGIN_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CSRF_FAILED = "CSRF_FAILED"
    ORIGIN_REJECTED = "ORIGIN_REJECTED"
    ROLE_SELECTION_REQUIRED = "ROLE_SELECTION_REQUIRED"
    NOT_FOUND = "NOT_FOUND"
    DOCUMENT_BUSY = "DOCUMENT_BUSY"
    REQUEST_IN_PROGRESS = "REQUEST_IN_PROGRESS"
    FROZEN_BY_APPROVAL = "FROZEN_BY_APPROVAL"
    RECONFIRM_REQUIRED = "RECONFIRM_REQUIRED"
    ROW_NOT_FOUND = "ROW_NOT_FOUND"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    RULE_REJECTED = "RULE_REJECTED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    FIELD_NOT_WRITABLE = "FIELD_NOT_WRITABLE"
    CONFIG_UNAVAILABLE = "CONFIG_UNAVAILABLE"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    @property
    def http_status(self) -> int:
        """C03 第 2 节：每个错误码只对应一个 HTTP 状态。"""
        return _HTTP_STATUS[self]


_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.SESSION_REQUIRED: 401,
    ErrorCode.SESSION_ROLE_REVOKED: 401,
    ErrorCode.LOGIN_FAILED: 401,
    ErrorCode.PERMISSION_DENIED: 403,
    ErrorCode.CSRF_FAILED: 403,
    ErrorCode.ORIGIN_REJECTED: 403,
    ErrorCode.ROLE_SELECTION_REQUIRED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.DOCUMENT_BUSY: 409,
    ErrorCode.REQUEST_IN_PROGRESS: 409,
    ErrorCode.FROZEN_BY_APPROVAL: 409,
    ErrorCode.RECONFIRM_REQUIRED: 409,
    ErrorCode.ROW_NOT_FOUND: 409,
    ErrorCode.APPROVAL_REQUIRED: 409,
    ErrorCode.IDEMPOTENCY_KEY_REUSED: 422,
    ErrorCode.RULE_REJECTED: 422,
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.FIELD_NOT_WRITABLE: 422,
    ErrorCode.CONFIG_UNAVAILABLE: 503,
    ErrorCode.DATABASE_UNAVAILABLE: 503,
    ErrorCode.INTERNAL_ERROR: 500,
}


class ErrorDetail(Wire):
    """定位到行和字段的错误明细；被冻结时 `approval_id` 指明冻结它的审批。"""

    message: str | None = None
    entity: Code | None = None
    row_key: Key | None = None
    client_row_id: ClientRowId | None = None
    field: str | None = None
    approval_id: IdText | None = None


class ErrorResponse(Wire):
    code: ErrorCode
    message: str
    details: list[ErrorDetail] = []


class PlatformError(Exception):
    """平台错误：各模块失败时抛出，由 assembly 按 C03 转成响应。"""

    def __init__(self, code: ErrorCode | str, message: str, details: Sequence[ErrorDetail] = ()) -> None:
        self.code = ErrorCode(code)
        self.message = message
        self.details = list(details)
        super().__init__(f"{self.code.value}: {message}")

    @property
    def http_status(self) -> int:
        return self.code.http_status

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(code=self.code, message=self.message, details=self.details)


# ============================================================ C02 命令与结果

class MasterAdd(Wire):
    op: Literal["add"]
    client_row_id: ClientRowId
    values: FieldValues


class MasterModify(Wire):
    op: Literal["modify"]
    row_key: Key
    changes: FieldValues


class MasterDelete(Wire):
    """删除主表行，连同它的全部明细。"""

    op: Literal["delete"]
    row_key: Key


class MasterNone(Wire):
    """主表不改、只改明细。"""

    op: Literal["none"]
    row_key: Key


MasterChange = Annotated[MasterAdd | MasterModify | MasterDelete | MasterNone, Field(discriminator="op")]


class DetailAdd(Wire):
    entity: Code
    op: Literal["add"]
    client_row_id: ClientRowId
    values: FieldValues


class DetailModify(Wire):
    entity: Code
    op: Literal["modify"]
    row_key: Key
    changes: FieldValues


class DetailDelete(Wire):
    entity: Code
    op: Literal["delete"]
    row_key: Key


DetailChange = Annotated[DetailAdd | DetailModify | DetailDelete, Field(discriminator="op")]


class DocumentPatch(Wire):
    """一张单据的修改。"""

    entity: Code
    master: MasterChange
    details: list[DetailChange] = []

    @model_validator(mode="after")
    def _details_match_master(self) -> DocumentPatch:
        if self.master.op == "add" and any(d.op != "add" for d in self.details):
            raise ValueError("新增的单据只能新增明细")
        if self.master.op == "delete" and any(d.op != "delete" for d in self.details):
            raise ValueError("删除的单据不能新增或修改明细")
        return self


class Command(Wire):
    """命令：业务数据唯一的写入形式。"""

    request_key: RequestKey
    page: Code | None = None
    operation: Code
    documents: list[DocumentPatch] = []
    params: dict[str, JsonValue] = {}

    def content_digest(self) -> str:
        """去掉 requestKey 的命令体，按键名排序、去掉空白后取 SHA-256（十六进制小写），用于判重。"""
        body = self.model_dump(mode="json", by_alias=True, exclude={"request_key"})
        text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Outcome(StrEnum):
    SAVED = "saved"
    UNCHANGED = "unchanged"
    APPROVAL_SUBMITTED = "approvalSubmitted"
    APPROVAL_PROCESSED = "approvalProcessed"


class FrozenMark(Wire):
    """行所在单据被冻结时，冻结它的审批。"""

    approval_id: IdText


class ResultRow(Wire):
    """命令结果中的受影响行：未删除的行给出实体的全部字段；删除的行只有 `deleted`。"""

    entity: Code
    row_key: Key
    client_row_id: ClientRowId | None = None
    values: FieldValues | None = None
    frozen: FrozenMark | None = None
    deleted: bool = False

    @model_validator(mode="after")
    def _shape(self) -> ResultRow:
        if self.deleted and (self.values is not None or self.frozen is not None):
            raise ValueError("删除的行不带 values 和 frozen")
        if not self.deleted and self.values is None:
            raise ValueError("未删除的行必须给出 values")
        return self


class Prompt(Wire):
    """规则提示。"""

    rule: Code
    message: str
    entity: Code | None = None
    row_key: Key | None = None
    field: str | None = None


class SkippedRow(Wire):
    """因行已被删除而跳过的修改。"""

    entity: Code
    row_key: Key
    reason: Literal["ROW_NOT_FOUND"]


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ApprovalRef(Wire):
    """本命令提交或处理的审批。"""

    approval_id: IdText
    document: RecordRef
    status: ApprovalStatus
    level: int = Field(ge=1)
    flows: list[Code]


ApprovalState = ApprovalRef
"""C08 CommandState.approvals 的元素，与命令结果中的 `approvals` 相同。"""


class CommandResult(Wire):
    request_key: RequestKey
    outcome: Outcome
    rows: list[ResultRow] = []
    id_map: dict[ClientRowId, Key] = {}
    prompts: list[Prompt] = []
    skipped: list[SkippedRow] = []
    approvals: list[ApprovalRef] = []


# ============================================================ C04 执行上下文

@dataclass(frozen=True)
class Identity:
    user_id: str
    username: str
    display_name: str
    department_id: str | None
    role_code: str
    session_id: str = dc_field(repr=False)


@dataclass(frozen=True)
class Origin:
    kind: Literal["user", "approval"]
    approval_id: str | None = None

    def __post_init__(self) -> None:
        if (self.kind == "approval") != (self.approval_id is not None):
            raise ValueError("来源为审批时必须给出 approval_id，否则不能给出")


@dataclass(frozen=True)
class ExecutionContext:
    request_id: str
    identity: Identity
    config: ConfigSnapshot
    config_version: int
    origin: Origin
    now: datetime


# ============================================================ C05 页面视图

class ViewLookup(Wire):
    code: Code
    fill: dict[str, str]


class ViewField(Wire):
    name: str
    label: str
    type: FieldType
    scale: int | None
    source: ColumnSource
    calculated: bool
    visible: bool
    editable: bool
    required: bool
    width: int | None
    pinned: Pinned | None
    dict_type: Code | None
    lookup: ViewLookup | None


class ViewButton(Wire):
    key: Code
    action: Code
    label: str
    operation: Code | None
    requires_selection: bool


class GridOptions(Wire):
    side_bar: bool
    cell_selection: bool
    group_by: list[str]


class FormCell(Wire):
    """表单布局的一格：24 列网格，`x` 从 0 起。"""

    field: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)

    @model_validator(mode="after")
    def _within_grid(self) -> FormCell:
        if self.x + self.w > 24:
            raise ValueError("表单布局越出 24 列")
        return self


class ErpRow(Wire):
    """实体的 ERP 行标识（C06 第 2 节）。"""

    column: str
    value: str
    local_value: str


class ViewMaster(Wire):
    entity: Code
    primary_key: str
    fields: list[ViewField]
    buttons: list[ViewButton]
    grid: GridOptions
    form_layout: list[FormCell]
    erp_row: ErpRow | None = None


class ViewDetail(Wire):
    entity: Code
    title: str
    primary_key: str
    parent_key: str
    fields: list[ViewField]
    buttons: list[ViewButton]
    grid: GridOptions
    form_layout: list[FormCell]
    erp_row: ErpRow | None = None


class PackRef(Wire):
    pack_id: Code
    version: int


SystemButton = Literal["save", "addRow", "deleteRow", "advancedSearch"]


class PageView(Wire):
    page_code: Code
    title: str
    version: int
    layout: PageLayout
    detail_mode: DetailMode
    audit: bool
    save_operation: Code | None
    rules_pack: PackRef | None
    master: ViewMaster
    details: list[ViewDetail]
    system_buttons: list[SystemButton]

    @model_validator(mode="after")
    def _single_has_no_details(self) -> PageView:
        if self.layout == "single" and self.details:
            raise ValueError("单表页没有明细")
        return self


# ============================================================ C06 配置模型

CompareOp = Literal["eq", "ne", "gt", "ge", "lt", "le", "like", "in", "isNull", "isNotNull"]
Logic = Literal["AND", "OR"]


class RuleConditionItem(Wire):
    source: Literal["row", "master"]
    field: str
    op: CompareOp
    value: JsonValue = None


class VisualCondition(Wire):
    """可视化条件（C06 第 5 节）。"""

    logic: Logic
    conditions: list[RuleConditionItem]


Condition: TypeAlias = str | VisualCondition
"""条件：表达式文本，或可视化条件。"""


class DataItem(Wire):
    """规则或审批条件需要的数据库数据，表达式中写作 `data.名称`。"""

    name: str
    sql: str
    binds: dict[str, str] = {}


# ---- 2. entity

class StaticDefault(Wire):
    type: Literal["static"]
    value: str


class BuiltinDefault(Wire):
    type: Literal["builtin"]
    value: Literal["currentUserId", "currentUserName", "currentDeptId", "currentDeptName", "currentRoleCode", "currentTime"]


class OptionsDefault(Wire):
    type: Literal["options"]
    value: list[str] = Field(min_length=1)


DefaultValue = Annotated[StaticDefault | BuiltinDefault | OptionsDefault, Field(discriminator="type")]

CompareFormat = Literal["value", "percent", "both"]


class FieldCompare(Wire):
    mode: Literal["field"]
    field: str
    format: CompareFormat


class CompareKey(Wire):
    current: str
    compare: str


class QueryCompare(Wire):
    mode: Literal["query"]
    source: str
    keys: list[CompareKey] = Field(min_length=1)
    field: str
    format: CompareFormat


FieldCompareConfig = Annotated[FieldCompare | QueryCompare, Field(discriminator="mode")]


class EntityField(Wire):
    name: str
    column: str | None
    label: str
    type: FieldType
    scale: int | None = None
    source: ColumnSource
    role: FieldRole
    default: DefaultValue | None = None
    compare: FieldCompareConfig | None = None


class DetailLink(Wire):
    entity: Code
    parent_key: str


class FieldFlags(Wire):
    visible: bool | None = None
    editable: bool | None = None
    required: bool | None = None


class RequiredConditionItem(Wire):
    field: str
    op: Literal["eq", "ne", "isNull", "isNotNull"]
    value: str | None = None


class RequiredCondition(Wire):
    logic: Logic
    conditions: list[RequiredConditionItem]


class ApprovalRequiredRule(Wire):
    fields: list[str] = Field(min_length=1)
    when: RequiredCondition | None = None
    source_pages: list[Code]


class EntityConfig(Wire):
    table: str
    primary_key: str
    freezable: bool
    read_view: str | None = None
    erp_row: ErpRow | None = None
    fields: list[EntityField]
    details: list[DetailLink] = []
    field_defaults: dict[str, FieldFlags] = {}
    approval_required: list[ApprovalRequiredRule] = []


# ---- 3. page

class LookupFilter(Wire):
    column: str
    from_: Literal["row", "cell"] = Field(alias="from")
    field: str | None = None


class LookupSetting(Wire):
    code: Code
    fill: dict[str, str]
    multiple: bool = False
    filter: LookupFilter | None = None
    fill_back: bool = True


class FieldSetting(Wire):
    visible: bool | None = None
    editable: bool | None = None
    required: bool | None = None
    width: int | None = None
    pinned: Pinned | None = None
    dict_type: Code | None = None
    lookup: LookupSetting | None = None


class ButtonConfig(Wire):
    action: Code
    label: str
    operation: Code | None = None
    requires_selection: bool = False


class PageMasterConfig(Wire):
    entity: Code
    fields: dict[str, FieldSetting] = {}
    buttons: list[ButtonConfig] = []
    grid: GridOptions
    form_layout: list[FormCell] = []


class PageDetailConfig(Wire):
    entity: Code
    title: str
    fields: dict[str, FieldSetting] = {}
    buttons: list[ButtonConfig] = []
    grid: GridOptions
    form_layout: list[FormCell] = []


class PageConfig(Wire):
    title: str
    layout: PageLayout
    detail_mode: DetailMode = "tabs"
    audit: bool = False
    save_operation: Code | None
    master: PageMasterConfig
    details: list[PageDetailConfig] = []

    @model_validator(mode="after")
    def _single_has_no_details(self) -> PageConfig:
        if self.layout == "single" and self.details:
            raise ValueError("单表页没有明细")
        return self


# ---- 7.2 查找目标（通用动作 updateRecords 也使用）

class RelationKeyFinder(Wire):
    kind: Literal["relationKey"]
    entity: Code
    target_key: str
    source_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")]
    rows: Literal["changed", "all"]


class SqlFinder(Wire):
    kind: Literal["sql"]
    entity: Code
    sql: str
    binds: dict[str, str] = {}
    record_key_column: str
    row_key_columns: list[str] = []
    label_column: str | None = None
    display_columns: list[str] = []


TargetFinder = Annotated[RelationKeyFinder | SqlFinder, Field(discriminator="kind")]
TargetFinderConfig = TargetFinder


# ---- 6. 通用动作

class FieldMap(Wire):
    from_: str = Field(alias="from")
    to: str


class ApplyPendingChanges(Wire):
    action: Literal["applyPendingChanges"]


class Recalculate(Wire):
    action: Literal["recalculate"]
    target: Literal["source", "targets"]


class TargetUpdate(Wire):
    entity: Code
    detail_entity: Code | None = None
    match: dict[str, str] = {}
    field_mapping: list[FieldMap] = Field(min_length=1)


class UpdateTargets(Wire):
    action: Literal["updateTargets"]
    targets: list[TargetUpdate] = Field(min_length=1)


class UpdateRecords(Wire):
    action: Literal["updateRecords"]
    find: TargetFinder
    field_mapping: list[FieldMap] = Field(min_length=1)


class EscapeHatch(Wire):
    action: Literal["escapeHatch"]
    operation: Code


ActionStep = Annotated[
    ApplyPendingChanges | Recalculate | UpdateTargets | UpdateRecords | EscapeHatch,
    Field(discriminator="action"),
]


# ---- 4. operation

class OperationConfig(Wire):
    label: str
    kind: Literal["save", "action", "escapeHatch"]
    writable_fields: dict[str, list[str]] = {}
    impact: list[Code] = []
    actions: list[ActionStep] = []
    row_not_found: Literal["skip", "reject"] = "skip"
    propagation: Literal["continue", "end"] = "continue"
    procedure: str | None = None
    writes: dict[str, list[str]] = {}


# ---- 5. rule

class Branch(Wire):
    when: Condition | None = None
    expression: str


class UiEffect(Wire):
    editable: bool | None = None
    required: bool | None = None
    row_style: JsonValue = None
    cell_style: JsonValue = None


class RuleConfig(Wire):
    layer: Literal["entity", "operation", "page"]
    target: Code
    category: Literal["calc", "validate", "ui"]
    field: str | None = None
    order: int = 0
    data_items: list[DataItem] = []
    when: Condition | None = None
    expression: str | None = None
    branches: list[Branch] | None = None
    level: Literal["reject", "prompt"] | None = None
    message: str | None = None
    effect: UiEffect | None = None

    @model_validator(mode="after")
    def _category_shape(self) -> RuleConfig:
        if self.layer == "page" and self.category != "ui":
            raise ValueError("页面规则只能是界面规则")
        if self.category == "calc":
            if not self.field:
                raise ValueError("计算规则必须指定字段")
            if (self.expression is None) == (self.branches is None):
                raise ValueError("计算规则只能有 expression 或 branches 之一")
        if self.category == "validate" and (self.level is None or not self.message):
            raise ValueError("校验规则必须给出 level 和 message")
        if self.category == "ui" and self.effect is None:
            raise ValueError("界面规则必须给出 effect")
        return self


# ---- 7. approvalFlow

class Trigger(Wire):
    operations: list[RowOp] = Field(default=[RowOp.MODIFY], min_length=1)
    changed_fields: dict[str, list[str]] = {}
    when: Condition | None = None
    data_items: list[DataItem] = []


class UserApprover(Wire):
    type: Literal["user"]
    user_id: IdText


class RoleApprover(Wire):
    type: Literal["role"]
    role: Code


class SqlApprover(Wire):
    type: Literal["sql"]
    sql: str
    binds: dict[str, str] = {}


Approver = Annotated[UserApprover | RoleApprover | SqlApprover, Field(discriminator="type")]


class LevelEntry(Wire):
    name: str
    when: Condition | None = None
    mode: Literal["or", "and"]
    approvers: list[Approver] = Field(min_length=1)


class FlowLevel(Wire):
    level: int = Field(ge=1)
    entries: list[LevelEntry] = Field(min_length=1)


class FlowTargets(Wire):
    find: list[TargetFinder] = Field(min_length=1)
    selection: Literal["all", "approverSelects"]


class FreezeTargets(Wire):
    """冻结全部候选对象所在的单据（C06 7.3）。"""

    kind: Literal["targets"]


FreezeSpec = Annotated[FreezeTargets | RelationKeyFinder | SqlFinder, Field(discriminator="kind")]
"""来源单据之外还要冻结的单据：全部候选对象，或按来源的字段关联其他表找到的单据。"""

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


class DisplayColumn(Wire):
    label: str
    field: Annotated[str, StringConstraints(pattern=rf"^(source|target)(\.{_IDENT}){{1,2}}$")]


class DisplayMaster(Wire):
    columns: list[DisplayColumn] = []


class DisplayDetail(Wire):
    title: str
    rows: Annotated[str, StringConstraints(pattern=rf"^(source\.{_IDENT}|target(\.{_IDENT})?)$")]
    rows_filter: Literal["changed", "all"] = "changed"
    columns: list[DisplayColumn] = []

    @model_validator(mode="after")
    def _fields_match_rows(self) -> DisplayDetail:
        side = self.rows.split(".", 1)[0]
        if any(not c.field.startswith(side + ".") for c in self.columns):
            raise ValueError(f"rows 为 {self.rows} 的从表只能取 {side} 的字段")
        return self


class ApprovalDisplay(Wire):
    """审批详情"修改内容"的主表和从表（C06 7.6）。"""

    master: DisplayMaster
    details: list[DisplayDetail] = []


class LevelActions(Wire):
    level: int = Field(ge=1)
    steps: list[ActionStep] = Field(min_length=1)


class FlowParam(Wire):
    name: str
    label: str
    type: Literal["string", "number", "boolean", "date"]
    source: Literal["manual", "constant", "expression"]
    required: bool = False
    level: int | None = Field(default=None, ge=1)
    value: JsonValue = None


class NotifyUsers(Wire):
    users: list[IdText] = Field(min_length=1)


class NotifyRole(Wire):
    role: Code


class NotifyRule(Wire):
    event: Literal["submitted", "levelEntered", "passed", "rejected", "withdrawn"]
    to: Literal["levelApprovers", "applicant"] | NotifyUsers | NotifyRole


class ApprovalFlowConfig(Wire):
    created_seq: int = Field(ge=1)
    source_operation: Code
    trigger: Trigger
    levels: list[FlowLevel] = Field(min_length=1)
    targets: FlowTargets | None = None
    display: ApprovalDisplay | None = None
    freeze: list[FreezeSpec] = []
    after_approval: list[ActionStep] = []
    level_actions: list[LevelActions] = []
    params: list[FlowParam] = []
    propagation: Literal["end"] = "end"
    notify: list[NotifyRule] = []

    @model_validator(mode="after")
    def _structure(self) -> ApprovalFlowConfig:
        if [lv.level for lv in self.levels] != list(range(1, len(self.levels) + 1)):
            raise ValueError("审批流的级别必须从 1 开始连续")
        if self.targets is None and any(f.kind == "targets" for f in self.freeze):
            raise ValueError("没有配置 targets.find 的审批流不能冻结候选对象")
        return self


# ---- 8. role

class RowConditionItem(Wire):
    field: str
    field_label: str
    op: CompareOp
    value_type: Literal["static", "dynamic"]
    value: JsonValue = None


class VisualRowPolicy(Wire):
    mode: Literal["visual"]
    logic: Logic
    conditions: list[RowConditionItem]
    sql: str


class RolePage(Wire):
    buttons: list[str] = []
    rows: VisualRowPolicy | str | None = None
    columns: dict[str, dict[str, FieldFlags]] = {}


class RoleConfig(Wire):
    name: str
    admin: bool = False
    pages: dict[Code, RolePage] = {}


# ---- 9. menu、dict、lookup、export

class MenuItem(Wire):
    key: Code
    title: str
    kind: Literal["group", "page", "config", "admin"]
    page_code: Code | None = None
    children: list[MenuItem] = []

    @model_validator(mode="after")
    def _page_has_code(self) -> MenuItem:
        if self.kind == "page" and not self.page_code:
            raise ValueError("页面菜单必须给出 pageCode")
        return self


class MenuConfig(Wire):
    items: list[MenuItem]


class DictEntry(Wire):
    value: str
    label: str
    order: int = 0


class DictConfig(Wire):
    items: list[DictEntry]


class LookupConfig(Wire):
    table: str
    columns: list[str] = Field(min_length=1)
    keyword_columns: list[str] = []
    order_by: str | None = None


class ExportColumn(Wire):
    field: str
    header: str


class ExportMaster(Wire):
    sheet: str
    sql: str
    key_column: str
    columns: list[ExportColumn] = Field(min_length=1)


class ExportDetail(Wire):
    sheet: str
    sql: str
    link_column: str
    columns: list[ExportColumn] = Field(min_length=1)


class ExportConfig(Wire):
    page: Code
    name: str
    file_name: str
    font: str = "Calibri"
    detail_layout: Literal["perMaster", "perDetail"] = "perMaster"
    master: ExportMaster
    details: list[ExportDetail] = []


# ---- 1. 配置项

ConfigType = Literal["entity", "page", "operation", "rule", "approvalFlow", "role", "menu", "dict", "lookup", "export"]

CONFIG_CONTENT: dict[str, type[Wire]] = {
    "entity": EntityConfig,
    "page": PageConfig,
    "operation": OperationConfig,
    "rule": RuleConfig,
    "approvalFlow": ApprovalFlowConfig,
    "role": RoleConfig,
    "menu": MenuConfig,
    "dict": DictConfig,
    "lookup": LookupConfig,
    "export": ExportConfig,
}
"""各类配置项 `content` 的模型。"""


class ConfigDraft(Wire):
    """要保存或校验的配置项：还没有版本号。"""

    type: ConfigType
    key: Code
    name: str
    content: dict[str, JsonValue]

    def parsed_content(self) -> Wire:
        """按 `type` 解析 `content`；不符合 C06 时抛 pydantic.ValidationError。"""
        return CONFIG_CONTENT[self.type].model_validate(self.content)


class ConfigItemSummary(Wire):
    type: ConfigType
    key: Code
    name: str
    version: int = Field(ge=1)
    updated_by: IdText
    updated_at: datetime


class ConfigItem(ConfigItemSummary):
    content: dict[str, JsonValue]

    def parsed_content(self) -> Wire:
        """按 `type` 解析 `content`；不符合 C06 时抛 pydantic.ValidationError。"""
        return CONFIG_CONTENT[self.type].model_validate(self.content)


# ============================================================ C07 规则内核接口

class PackField(Wire):
    type: FieldType
    scale: int | None = None
    role: FieldRole
    source: ColumnSource


class PackRule(Wire):
    id: Code
    layer: Literal["entity", "operation", "page"]
    entity: Code | None = None
    operation: Code | None = None
    page: Code | None = None
    category: Literal["calc", "validate", "approvalTrigger", "ui"]
    flow: Code | None = None
    order: int
    server_only: bool
    jdm: Code

    @model_validator(mode="after")
    def _target_matches_layer(self) -> PackRule:
        if getattr(self, self.layer) is None:
            raise ValueError(f"{self.layer} 层的规则必须给出 {self.layer}")
        if (self.category == "approvalTrigger") != (self.flow is not None):
            raise ValueError("只有审批条件规则带 flow，且必须带")
        return self


class PackApprovalEntry(Wire):
    flow: Code
    level: int = Field(ge=1)
    entry: str
    jdm: Code


class JdmGraph(Wire):
    """ZEN 的 JDM；允许的节点种类由 rules-core 在 load_pack 时检查。"""

    nodes: list[dict[str, JsonValue]]
    edges: list[dict[str, JsonValue]]


class RulesPack(Wire):
    pack_id: Code
    version: int
    core_version: str
    fields: dict[str, dict[str, PackField]]
    rules: list[PackRule]
    approval_entries: list[PackApprovalEntry] = []
    jdm: dict[str, JdmGraph]


class EvalContext(Wire):
    user_id: IdText
    department_id: Key | None
    role: Code
    today: date
    origin: Literal["user", "approval"]


class EvalRow(Wire):
    """求值请求中的一行：已保存的行用 rowKey，新增行用 clientRowId；`old` 只列出改过的字段的旧值。"""

    row_key: Key | None = None
    client_row_id: ClientRowId | None = None
    values: FieldValues
    old: FieldValues | None = None

    @model_validator(mode="after")
    def _one_identity(self) -> EvalRow:
        if (self.row_key is None) == (self.client_row_id is None):
            raise ValueError("rowKey 和 clientRowId 必须且只能给出一个")
        if self.client_row_id is not None and self.old is not None:
            raise ValueError("新增行没有 old")
        return self


class EvalDocument(Wire):
    entity: Code
    master: EvalRow
    details: dict[str, list[EvalRow]] = {}


class ChangedRow(Wire):
    entity: Code
    row_key: Key | None = None
    client_row_id: ClientRowId | None = None
    op: RowOp
    fields: list[str] = []

    @model_validator(mode="after")
    def _one_identity(self) -> ChangedRow:
        if (self.row_key is None) == (self.client_row_id is None):
            raise ValueError("rowKey 和 clientRowId 必须且只能给出一个")
        return self


class EvaluationRequest(Wire):
    purpose: Literal["operation", "approvalEntry"]
    operation: Code | None = None
    page: Code | None = None
    phase: Literal["preview", "commit"]
    flow: Code | None = None
    level: int | None = Field(default=None, ge=1)
    context: EvalContext
    document: EvalDocument
    changed: list[ChangedRow] = []
    data: dict[str, JsonValue] = {}

    @model_validator(mode="after")
    def _entry_has_flow(self) -> EvaluationRequest:
        if self.purpose == "approvalEntry" and (self.flow is None or self.level is None):
            raise ValueError("判断审批入口时必须给出 flow 和 level")
        return self


class FieldState(Wire):
    editable: bool | None = None
    required: bool | None = None


class RowStyle(Wire):
    row: JsonValue = None
    cells: dict[str, JsonValue] = {}


class EvalRowResult(Wire):
    entity: Code
    row_key: Key
    computed: FieldValues = {}
    fields: dict[str, FieldState] = {}
    style: RowStyle | None = None


class PromptEffect(Wire):
    kind: Literal["prompt"]
    rule: Code
    message: str
    entity: Code | None = None
    row_key: Key | None = None
    field: str | None = None


class RejectEffect(Wire):
    kind: Literal["reject"]
    rule: Code
    message: str
    entity: Code | None = None
    row_key: Key | None = None
    field: str | None = None


class ApproveEffect(Wire):
    kind: Literal["approve"]
    rule: Code
    flow: Code


RuleEffect = Annotated[PromptEffect | RejectEffect | ApproveEffect, Field(discriminator="kind")]


class EvalError(Wire):
    code: Literal["PACK_INVALID", "INPUT_INVALID", "EVAL_FAILED"]
    message: str


class EvaluationResult(Wire):
    ok: bool
    rows: list[EvalRowResult] = []
    effects: list[RuleEffect] = []
    satisfied: bool | None = None
    error: EvalError | None = None

    @model_validator(mode="after")
    def _ok_or_error(self) -> EvaluationResult:
        if self.ok and self.error is not None:
            raise ValueError("成功的结果不带 error")
        if not self.ok and (self.error is None or self.rows or self.effects or self.satisfied is not None):
            raise ValueError("失败的结果只带 error，不返回部分结果")
        return self


# ============================================================ C09 HTTP 接口

# ---- 1. 共用类型

class CurrentUser(Wire):
    user_id: IdText
    username: str
    display_name: str
    department_id: Key | None


class RoleRef(Wire):
    code: Code
    name: str
    admin: bool


class CompareResult(Wire):
    value: DecimalText | None
    diff: DecimalText | None
    percent: DecimalText | None


class DataRow(Wire):
    row_key: Key
    values: FieldValues
    frozen: FrozenMark | None
    compare: dict[str, CompareResult] | None = None


# ---- 2. identity

class LoginRequest(Wire):
    username: str = Field(min_length=1)
    password: SecretStr


class LoginResponse(Wire):
    user: CurrentUser
    roles: list[RoleRef]
    selected_role: RoleRef | None
    csrf_token: str


class SelectRoleRequest(Wire):
    role_code: Code


class SelectRoleResponse(Wire):
    selected_role: RoleRef


class MeResponse(Wire):
    user: CurrentUser
    role: RoleRef | None
    menus: list[MenuItem]
    config_version: int
    csrf_token: str


class Account(Wire):
    user_id: IdText
    username: str
    display_name: str
    department_id: Key | None
    enabled: bool
    role_codes: list[Code]


class AccountList(Wire):
    rows: list[Account]
    total: int = Field(ge=0)


class AccountCreate(Wire):
    username: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    department_id: Key | None
    password: SecretStr
    role_codes: list[Code] = []


class AccountUpdate(Wire):
    display_name: str = Field(min_length=1)
    department_id: Key | None
    role_codes: list[Code]
    enabled: bool


class PasswordChange(Wire):
    password: SecretStr


class Department(Wire):
    department_id: Key
    name: str
    parent_id: Key | None


class DepartmentList(Wire):
    items: list[Department]


# ---- 3. config

class ConfigItemList(Wire):
    items: list[ConfigItemSummary]


class ConfigSaveRequest(Wire):
    name: str = Field(min_length=1)
    content: dict[str, JsonValue]


class ConfigSaveResponse(Wire):
    type: ConfigType
    key: Code
    version: int = Field(ge=1)


class ConfigValidateRequest(Wire):
    items: list[ConfigDraft] = Field(min_length=1)


class ConfigValidateResponse(Wire):
    ok: bool
    errors: list[ErrorDetail] = []


class WizardColumnsRequest(Wire):
    read_view: str | None = None
    table: str = Field(min_length=1)


class WizardSequence(Wire):
    name: str
    exists: bool


class WizardColumn(Wire):
    name: str
    type: FieldType
    label: str
    in_table: bool


class WizardColumnsResponse(Wire):
    primary_key: str
    sequence: WizardSequence
    columns: list[WizardColumn]


class WizardGenerateRequest(Wire):
    """新建页面向导的生成请求；`master`、`details` 的内容由 config CF-14 校验。"""

    parent_menu: Code
    page_code: Code
    title: str = Field(min_length=1)
    layout: PageLayout
    master: dict[str, JsonValue]
    details: list[dict[str, JsonValue]] = []


# ---- 4. queries-export

class SortItem(Wire):
    col_id: str
    sort: Literal["asc", "desc"]


class AdvancedCondition(Wire):
    """高级查询条件：不写 `entity` 时属于主表；同一明细实体的条件由同一条明细行同时满足。"""

    entity: Code | None = None
    group: str | None = None
    logic: Literal["and", "or"] | None = None
    field: str
    operator: str
    value: JsonValue = None


class AdvancedQuery(Wire):
    op: Literal["and", "or"]
    conditions: list[AdvancedCondition]


class ListRequest(Wire):
    start_row: int = Field(ge=0)
    end_row: int = Field(ge=0)
    sort_model: list[SortItem] = []
    filter_model: dict[str, dict[str, JsonValue]] = {}
    advanced: AdvancedQuery | None = None

    @model_validator(mode="after")
    def _range(self) -> ListRequest:
        if self.end_row < self.start_row:
            raise ValueError("endRow 不能小于 startRow")
        return self


class ListResponse(Wire):
    rows: list[DataRow]
    total: int = Field(ge=0)
    aggregates: FieldValues = {}


class ByKeysRequest(Wire):
    entity: Code
    row_keys: list[Key]


class RowsResponse(Wire):
    rows: list[DataRow]


class RecordResponse(Wire):
    master: DataRow
    details: dict[str, list[DataRow]] = {}


class LookupSearchFilter(Wire):
    column: str
    value: str | None


class LookupSearchRequest(Wire):
    keyword: str = ""
    filter: LookupSearchFilter | None = None
    start_row: int = Field(default=0, ge=0)
    end_row: int = Field(default=50, ge=0)


class LookupRow(Wire):
    values: FieldValues


class LookupSearchResponse(Wire):
    rows: list[LookupRow]
    total: int = Field(ge=0)


class DictItem(Wire):
    value: str
    label: str


class DictResponse(Wire):
    items: list[DictItem]


class PersonalColumn(Wire):
    field: str
    width: int | None = None
    pinned: Pinned | None = None
    hide: bool = False


class PersonalGrid(Wire):
    columns: list[PersonalColumn] = []


class PersonalConfig(Wire):
    """个人列配置：`grids` 的键为 `master` 或明细实体；没有保存过时各项为空。"""

    grids: dict[str, PersonalGrid] = {}
    detail_mode: DetailMode | None = None


class ExportItem(Wire):
    export_code: Code
    name: str


class ExportList(Wire):
    items: list[ExportItem]


class PageExportRequest(Wire):
    mode: Literal["page"]
    request: ListRequest
    columns: list[str] = Field(min_length=1)


class ConfigExportRequest(Wire):
    mode: Literal["config"]
    export_code: Code
    scope: Literal["current", "all"]
    request: ListRequest


ExportRequest = Annotated[PageExportRequest | ConfigExportRequest, Field(discriminator="mode")]


# ---- 6. approval

class UserBrief(Wire):
    user_id: IdText
    display_name: str


class SourceRef(Wire):
    entity: Code
    record_key: Key
    label: str | None


class ApprovalSummary(Wire):
    approval_id: IdText
    page: Code
    page_title: str
    operation: Code
    operation_label: str
    source: SourceRef
    applicant: UserBrief
    submitted_at: datetime
    status: ApprovalStatus
    level: int = Field(ge=1)


class ApprovalList(Wire):
    rows: list[ApprovalSummary]
    total: int = Field(ge=0)


class StepMember(Wire):
    type: Literal["user", "role"]
    id: Key
    name: str
    status: Literal["pending", "passed", "rejected"]
    processed_by: UserBrief | None
    processed_at: datetime | None
    comment: str | None


class ApprovalStep(Wire):
    level: int = Field(ge=1)
    flow: Code
    flow_name: str
    entry: str
    mode: Literal["or", "and"]
    status: Literal["passed", "pending", "rejected", "upcoming"]
    members: list[StepMember]


class ViewCell(Wire):
    before: BusinessValue
    after: BusinessValue


class ViewRow(Wire):
    """"修改内容"的一行：来源单据的行带 `flows`，候选单据的行带 `target`。"""

    op: Literal["modify", "add", "delete", "none"]
    cells: list[ViewCell]
    target: RecordRef | None = None
    flows: list[Code] | None = None

    @model_validator(mode="after")
    def _op_shape(self) -> ViewRow:
        if self.op == "add" and any(c.before is not None for c in self.cells):
            raise ValueError("新增行的 before 为 null")
        if self.op == "delete" and any(c.after is not None for c in self.cells):
            raise ValueError("删除行的 after 为 null")
        return self


def _check_cells(columns: list[str], rows: list[ViewRow]) -> None:
    for row in rows:
        if len(row.cells) != len(columns):
            raise ValueError("每行的单元格数必须与列数相同")


class ViewMasterTable(Wire):
    columns: list[str]
    rows: list[ViewRow]

    @model_validator(mode="after")
    def _cells(self) -> ViewMasterTable:
        _check_cells(self.columns, self.rows)
        return self


class TargetChoice(Wire):
    entity: Code
    record_key: Key
    selectable: bool
    selected: bool


class ViewDetailTable(Wire):
    title: str
    flow: Code | None = None
    selection: Literal["all", "approverSelects"] | None = None
    columns: list[str]
    merged_columns: list[int] = []
    targets: list[TargetChoice] = []
    rows: list[ViewRow]

    @model_validator(mode="after")
    def _cells(self) -> ViewDetailTable:
        _check_cells(self.columns, self.rows)
        if any(not 0 <= i < len(self.columns) for i in self.merged_columns):
            raise ValueError("mergedColumns 超出列的范围")
        return self


class ApprovalView(Wire):
    master: ViewMasterTable
    details: list[ViewDetailTable] = []


class ApprovalActions(Wire):
    can_pass: bool
    can_reject: bool
    can_withdraw: bool


class ApprovalDetail(Wire):
    approval_id: IdText
    status: ApprovalStatus
    page: Code
    page_title: str
    operation: Code
    operation_label: str
    source: SourceRef
    applicant: UserBrief
    submitted_at: datetime
    current_level: int = Field(ge=1)
    steps: list[ApprovalStep]
    view: ApprovalView
    fingerprint: Fingerprint
    actions: ApprovalActions


class SelectedObject(Wire):
    flow: Code
    entity: Code
    record_key: Key


class PassRequest(Wire):
    request_key: RequestKey
    fingerprint: Fingerprint
    selected_objects: list[SelectedObject] = []
    comment: str | None = None
    params: dict[str, JsonValue] = {}


class RejectRequest(Wire):
    """驳回原因必填，由 approval 检查，没填返回 VALIDATION_FAILED（AP-11）。"""

    request_key: RequestKey
    comment: str | None = None


class WithdrawRequest(Wire):
    request_key: RequestKey
    comment: str | None = None


# ---- 7. delivery

class InboxItem(Wire):
    delivery_id: Uuid
    title: str
    body: str
    link: str | None
    created_at: datetime
    read: bool


class InboxList(Wire):
    rows: list[InboxItem]
    total: int = Field(ge=0)
    unread: int = Field(ge=0)


class DeliveryRow(Wire):
    delivery_id: Uuid
    recipient: IdText
    status: Literal["pending", "sent", "failed", "abandoned"]
    attempts: int = Field(ge=0)
    next_retry_at: datetime | None
    last_error: str | None


class DeliveryList(Wire):
    rows: list[DeliveryRow]
    total: int = Field(ge=0)


# ---- 7a. 命令审查

class SqlTrace(Wire):
    text: str
    binds: dict[str, JsonValue] = {}
    ms: float
    rows: int | None = None
    error: str | None = None


class CommandLog(Wire):
    request_key: RequestKey
    user: str
    page: Code | None
    operation: Code
    result: Literal["saved", "rejected", "failed"]
    error_code: ErrorCode | None
    message: str | None
    started_at: datetime
    duration_ms: float
    sql_count: int = Field(ge=0)
    sql_ms: float
    sql: list[SqlTrace]


class CommandReviewList(Wire):
    enabled: bool
    rows: list[CommandLog]
    total: int = Field(ge=0)


class CommandReviewToggle(Wire):
    enabled: bool


# ---- 8. assembly

class HealthResponse(Wire):
    status: Literal["ok", "starting"]
    core_version: str | None = None
    config_version: int | None = None


# ============================================================ C10 实时事件

class PagesAudience(Wire):
    pages: list[Code] = Field(min_length=1)


class UsersAudience(Wire):
    users: list[IdText] = Field(min_length=1)


class SessionsAudience(Wire):
    sessions: list[str] = Field(min_length=1)


class ConfigChangedPayload(Wire):
    pages: list[Code]
    version: int


class NotificationPayload(Wire):
    delivery_id: Uuid
    title: str
    body: str
    link: str | None


class SessionRevokedPayload(Wire):
    reason: Literal["accountDisabled", "roleRevoked", "loggedOut"]


class ConfigChangedEvent(Wire):
    event_id: Uuid
    topic: Literal["config.changed"]
    audience: PagesAudience
    payload: ConfigChangedPayload


class NotificationEvent(Wire):
    event_id: Uuid
    topic: Literal["notification"]
    audience: UsersAudience
    payload: NotificationPayload


class SessionRevokedEvent(Wire):
    event_id: Uuid
    topic: Literal["session.revoked"]
    audience: UsersAudience | SessionsAudience
    payload: SessionRevokedPayload


ChannelEvent = Annotated[ConfigChangedEvent | NotificationEvent | SessionRevokedEvent, Field(discriminator="topic")]
"""后端进程之间经 Redis 频道传递的事件（C10 第 1 节）。"""

RealtimeEvent = ChannelEvent


class SubscribeMessage(Wire):
    type: Literal["subscribe"]
    pages: list[Code]


class UnsubscribeMessage(Wire):
    type: Literal["unsubscribe"]
    pages: list[Code]


class PingMessage(Wire):
    type: Literal["ping"]


ClientMessage = Annotated[SubscribeMessage | UnsubscribeMessage | PingMessage, Field(discriminator="type")]
"""浏览器经 WebSocket 发送的消息。"""


class PushConfigChanged(Wire):
    topic: Literal["config.changed"]
    event_id: Uuid
    payload: ConfigChangedPayload


class PushNotification(Wire):
    topic: Literal["notification"]
    event_id: Uuid
    payload: NotificationPayload


class PushSessionRevoked(Wire):
    topic: Literal["session.revoked"]
    event_id: Uuid
    payload: SessionRevokedPayload


class PongMessage(Wire):
    type: Literal["pong"]


def _server_message_tag(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("topic") or value.get("type")
    return getattr(value, "topic", None) or getattr(value, "type", None)


ServerMessage = Annotated[
    Annotated[PushConfigChanged, Tag("config.changed")]
    | Annotated[PushNotification, Tag("notification")]
    | Annotated[PushSessionRevoked, Tag("session.revoked")]
    | Annotated[PongMessage, Tag("pong")],
    Discriminator(_server_message_tag),
]
"""服务端经 WebSocket 推送的消息。"""


# ============================================================ C08 后端端口使用的类型

@dataclass(frozen=True)
class DocumentRef:
    """一张单据：主从页为主表实体和主单主键，单表页为该实体和行主键。"""

    entity: str
    record_key: str


@dataclass
class Row:
    entity: str
    row_key: str | None
    client_row_id: str | None
    values: dict[str, Value]


@dataclass
class DocumentData:
    ref: DocumentRef
    master: Row
    details: dict[str, list[Row]] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class FreezeEntry:
    """一张被冻结的单据：冻结主表和全部明细，单表页为这一行。"""

    approval_id: str
    entity: str
    record_key: str


@dataclass(frozen=True)
class TargetObject:
    entity: str
    record_key: str
    row_keys: tuple[str, ...] = ()
    display: dict[str, Value] = dc_field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class NotificationIntent:
    event: str
    recipients: tuple[str, ...]
    title: str
    body: str
    link: str | None


@dataclass(frozen=True)
class ImportReport:
    imported: int
    skipped: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ColumnInfo:
    """数据库中的一列（db-core 的 SchemaInspector）。"""

    name: str
    data_type: str
    nullable: bool
    length: int | None = None
    precision: int | None = None
    scale: int | None = None


@dataclass(frozen=True)
class AccountRef:
    user_id: str
    username: str
    display_name: str
    department_id: str | None
    enabled: bool


@dataclass(frozen=True)
class ImportedAccount:
    user_id: str
    username: str
    display_name: str
    department_id: str | None
    enabled: bool
    password_hash: str = dc_field(repr=False)


@dataclass(frozen=True)
class ImportedRole:
    code: str
    name: str


@dataclass(frozen=True)
class ImportedDepartment:
    department_id: str
    name: str
    parent_id: str | None


@dataclass(frozen=True)
class RoleAssignment:
    user_id: str
    role_code: str


@dataclass(frozen=True)
class AccountBatch:
    """migration 导入的账号（含 BCrypt 哈希）、角色、账号与角色的分配、部门。"""

    accounts: tuple[ImportedAccount, ...] = ()
    roles: tuple[ImportedRole, ...] = ()
    assignments: tuple[RoleAssignment, ...] = ()
    departments: tuple[ImportedDepartment, ...] = ()


@dataclass(frozen=True)
class PersonalConfigEntry:
    user_id: str
    page_code: str
    config: PersonalConfig


@dataclass(frozen=True)
class PersonalConfigBatch:
    entries: tuple[PersonalConfigEntry, ...] = ()


@dataclass(frozen=True)
class SqlCondition:
    """行权限的 SQL 条件：占位符已换成绑定变量名，`binds` 为绑定变量的值。"""

    sql: str
    binds: dict[str, Value] = dc_field(default_factory=dict, hash=False)


PackHandle: TypeAlias = object
"""rules-core 的 load_pack 返回的句柄，对调用方不透明。"""


@dataclass
class RowChange:
    """变更计划中的一行。"""

    document: DocumentRef
    """所属单据。新增的单据在取得主键前，record_key 为主表行的 clientRowId。"""
    entity: str
    op: RowOp
    row_key: str | None
    """新增行在取得主键前为 None。"""
    client_row_id: str | None = None
    values: dict[str, Value] = dc_field(default_factory=dict)
    """新增：要写入的字段；修改：有变化的字段的新值；删除：空。"""
    old: dict[str, Value] = dc_field(default_factory=dict)
    """修改：这些字段的旧值；删除：删除前的整行（审计用）；新增：空。"""


@dataclass
class ChangePlan:
    """只含有变化的列的写入计划，由 write-pipeline 生成并执行。"""

    rows: list[RowChange] = dc_field(default_factory=list)


@dataclass
class CommandState:
    """管道阶段之间传递的数据；每个阶段只写 C08 第 6 节表中它负责的字段。"""

    command: Command
    involved: list[DocumentRef] = dc_field(default_factory=list)
    current: dict[DocumentRef, DocumentData] = dc_field(default_factory=dict)
    actions: list[ActionStep] = dc_field(default_factory=list)
    candidate: dict[DocumentRef, DocumentData] = dc_field(default_factory=dict)
    effects: list[RuleEffect] = dc_field(default_factory=list)
    changes: ChangePlan = dc_field(default_factory=ChangePlan)
    approvals: list[ApprovalState] = dc_field(default_factory=list)
    notifications: list[NotificationIntent] = dc_field(default_factory=list)
    delivery_ids: list[str] = dc_field(default_factory=list)
    prompts: list[Prompt] = dc_field(default_factory=list)
    skipped: list[SkippedRow] = dc_field(default_factory=list)
    pending_documents: set[DocumentRef] = dc_field(default_factory=set)
    outcome: Outcome = Outcome.SAVED
