"""契约类型：C02–C10 中跨模块使用的数据结构。

- 进出 JSON 的结构（C02、C03、C05、C06、C07、C09、C10）用 pydantic 模型：Python 中字段名为
  snake_case，JSON 中为 camelCase（C01 第 1 节）；不允许出现未定义的字段；模型创建后不可修改。
- 后端模块之间传递的结构（C04、C08）用 dataclass。端口协议在 ports.py。

外部数据一律经 `parse_wire` 解析，经 `dump_wire` 输出：
- 解析只认 camelCase 字段名；整数和是非必须是 JSON 的数字和布尔；日期、日期时间必须是 C01 第 4 节的格式。
- 输出时，契约写明总会出现的字段（含值为 null 的）总是输出；可选字段没有值时省略。

本文件只表达契约的数据形状和 C01 规定的值格式。跨字段的规则（例如单表页没有明细、审批流的级别连续）
由提供方模块校验（config 按 C06 第 10 节，其他见各模块说明），不在这里。

按契约编号分节，每节开头注明对应的文档。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    JsonValue,
    PlainSerializer,
    SecretStr,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    Tag,
    TypeAdapter,
    model_serializer,
    model_validator,
)
from pydantic.alias_generators import to_camel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .ports import ConfigSnapshot


# ============================================================ 基础（C01）

class Wire(BaseModel):
    """进出 JSON 的模型的基类。Python 代码可以按 snake_case 字段名构造；外部数据经 parse_wire 只按 camelCase 解析。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="forbid",
        frozen=True,
    )


_adapters: dict[int, tuple[Any, TypeAdapter[Any]]] = {}


def adapter(tp: Any) -> TypeAdapter[Any]:
    """返回某个模型或联合类型的 TypeAdapter，同一类型只创建一次。"""
    found = _adapters.get(id(tp))
    if found is None or found[0] is not tp:
        found = (tp, TypeAdapter(tp))
        _adapters[id(tp)] = found
    return found[1]


def parse_wire(tp: Any, data: Any) -> Any:
    """把外部数据（已由 JSON 解码为 dict、list 等）解析为契约类型；只认 camelCase 字段名。

    不符合契约时抛 pydantic.ValidationError。
    """
    return adapter(tp).validate_python(data, by_alias=True, by_name=False)


def dump_wire(tp: Any, value: Any) -> Any:
    """把契约类型转为可以直接编码为 JSON 的数据：字段名为 camelCase，可选字段没有值时省略。"""
    return adapter(tp).dump_python(value, mode="json", by_alias=True, exclude_defaults=True)


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

Uuid = Annotated[str, StringConstraints(pattern=rf"^{_UUID}$")]
"""小写 UUID：requestKey、eventId、deliveryId（C01 第 5 节）。"""

RequestKey = Uuid
ClientRowId = Annotated[str, StringConstraints(pattern=rf"^tmp-{_UUID}$")]
"""前端为新增行生成的临时编号：`tmp-` 加小写 UUID。"""

DecimalText = Annotated[str, StringConstraints(pattern=r"^-?[0-9]+(\.[0-9]+)?$")]
"""十进制文本（C01 第 2 节）：精确数值、approvalId、userId。解析、格式化和一致判定见 decimal_text。"""

Key = Annotated[str, StringConstraints(min_length=1)]
"""rowKey、recordKey：主键列的值转成的文本。"""

Code = Annotated[str, StringConstraints(min_length=1)]
"""配置中的编码：实体、页面、操作、审批流、规则、角色等。"""

Int: TypeAlias = StrictInt
Bool: TypeAlias = StrictBool
Millis: TypeAlias = StrictInt | StrictFloat

def _exactly(expected: bool) -> Any:
    def check(value: Any) -> Any:
        if value is not expected:
            raise ValueError(f"必须是 JSON 的 {str(expected).lower()}")
        return value
    return BeforeValidator(check)


TrueValue = Annotated[Literal[True], _exactly(True)]
"""只能是 JSON 的 true（不接受 1、1.0）。"""
FalseValue = Annotated[Literal[False], _exactly(False)]
"""只能是 JSON 的 false（不接受 0、0.0）。"""

BusinessValue: TypeAlias = StrictStr | StrictBool | None
"""业务字段在 JSON 中的值：精确数值和文本都是字符串（C01），是非为布尔，空为 null。"""

FieldValues: TypeAlias = dict[str, BusinessValue]

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DATETIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}")


def _date_input(value: Any) -> Any:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and _DATE.fullmatch(value):
        return value
    raise ValueError("日期的格式为 YYYY-MM-DD")


def _datetime_input(value: Any) -> Any:
    if isinstance(value, datetime) and value.tzinfo is None:
        return value
    if isinstance(value, str) and _DATETIME.fullmatch(value):
        return value
    raise ValueError("日期时间的格式为 YYYY-MM-DDTHH:mm:ss，不带时区")


DateText = Annotated[date, BeforeValidator(_date_input)]
"""C01 第 4 节的日期：`YYYY-MM-DD`。"""

DateTimeText = Annotated[
    datetime,
    BeforeValidator(_datetime_input),
    PlainSerializer(lambda v: v.strftime("%Y-%m-%dT%H:%M:%S"), return_type=str, when_used="json"),
]
"""C01 第 4 节的日期时间：`YYYY-MM-DDTHH:mm:ss`，按服务器时区，不带时区后缀；输出到秒。"""

Value: TypeAlias = str | Decimal | bool | date | datetime | None
"""业务字段在后端内部的值（C08 第 1 节）：精确数值为 Decimal。"""

RowOp: TypeAlias = Literal["add", "modify", "delete"]
"""行操作，对应命令中各行的 `op` 和审批流的审核操作 `operations`。"""

FieldType: TypeAlias = Literal["text", "number", "date", "datetime", "boolean"]
ColumnSource: TypeAlias = Literal["erp", "own"]
FieldRole: TypeAlias = Literal["input", "calculated", "system"]
Pinned: TypeAlias = Literal["left", "right"]
Aggregate: TypeAlias = Literal["sum"]
"""页面字段的汇总方式（C06 第 3 节 `aggregate`）：只有求和，对应旧系统列配置的 `aggFunc: "sum"`。"""
PageLayout: TypeAlias = Literal["single", "masterDetail"]
DetailMode: TypeAlias = Literal["tabs", "stack"]


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
    """错误明细：定位到行和字段（被冻结时 `approval_id` 指明冻结它的审批），或定位到配置项和其中的位置。

    后端负责生成（C03 第 1 节"生成和接收的分工"）：构造时只需给出用到的字段，输出时 9 个字段总是出现，没有值的为 null。
    这种宽松只用于错误明细的构造；严格检查收到的错误体由前端负责（T-CT-4），其他请求类型照常严格解析。
    """

    message: str | None = None
    entity: Code | None = None
    row_key: Key | None = None
    client_row_id: ClientRowId | None = None
    field: str | None = None
    approval_id: DecimalText | None = None
    config_type: str | None = None
    config_key: str | None = None
    path: str | None = None

    @model_serializer(mode="wrap")
    def _every_key(self, handler: SerializerFunctionWrapHandler, info: SerializationInfo) -> dict[str, Any]:
        data = handler(self)
        fields = type(self).model_fields
        # 沿用处理函数输出的键名风格；Wire 默认按别名输出，只有明确传 by_alias=False 时才用字段名
        use_alias = info.by_alias is not False
        for name, field_info in fields.items():
            data.setdefault((field_info.alias or name) if use_alias else name, getattr(self, name))
        return data


class ErrorResponse(Wire):
    code: ErrorCode
    message: str
    details: list[ErrorDetail]


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
    copy_of: Key | None = None
    """复制出的行：源行（同一实体）的主键。不可写的复制字段由后端取源行的值，不补默认值（C02 第 1 节）。"""
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
    copy_of: Key | None = None
    """同 `MasterAdd.copy_of`：源行为同一明细实体的行。"""
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
    details: list[DetailChange]


class Command(Wire):
    """命令：业务数据唯一的写入形式。"""

    request_key: RequestKey
    page: Code | None
    operation: Code
    documents: list[DocumentPatch]
    params: dict[str, JsonValue]

    def content_digest(self) -> str:
        """去掉 requestKey 的命令体，按键名排序、去掉空白后取 SHA-256（十六进制小写），用于判重。"""
        body = self.model_dump(mode="json", by_alias=True, exclude={"request_key"})
        text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


Outcome: TypeAlias = Literal["saved", "unchanged", "approvalSubmitted", "approvalProcessed"]


class FrozenMark(Wire):
    """行所在单据被冻结时，冻结它的审批。"""

    approval_id: DecimalText


class ResultRow(Wire):
    """命令结果中写入的行或计算带出变化的行：给出实体的全部字段；未冻结时 `frozen` 为 null。"""

    entity: Code
    row_key: Key
    client_row_id: ClientRowId | None = None
    values: FieldValues
    frozen: FrozenMark | None


class DeletedRow(Wire):
    """命令结果中删除的行。"""

    entity: Code
    row_key: Key
    deleted: TrueValue


def _at_most_one_row_identity(model: Any) -> Any:
    if model.row_key is not None and model.client_row_id is not None:
        raise ValueError("rowKey 和 clientRowId 最多给出一个")
    return model


def _exactly_one_row_identity(model: Any) -> Any:
    if (model.row_key is None) == (model.client_row_id is None):
        raise ValueError("rowKey 和 clientRowId 必须且只能给出一个")
    return model


class Prompt(Wire):
    """规则提示；定位到行时，已保存的行用 row_key，新增行用 client_row_id。"""

    rule: Code
    message: str
    entity: Code | None = None
    row_key: Key | None = None
    client_row_id: ClientRowId | None = None
    field: str | None = None

    check_row_identity = model_validator(mode="after")(_at_most_one_row_identity)


class SkippedRow(Wire):
    """因行已被删除而跳过的修改。"""

    entity: Code
    row_key: Key
    reason: Literal["ROW_NOT_FOUND"]


ApprovalStatus: TypeAlias = Literal["pending", "approved", "rejected", "withdrawn"]


class ApprovalRef(Wire):
    """本命令提交或处理的审批。"""

    approval_id: DecimalText
    document: RecordRef
    status: ApprovalStatus
    level: Int
    flows: list[Code]


ApprovalState = ApprovalRef
"""C08 CommandState.approvals 的元素，与命令结果中的 `approvals` 相同。"""


class CommandResult(Wire):
    request_key: RequestKey
    outcome: Outcome
    rows: list[ResultRow | DeletedRow]
    id_map: dict[ClientRowId, Key]
    prompts: list[Prompt]
    skipped: list[SkippedRow]
    approvals: list[ApprovalRef]


# ============================================================ C04 执行上下文

@dataclass(frozen=True)
class Identity:
    user_id: str
    username: str
    display_name: str
    department_id: str | None
    role_code: str
    session_id: str = dc_field(repr=False)
    department_name: str | None = None  # C04 v2：部门名称，identity 登录时填；没有部门或部门已删除时为 None


@dataclass(frozen=True)
class Origin:
    kind: Literal["user", "approval"]
    approval_id: str | None

    def __post_init__(self) -> None:
        if self.kind == "approval" and self.approval_id is None:
            raise ValueError("来源为审批时必须给出 approval_id")


@dataclass(frozen=True)
class ExecutionContext:
    request_id: str
    identity: Identity
    config: ConfigSnapshot
    config_version: int
    origin: Origin
    now: datetime


# ============================================================ C05 页面视图

class LookupFilter(Wire):
    column: str
    from_: Literal["row", "cell"] = Field(alias="from")
    field: str | None = None


class LookupSetting(Wire):
    """Lookup 设置：C06 第 3 节页面配置和 C05 页面视图用同一写法。"""

    code: Code
    fill: dict[str, str]
    multiple: Bool = False
    filter: LookupFilter | None = None
    fill_back: Bool = True


class LookupColumn(Wire):
    """Lookup 的一个显示列（C06 第 9 节 `columns` 写成对象时；C05 `lookup.columns`）：`label` 是对话框中的列标题，
    省略时显示列名；`width` 是列宽（像素），省略时各列平分。同旧系统 Lookup 配置 `displayColumns` 的 `header`、`width`。"""

    column: str
    label: str | None = None
    width: Int | None = None


class ViewLookup(LookupSetting):
    """页面视图中的 Lookup（C05）：页面配置的设置，加上 Lookup 配置的显示列（`label` 已按列名补上）。"""

    columns: list[LookupColumn] = []


def _view_lookup(value: Any) -> Any:
    """页面视图的字段也可以直接给页面配置的 `LookupSetting`，这时没有显示列。"""
    if isinstance(value, LookupSetting) and not isinstance(value, ViewLookup):
        return ViewLookup(**dict(value))
    return value


class StaticDefault(Wire):
    type: Literal["static"]
    value: str


class BuiltinDefault(Wire):
    type: Literal["builtin"]
    value: Literal["currentUserId", "currentUserName", "currentDeptId", "currentDeptName", "currentRoleCode", "currentTime"]


class OptionsDefault(Wire):
    type: Literal["options"]
    value: list[str]


DefaultValue = Annotated[StaticDefault | BuiltinDefault | OptionsDefault, Field(discriminator="type")]
"""字段的默认值（C06 第 2 节 `fields[].default`），页面视图原样带出（C05 v9）。"""

CompareFormat: TypeAlias = Literal["value", "percent", "both"]


class FieldCompareView(Wire):
    """页面视图中字段的对比（C05 v9）：只带显示方式，取自实体字段的 `compare.format`（C06 第 2 节）。"""

    format: CompareFormat


class ViewField(Wire):
    name: str
    label: str
    type: FieldType
    scale: Int | None
    source: ColumnSource
    calculated: Bool
    visible: Bool
    editable: Bool
    required: Bool
    width: Int | None
    pinned: Pinned | None
    dict_type: Code | None
    lookup: Annotated[ViewLookup | None, BeforeValidator(_view_lookup)]
    aggregate: Aggregate | None = None
    """汇总行：`sum` 为在表格底部的汇总行中求和（C06 第 3 节）；没有时省略。"""
    fill_writable: Bool = False
    """字段不可编辑，但它是本区域可编辑字段的 Lookup 回填目标（`fillBack` 为 true），且保存时能写（在保存操作的
    `writableFields` 中、有写入列，authz 的 AZ-04）：前端把 Lookup 回填和复制带来的值写进命令。为 false 时省略。"""
    grouping: Bool = False
    """千分位：取自实体字段（C06 第 2 节），数值显示时整数部分每三位加英文逗号；为 false 时省略。"""
    dict_free_text: Bool = False
    """字典下拉中可以填写字典以外的值：取自页面配置（C06 第 3 节）；为 false 时省略。"""
    searchable: Bool = False
    """页面配置的 `searchable` 为 true 且字段可见：高级查询对话框一打开就列出这个字段的条件（C05 v7）。为 false 时省略。"""
    default: DefaultValue | None = None
    """新增行的默认值：取自实体字段（C06 第 2 节），写法相同（C05 v9）；没有配置时省略。"""
    compare: FieldCompareView | None = None
    """对比的显示方式：实体字段配了 `compare` 时给出它的 `format`（C05 v9）；没有配置时省略。"""


class ViewButton(Wire):
    key: Code
    action: Code
    label: str
    operation: Code | None
    requires_selection: Bool


class GridOptions(Wire):
    side_bar: Bool
    cell_selection: Bool
    group_by: list[str]


class FormCell(Wire):
    """表单布局的一格：24 列网格，`x` 从 0 起；越界由 config 在保存时拒绝。"""

    field: str
    x: Int
    y: Int
    w: Int
    h: Int


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
    can_modify: Bool = True
    """C05 v8：当前角色能否修改本区域已经保存的行（角色权限 `<区域>:modify`，C06 第 8 节）。为 false 时这些行的字段
    都不能编辑；新增、复制出的行不受影响，按 `fields[].editable`。为 true 时省略。"""


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
    can_modify: Bool = True
    """同 `ViewMaster.can_modify`，权限键为 `<明细实体>:modify`。"""


class PackRef(Wire):
    pack_id: Code
    version: Int


SystemButton: TypeAlias = Literal["save", "addRow", "deleteRow", "advancedSearch"]
"""C05 v8 起 config 只给出 `save`、`advancedSearch`；新增、删除按区域授权，见区域的 `buttons`。`addRow`、`deleteRow`
留在这里，是为了能读 v8 之前生成、下次保存配置前还没重新生成的页面视图，前端不用这两项。"""


class PageView(Wire):
    page_code: Code
    title: str
    version: Int
    layout: PageLayout
    detail_mode: DetailMode
    audit: Bool
    save_operation: Code | None
    """C05 v10：只读页面（页面配置的 `saveOperation` 为 null，C06 v29 第 3 节）为 null，`system_buttons` 不含 `save`。"""
    rules_pack: PackRef
    master: ViewMaster
    details: list[ViewDetail]
    system_buttons: list[SystemButton]


# ============================================================ C06 配置模型
#
# 管理员保存的配置内容原样存储；这里的模型用于读取和校验结构。保存时的其余校验见 C06 第 10 节，由 config 负责。
# 哪些字段可以省略、省略时取什么值，按 C06 第 1.1 节：这里带默认值的字段与该节的表格逐项对应，其他字段都必须写出。

CompareOp: TypeAlias = Literal["eq", "ne", "gt", "ge", "lt", "le", "like", "in", "isNull", "isNotNull"]
Logic: TypeAlias = Literal["AND", "OR"]


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


# ---- 2. entity
# 字段的默认值（`StaticDefault` 等）和对比的显示方式（`CompareFormat`）定义在 C05 一节，页面视图也用它们。


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
    keys: list[CompareKey]
    field: str
    format: CompareFormat


FieldCompareConfig = Annotated[FieldCompare | QueryCompare, Field(discriminator="mode")]


class EntityField(Wire):
    name: str
    column: str | None
    label: str
    type: FieldType
    scale: Int | None = None
    grouping: Bool = False
    """千分位（C06 第 2 节）：数值显示时整数部分每三位加英文逗号，只用于显示；同旧系统列配置 `rulesConfig.useGrouping`。"""
    source: ColumnSource
    role: FieldRole
    default: DefaultValue | None = None
    compare: FieldCompareConfig | None = None


class DetailLink(Wire):
    entity: Code
    parent_key: str


class FieldFlags(Wire):
    visible: Bool | None = None
    editable: Bool | None = None
    required: Bool | None = None


class RequiredConditionItem(Wire):
    field: str
    op: Literal["eq", "ne", "isNull", "isNotNull"]
    value: str | None = None


class RequiredCondition(Wire):
    logic: Logic
    conditions: list[RequiredConditionItem]


class ApprovalRequiredRule(Wire):
    fields: list[str]
    when: RequiredCondition | None = None
    source_pages: list[Code]


class EntityConfig(Wire):
    table: str
    primary_key: str
    freezable: Bool
    read_view: str | None = None
    erp_row: ErpRow | None = None
    updated_by_column: str | None = None
    """写入修改人的列（`table` 中的列名，不是实体字段）：新增、修改这个实体的行时写当前用户的登录名（C06 第 2 节、WP-20）。"""
    fields: list[EntityField]
    details: list[DetailLink] = []
    field_defaults: dict[str, FieldFlags] = {}
    approval_required: list[ApprovalRequiredRule] = []


# ---- 3. page

class FieldSetting(Wire):
    visible: Bool | None = None
    editable: Bool | None = None
    required: Bool | None = None
    width: Int | None = None
    pinned: Pinned | None = None
    dict_type: Code | None = None
    dict_free_text: Bool = False
    """为 true 时字典下拉中还可以填写字典以外的值（C06 第 3 节，旧系统"下拉（可填写）"）。"""
    lookup: LookupSetting | None = None
    aggregate: Aggregate | None = None
    searchable: Bool | None = None
    """查询（C06 第 3 节，旧系统列配置的"查询"）：为 true 时高级查询对话框一打开就列出这个字段的条件；省略为不预置。"""


class ButtonConfig(Wire):
    """区域按钮：业务动作必须写 `operation` 和 `requires_selection`，内置动作两项都不写（C06 第 3 节，保存时由 config 检查）。"""

    action: Code
    label: str
    operation: Code | None = None
    requires_selection: Bool | None = None


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
    detail_mode: DetailMode
    audit: Bool
    save_operation: Code | None
    """必须写；为 null 时是只读页面（C06 v29 第 3 节，依据旧系统审计追踪页 auditLog）：没有保存，只能查询、筛选、排序、导出。"""
    master: PageMasterConfig
    details: list[PageDetailConfig] = []


# ---- 6.1 查找方式（按钮的 updateRecords 使用）

class RelationKeyFinder(Wire):
    kind: Literal["relationKey"]
    entity: Code
    target_key: str
    source_key: str
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


class Recalculate(Wire):
    action: Literal["recalculate"]
    target: Literal["source", "targets"]


class TargetUpdate(Wire):
    entity: Code
    detail_entity: Code | None = None
    match: dict[str, str] = {}
    field_mapping: list[FieldMap]


class UpdateTargets(Wire):
    action: Literal["updateTargets"]
    targets: list[TargetUpdate]


class UpdateRecords(Wire):
    action: Literal["updateRecords"]
    find: TargetFinder
    field_mapping: list[FieldMap]


class ReplaceDetails(Wire):
    """按 SQL 查出的行替换选中单据的一个明细实体（C06 第 6 节，v18）：删除这个明细的全部行，再把 SQL 的每一行新增为
    一行，列按列名写到同名字段；绑定变量只引用选中单据主表的字段，每张单据执行一次。"""

    action: Literal["replaceDetails"]
    entity: Code
    sql: str
    binds: dict[str, str] = {}


class UpdateRows(Wire):
    """按 SQL 找到要改的记录和新值并更新（C06 第 6 节，v18）：SQL 执行一次，不用绑定变量，不看选中行；
    `recordKeyColumn`、`rowKeyColumns` 同 6.1，其余列按列名写到同名字段。"""

    action: Literal["updateRows"]
    entity: Code
    sql: str
    record_key_column: str
    row_key_columns: list[str] = []


class EscapeHatch(Wire):
    action: Literal["escapeHatch"]
    operation: Code


ActionStep = Annotated[
    Recalculate | UpdateTargets | UpdateRecords | ReplaceDetails | UpdateRows | EscapeHatch,
    Field(discriminator="action"),
]
"""按钮操作的通用动作（C06 第 6 节）。审批流通过后的操作见 `BlockAction`。"""


# ---- 4. operation

class OperationConfig(Wire):
    label: str
    kind: Literal["save", "action", "escapeHatch"]
    writable_fields: dict[str, list[str]] = {}
    impact: list[Code] = []
    actions: list[ActionStep] = []
    row_not_found: Literal["skip", "reject"] = "skip"
    propagation: Literal["continue", "end"]
    procedure: str | None = None
    writes: dict[str, list[str]] = {}


# ---- 5. rule

class Branch(Wire):
    when: Condition | None = None
    expression: str


class UiEffect(Wire):
    editable: Bool | None = None
    required: Bool | None = None
    row_style: JsonValue = None
    cell_style: JsonValue = None


class RuleConfig(Wire):
    layer: Literal["entity", "operation", "page"]
    target: Code
    category: Literal["calc", "validate", "ui"]
    field: str | None = None
    order: Int
    when: Condition | None = None
    expression: str | None = None
    branches: list[Branch] | None = None
    level: Literal["reject", "prompt"] | None = None
    message: str | None = None
    effect: UiEffect | None = None


# ---- 7. approvalFlow

class UserApprover(Wire):
    type: Literal["user"]
    user_id: DecimalText


class RoleApprover(Wire):
    type: Literal["role"]
    role: Code


class SqlApprover(Wire):
    type: Literal["sql"]
    sql: str
    binds: dict[str, str] = {}


Approver = Annotated[UserApprover | RoleApprover | SqlApprover, Field(discriminator="type")]


class FlowNode(Wire):
    """审批节点（C06 7.3）：`condition` 为带参数的 SQL 条件片段（C06 7.2），`condition_type` 为 sql 时必须写。"""

    name: str
    condition_type: Literal["always", "sql"]
    condition: str | None = None
    department: Key | None = None
    """发起部门限制：部门编号，为空表示不限。"""
    approvers: list[Approver]
    mode: Literal["or", "and"]
    enabled: Bool = True


class FlowLevel(Wire):
    level: Int
    nodes: list[FlowNode]


class FreezeItem(Wire):
    """冻结节点的一项（C06 7.4）：冻结表可以不在平台注册，只能是表；关联条件每个触发本审批的行执行一次。"""

    table: str
    condition: str
    enabled: Bool = True


_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


class DisplayColumn(Wire):
    """展示数据的一列（C06 7.5）：`field` 为展示表或视图的列，修改表注册过时也可以写 `master.字段`。"""

    field: Annotated[str, StringConstraints(pattern=rf"^(master\.)?{_IDENT}$")]
    label: str
    precision: Int | None = None
    width: Int | None = None
    target_column: str | None = None
    """对应修改表的哪一列，省略时按同名对应；只用于受影响单据的块。"""


class FieldWrite(Wire):
    """写入一列：`column` 为修改表的列，`value` 为取值（SQL 表达式片段，C06 7.2）。"""

    column: str
    value: str


class UpdateFields(Wire):
    """按主键修改修改表的这一行（C06 7.5）。"""

    action: Literal["updateFields"]
    fields: list[FieldWrite]


class InsertRows(Wire):
    """每个勾选的行在 `table` 中新增一行（C06 7.5）；主键取序列 `<表名>_SEQ`。"""

    action: Literal["insertRows"]
    table: str
    fields: list[FieldWrite]


class DeleteRows(Wire):
    """按主键删除修改表的这一行（C06 7.5）。"""

    action: Literal["deleteRows"]


BlockAction = Annotated[UpdateFields | InsertRows | DeleteRows | EscapeHatch, Field(discriminator="action")]
"""审批流全部级别通过后，对受影响单据勾选的行执行的操作（C06 7.5）。"""


class DisplayBlock(Wire):
    """展示数据的一块（C06 7.5）：修改内容的主表、明细，或受影响单据。"""

    key: Code
    title: str
    region: Literal["master", "detail", "affected"]
    source: str
    """`master`、`detail` 为本页面的表格（实体编码）；`affected` 为表名或视图名。"""
    condition: str | None = None
    target_table: str | None = None
    key_column: str | None = None
    columns: list[DisplayColumn]
    selection: Literal["checked", "all", "hidden"] | None = None
    actions: list[BlockAction] = []


class FlowParam(Wire):
    name: str
    label: str
    type: Literal["string", "number", "boolean", "date"]
    source: Literal["manual", "constant", "expression"]
    required: Bool
    level: Int | None = None
    value: JsonValue = None


class NotifyUsers(Wire):
    users: list[DecimalText]


class NotifyRole(Wire):
    role: Code


class NotifyRule(Wire):
    event: Literal["submitted", "levelEntered", "passed", "rejected", "withdrawn"]
    to: Literal["levelApprovers", "applicant"] | NotifyUsers | NotifyRole


class ApprovalFlowConfig(Wire):
    """审批流（C06 第 7 节）：配在所属页面下，第 1 级节点的入口条件逐行判断触发本审批的行。"""

    page: Code
    order: Int
    enabled: Bool = True
    operations: dict[str, list[RowOp]]
    """审核操作：键为本页面的表格（实体编码），值为选中的操作。"""
    levels: list[FlowLevel]
    freeze: list[FreezeItem] = []
    display: list[DisplayBlock] = []
    params: list[FlowParam] = []
    propagation: Literal["end"] = "end"
    notify: list[NotifyRule] = []


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
    admin: Bool
    pages: dict[Code, RolePage] = {}


# ---- 9. menu、dict、lookup、export

class MenuItem(Wire):
    key: Code
    title: str
    kind: Literal["group", "page", "config", "admin"]
    page_code: Code | None = None
    icon: str | None = None  # C06 v26：Iconify 图标名，例如 mdi:calculator-variant；省略时外壳用默认图标
    children: list[MenuItem] = []


class MenuConfig(Wire):
    items: list[MenuItem]


class DictEntry(Wire):
    value: str
    label: str
    order: Int


class DictConfig(Wire):
    items: list[DictEntry]


class LookupConfig(Wire):
    table: str
    columns: list[str | LookupColumn]
    """查询和显示的列：列名，或带显示标题、宽度的 `LookupColumn`（C06 第 9 节）。"""
    keyword_columns: list[str]
    order_by: str | None = None

    def column_names(self) -> list[str]:
        """`columns` 中的列名，按顺序。"""
        return [c if isinstance(c, str) else c.column for c in self.columns]

    def display_columns(self) -> list[LookupColumn]:
        """`columns` 中的每一列写成 `LookupColumn`，`label` 没写时为列名（C05 `lookup.columns`）。"""
        return [LookupColumn(column=c, label=c) if isinstance(c, str) else c.model_copy(update={"label": c.label or c.column})
                for c in self.columns]


class ExportColumn(Wire):
    field: str
    header: str


class ExportMaster(Wire):
    sheet: str
    sql: str
    key_column: str
    columns: list[ExportColumn]


class ExportDetail(Wire):
    sheet: str
    sql: str
    link_column: str
    columns: list[ExportColumn]


class ExportConfig(Wire):
    page: Code
    name: str
    file_name: str
    font: str = "Calibri"
    detail_layout: Literal["perMaster", "perDetail"] = "perMaster"
    master: ExportMaster
    details: list[ExportDetail] = []


# ---- 1. 配置项

ConfigType: TypeAlias = Literal["entity", "page", "operation", "rule", "approvalFlow", "role", "menu", "dict", "lookup", "export"]

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


def parse_config_content(config_type: str, content: Any) -> Wire:
    """按配置项的类型解析 `content`；不符合 C06 的结构时抛 pydantic.ValidationError。"""
    return parse_wire(CONFIG_CONTENT[config_type], content)


class ConfigDraft(Wire):
    """要保存或校验的配置项：还没有版本号。"""

    type: ConfigType
    key: Code
    name: str
    content: dict[str, JsonValue]


class ConfigItemSummary(Wire):
    type: ConfigType
    key: Code
    name: str
    version: Int
    updated_by: DecimalText
    updated_at: DateTimeText


class ConfigItem(ConfigItemSummary):
    content: dict[str, JsonValue]


# ============================================================ C07 规则内核接口

class PackField(Wire):
    type: FieldType
    scale: Int | None = None
    role: FieldRole
    source: ColumnSource


class PackRule(Wire):
    id: Code
    layer: Literal["entity", "operation", "page"]
    entity: Code | None = None
    operation: Code | None = None
    page: Code | None = None
    category: Literal["calc", "validate", "ui"]
    order: Int
    server_only: Bool
    jdm: Code


class JdmGraph(Wire):
    """ZEN 的 JDM；允许的节点种类由 rules-core 在 load_pack 时检查。"""

    nodes: list[dict[str, JsonValue]]
    edges: list[dict[str, JsonValue]]


class RulesPack(Wire):
    pack_id: Code
    version: Int
    core_version: str
    fields: dict[str, dict[str, PackField]]
    rules: list[PackRule]
    jdm: dict[str, JdmGraph]


class EvalContext(Wire):
    user_id: DecimalText
    department_id: Key | None
    role: Code
    today: DateText
    origin: Literal["user", "approval"]


class EvalRow(Wire):
    """求值请求中的一行：已保存的行用 rowKey，新增行用 clientRowId；`old` 只列出改过的字段的旧值。"""

    row_key: Key | None = None
    client_row_id: ClientRowId | None = None
    values: FieldValues
    old: FieldValues | None = None

    check_row_identity = model_validator(mode="after")(_exactly_one_row_identity)


class EvalDocument(Wire):
    entity: Code
    master: EvalRow
    details: dict[str, list[EvalRow]]


class ChangedRow(Wire):
    entity: Code
    row_key: Key | None = None
    client_row_id: ClientRowId | None = None
    op: RowOp
    fields: list[str]


class EvaluationRequest(Wire):
    # display：只执行界面规则，页面一显示就用（C07 v6 第 3.1 节）；后端只发 operation
    purpose: Literal["operation", "display"]
    operation: Code | None = None
    page: Code | None = None
    phase: Literal["preview", "commit"]
    context: EvalContext
    document: EvalDocument
    changed: list[ChangedRow]
    data: dict[str, JsonValue]


class FieldState(Wire):
    editable: Bool | None = None
    required: Bool | None = None


class RowStyle(Wire):
    row: JsonValue
    cells: dict[str, JsonValue]


class EvalRowResult(Wire):
    """一行的计算结果：已保存的行用 row_key，新增行用请求中的 client_row_id。"""

    entity: Code
    row_key: Key | None = None
    client_row_id: ClientRowId | None = None
    computed: FieldValues
    fields: dict[str, FieldState]
    style: RowStyle

    check_row_identity = model_validator(mode="after")(_exactly_one_row_identity)


class PromptEffect(Wire):
    kind: Literal["prompt"]
    rule: Code
    message: str
    entity: Code | None = None
    row_key: Key | None = None
    client_row_id: ClientRowId | None = None
    field: str | None = None

    check_row_identity = model_validator(mode="after")(_at_most_one_row_identity)


class RejectEffect(Wire):
    kind: Literal["reject"]
    rule: Code
    message: str
    entity: Code | None = None
    row_key: Key | None = None
    client_row_id: ClientRowId | None = None
    field: str | None = None

    check_row_identity = model_validator(mode="after")(_at_most_one_row_identity)


RuleEffect = Annotated[PromptEffect | RejectEffect, Field(discriminator="kind")]


class EvalError(Wire):
    code: Literal["PACK_INVALID", "INPUT_INVALID", "EVAL_FAILED"]
    message: str


class EvalComputed(Wire):
    """计算和规则的结果：`rows`、`effects` 总会出现，没有时为空数组。"""

    ok: TrueValue
    rows: list[EvalRowResult]
    effects: list[RuleEffect]


class EvalFailure(Wire):
    """规则包或请求本身有问题；不返回部分结果。"""

    ok: FalseValue
    error: EvalError


def _evaluation_tag(value: Any) -> str | None:
    if isinstance(value, dict):
        return "failure" if "error" in value else "computed"
    return {EvalComputed: "computed", EvalFailure: "failure"}.get(type(value))


EvaluationResult = Annotated[
    Annotated[EvalComputed, Tag("computed")] | Annotated[EvalFailure, Tag("failure")],
    Discriminator(_evaluation_tag),
]
"""C07 第 3 节的求值结果，两种形状之一。"""


# ============================================================ C09 HTTP 接口

# ---- 1. 共用类型

class CurrentUser(Wire):
    user_id: DecimalText
    username: str
    display_name: str
    department_id: Key | None
    department_name: str | None  # C09 v15：部门名称（默认值"当前部门名称"）


class RoleRef(Wire):
    code: Code
    name: str
    admin: Bool


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
    username: str
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
    config_version: Int
    csrf_token: str


class Account(Wire):
    user_id: DecimalText
    username: str
    display_name: str
    department_id: Key | None
    enabled: Bool
    role_codes: list[Code]


class AccountList(Wire):
    rows: list[Account]
    total: Int


class AccountCreate(Wire):
    username: str
    display_name: str
    department_id: Key | None
    password: SecretStr
    role_codes: list[Code]


class AccountUpdate(Wire):
    display_name: str
    department_id: Key | None
    role_codes: list[Code]
    enabled: Bool
    username: str | None = None  # C09 v15：改账号名；省略时不改


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
    name: str
    content: dict[str, JsonValue]


class ConfigSaveResponse(Wire):
    type: ConfigType
    key: Code
    version: Int


class ConfigValidateRequest(Wire):
    items: list[ConfigDraft]


class ConfigValidateResponse(Wire):
    ok: Bool
    errors: list[ErrorDetail]


class WizardColumnsRequest(Wire):
    read_view: str | None = None
    table: str


class WizardSequence(Wire):
    name: str
    exists: Bool


class WizardColumn(Wire):
    name: str
    type: FieldType
    label: str
    in_table: Bool


class WizardColumnsResponse(Wire):
    primary_key: str
    sequence: WizardSequence
    columns: list[WizardColumn]


class SchemaColumnsRequest(Wire):
    """审批流配置中按表名或视图名读出列（C09 第 3 节）。"""

    name: str


class SchemaColumn(Wire):
    name: str
    type: FieldType


class SchemaColumnsResponse(Wire):
    object_type: Literal["table", "view"] | None
    primary_key: str | None
    columns: list[SchemaColumn]


class SchemaObjectsRequest(Wire):
    """按关键字列出表和视图（C09 v16 第 3 节，新建页面向导、"表与列"填视图名和目标表时用）。"""

    keyword: str


class SchemaObject(Wire):
    name: str
    type: Literal["table", "view"]


class SchemaObjectsResponse(Wire):
    """名称中含关键字的表和视图，最多 100 个，先表后视图、各按名称排列（同旧系统 `MetaConfigService.listDbObjects`）。"""

    objects: list[SchemaObject]


class WizardGenerateRequest(Wire):
    """新建页面向导的生成请求；`master`、`details` 的内容由 config CF-14 校验。"""

    parent_menu: Code
    page_code: Code
    title: str
    layout: PageLayout
    detail_mode: DetailMode
    audit: Bool
    master: dict[str, JsonValue]
    details: list[dict[str, JsonValue]]


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
    start_row: Int
    end_row: Int
    sort_model: list[SortItem] = []
    filter_model: dict[str, dict[str, JsonValue]] = {}
    advanced: AdvancedQuery | None = None


class ListResponse(Wire):
    rows: list[DataRow]
    total: Int
    aggregates: FieldValues


class ByKeysRequest(Wire):
    entity: Code
    row_keys: list[Key]


class RowsResponse(Wire):
    rows: list[DataRow]


class RecordResponse(Wire):
    master: DataRow
    details: dict[str, list[DataRow]]


class LookupSearchFilter(Wire):
    column: str
    value: str | None


class LookupSearchRequest(Wire):
    keyword: str = ""
    filter: LookupSearchFilter | None = None
    start_row: Int
    end_row: Int


class LookupRow(Wire):
    values: FieldValues


class LookupSearchResponse(Wire):
    rows: list[LookupRow]
    total: Int
    keyword_search: Bool
    """该 Lookup 是否支持关键字搜索（`keywordColumns` 不为空）。"""


class DictItem(Wire):
    value: str
    label: str


class DictResponse(Wire):
    items: list[DictItem]


class PersonalColumn(Wire):
    field: str
    width: Int | None
    pinned: Pinned | None
    hide: Bool


class PersonalGrid(Wire):
    columns: list[PersonalColumn]


class PersonalConfig(Wire):
    """个人列配置：`grids` 的键为 `master` 或明细实体。保存时只含要替换的部分；没有保存过的部分不出现。"""

    grids: dict[str, PersonalGrid] | None = None
    detail_mode: DetailMode | None = None


class ExportItem(Wire):
    export_code: Code
    name: str


class ExportList(Wire):
    items: list[ExportItem]


class PageExportRequest(Wire):
    mode: Literal["page"]
    request: ListRequest
    columns: list[str]


class ConfigExportRequest(Wire):
    mode: Literal["config"]
    export_code: Code
    scope: Literal["current", "all"]
    request: ListRequest


ExportRequest = Annotated[PageExportRequest | ConfigExportRequest, Field(discriminator="mode")]


# ---- 6. approval

class UserBrief(Wire):
    user_id: DecimalText
    display_name: str


class SourceRef(Wire):
    entity: Code
    record_key: Key
    label: str | None


class ApprovalSummary(Wire):
    approval_id: DecimalText
    page: Code
    page_title: str
    operation: Code
    operation_label: str
    source: SourceRef
    applicant: UserBrief
    submitted_at: DateTimeText
    status: ApprovalStatus
    level: Int


class ApprovalList(Wire):
    rows: list[ApprovalSummary]
    total: Int


class StepMember(Wire):
    type: Literal["user", "role"]
    id: Key
    name: str
    status: Literal["pending", "passed", "rejected", "withdrawn", "skipped"]
    processed_by: UserBrief | None
    processed_at: DateTimeText | None
    comment: str | None


class ApprovalStep(Wire):
    level: Int
    flow: Code
    flow_name: str
    node: str
    mode: Literal["or", "and"]
    status: Literal["passed", "pending", "rejected", "upcoming", "withdrawn"]
    members: list[StepMember]


class ViewCell(Wire):
    before: BusinessValue
    after: BusinessValue


class RowRef(Wire):
    """受影响单据的一行：修改表的主键值（C06 7.5）。"""

    key: Key


class ViewRow(Wire):
    """"修改内容"的一行：来源单据的行带 `flows`；受影响单据的行带 `ref` 和 `checked`（主键相同的后续行省略），
    记录已不存在的行带 `missing`。"""

    op: Literal["modify", "add", "delete", "none"]
    cells: list[ViewCell]
    flows: list[Code] | None = None
    ref: RowRef | None = None
    checked: Bool | None = None
    missing: TrueValue | None = None


class ViewMasterTable(Wire):
    key: Code
    title: str
    columns: list[str]
    rows: list[ViewRow]
    widths: list[Int | None] | None = None
    """C09 v14：各列的宽度，与 `columns` 一一对应，取 C06 7.5 `display[].columns[].width`，没配的为 null（前端按 170
    显示，同旧系统 `ApprovalPresentationGrid.vue` 第 188 行）；v14 之前结束时存下的修改内容没有这一项，省略。"""


class ViewDetailTable(Wire):
    key: Code
    title: str
    columns: list[str]
    rows: list[ViewRow]
    widths: list[Int | None] | None = None
    """同 `ViewMasterTable.widths`。"""


class ViewAffectedTable(Wire):
    """受影响单据的一块（C06 7.5）；`selection` 为 hidden 的块不返回。"""

    flow: Code
    key: Code
    title: str
    selection: Literal["checked", "all"]
    editable: Bool
    """当前用户这次通过能不能改勾选。"""
    columns: list[str]
    rows: list[ViewRow]
    widths: list[Int | None] | None = None
    """同 `ViewMasterTable.widths`。"""


class ApprovalView(Wire):
    master: ViewMasterTable
    details: list[ViewDetailTable]
    affected: list[ViewAffectedTable]


class ApprovalActions(Wire):
    can_pass: Bool
    can_reject: Bool
    can_withdraw: Bool


class ApprovalHistoryItem(Wire):
    """审批记录的一条（C09 v14）：提交、通过、驳回、撤回各一条，按时间先后排列；`comment` 为意见、驳回原因或撤回原因。"""

    action: Literal["submit", "pass", "reject", "withdraw"]
    level: Int
    """提交为 1；通过、驳回为处理时所在的级别；撤回为撤回时的当前级别。"""
    by: UserBrief
    at: DateTimeText
    comment: str | None


class ApprovalDetail(Wire):
    approval_id: DecimalText
    status: ApprovalStatus
    page: Code
    page_title: str
    operation: Code
    operation_label: str
    source: SourceRef
    applicant: UserBrief
    submitted_at: DateTimeText
    current_level: Int
    steps: list[ApprovalStep]
    view: ApprovalView
    fingerprint: str
    params: list[FlowParam]
    """当前用户这次通过要填写的人工参数（C06 7.1）；不需要填写时为空数组。"""
    actions: ApprovalActions
    history: list[ApprovalHistoryItem]
    """C09 v14：审批记录（旧系统审批详情底部的"审批记录（N）"，`WF_APPROVAL_LOG`）。"""
    view_unsaved: TrueValue | None = None
    """已结束的审批没有保存结束那一刻的修改内容时为 true，`view` 的各表为空（C06 7.6、C09 第 6 节）。"""


class CheckedRow(Wire):
    """审批人勾选的一行：哪个审批流的哪一块，以及这一行修改表的主键值（C06 7.5）。"""

    flow: Code
    block: Code
    key: Key


class PreviewRequest(Wire):
    """审批人改了勾选后，按这些勾选重新计算详情（C09 第 6 节）。"""

    checked_rows: list[CheckedRow] = []


class PreviewResponse(Wire):
    view: ApprovalView
    fingerprint: str


class PassRequest(Wire):
    request_key: RequestKey
    fingerprint: str
    checked_rows: list[CheckedRow] = []
    """当前用户能改勾选的块中勾选的行；只能从上一级保留的行中选。"""
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
    created_at: DateTimeText
    read: Bool


class InboxList(Wire):
    rows: list[InboxItem]
    total: Int
    unread: Int


class DeliveryRow(Wire):
    delivery_id: Uuid
    recipient: DecimalText
    status: Literal["pending", "sent", "failed", "abandoned"]
    attempts: Int
    next_retry_at: DateTimeText | None
    last_error: str | None


class DeliveryList(Wire):
    rows: list[DeliveryRow]
    total: Int


# ---- 7a. 命令审查

class SqlTrace(Wire):
    text: str
    binds: dict[str, JsonValue]
    ms: Millis
    rows: Int | None
    error: str | None


class CommandLog(Wire):
    request_key: RequestKey
    user: str
    page: Code | None
    operation: Code
    result: Literal["saved", "rejected", "failed"]
    error_code: ErrorCode | None
    message: str | None
    started_at: DateTimeText
    duration_ms: Millis
    sql_count: Int
    sql_ms: Millis
    sql: list[SqlTrace]


class CommandReviewList(Wire):
    enabled: Bool
    rows: list[CommandLog]
    total: Int


class CommandReviewToggle(Wire):
    enabled: Bool


# ---- 8. assembly

class HealthResponse(Wire):
    status: Literal["ok", "starting"]
    core_version: str | None = None
    config_version: Int | None = None


# ============================================================ C10 实时事件

class PagesAudience(Wire):
    pages: list[Code]


class UsersAudience(Wire):
    users: list[DecimalText]


class SessionsAudience(Wire):
    sessions: list[str]


class ConfigChangedPayload(Wire):
    pages: list[Code]
    version: Int


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
    details: dict[str, list[Row]]


@dataclass(frozen=True)
class FreezeEntry:
    """一条冻结记录（C08 第 1 节）：`table` 为根表，注册过的表为所属单据主表实体的表，冻结整张单据；
    单表页和没注册的表为这一行。"""

    approval_id: str
    table: str
    record_key: str


@dataclass(frozen=True)
class TargetObject:
    """`RelatedQuery` 找到的一个对象（C08 第 9 节）。

    `missing` 为 True 表示记录已不存在：关联 SQL 查出的这一行单据主键或明细主键为空。这时 `record_key` 为查到的
    单据主键（为空时为 None），`row_keys` 为空；调用方不冻结、不更新它（approval AP-21）。
    """

    entity: str
    record_key: str | None
    row_keys: tuple[str, ...]
    display: dict[str, Value] = dc_field(hash=False)
    missing: bool


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
    skipped: list[tuple[str, str]] = dc_field(hash=False)


@dataclass(frozen=True)
class ColumnInfo:
    """数据库中的一列（db-core 的 SchemaInspector）。"""

    name: str
    data_type: str
    nullable: bool
    length: int | None
    precision: int | None
    scale: int | None


@dataclass(frozen=True)
class DbObject:
    """数据库中的一个表或视图（db-core 的 `SchemaInspector.objects`，C08 v21）。"""

    name: str
    type: Literal["table", "view"]


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

    accounts: list[ImportedAccount] = dc_field(hash=False)
    roles: list[ImportedRole] = dc_field(hash=False)
    assignments: list[RoleAssignment] = dc_field(hash=False)
    departments: list[ImportedDepartment] = dc_field(hash=False)


@dataclass(frozen=True)
class PersonalConfigEntry:
    user_id: str
    page_code: str
    config: PersonalConfig


@dataclass(frozen=True)
class PersonalConfigBatch:
    entries: list[PersonalConfigEntry] = dc_field(hash=False)


@dataclass(frozen=True)
class SqlCondition:
    """行权限的 SQL 条件：占位符已换成绑定变量名，`binds` 为绑定变量的值。"""

    sql: str
    binds: dict[str, Value] = dc_field(hash=False)


@dataclass(frozen=True)
class ApprovalFlowEntry:
    """一个审批流配置项：编码、名称和内容（C08 第 4 节 `ConfigSnapshot.approval_flow_entries`）。"""

    code: str
    name: str
    flow: ApprovalFlowConfig = dc_field(hash=False)


@dataclass(frozen=True)
class TableEntity:
    """表上注册的一个实体（C08 第 4 节 `EntityDirectory.entities_on_table`）：实体编码、所属主表实体和明细中关联主表的字段；
    实体本身是主表时 `master` 为它自己、`parent_key` 为 None。"""

    entity: str
    master: str
    parent_key: str | None


LockLayer: TypeAlias = Literal["approval", "document", "base"]
LOCK_LAYERS: tuple[LockLayer, ...] = ("approval", "document", "base")
"""业务加锁的层级，按加锁的先后（write-pipeline WP-03，用户 2026-10-30）：审批记录（PF_APPROVAL）→ 单据层（有 details 的
主表实体，例如成本核算）→ 基础数据层（其余注册实体和没注册的表，例如物料清单 T_COST_GOODS）。层级由配置自动判断。"""


@dataclass(frozen=True)
class LockTarget:
    """一个要加行锁的对象（C08 第 5b 节 `BusinessLocker`）：层级、物理表（大写）、主键列（大写）和主键文本。
    `numeric` 为 True 时主键按数值比较（主键字段或列是数值类型）。"""

    layer: LockLayer
    table: str
    key_column: str
    key: str
    numeric: bool

    def order(self) -> tuple[int, str, Decimal | str]:
        """统一的加锁顺序（WP-03）：层级 → 表名 → 主键。同一张表的主键类型相同，数值与文本不会互相比较。"""
        return LOCK_LAYERS.index(self.layer), self.table, Decimal(self.key) if self.numeric else self.key


class LockScopeChanged(Exception):
    """加锁前普通读取的本命令单据，锁住后核对时已被别人改了（write-pipeline WP-13 的例外，用户 2026-10-30 规则 4）。
    由 `BusinessLocker.lock` 抛出；编排回滚整个事务，用新的范围把整条命令重来一次，命令记录随事务重新插入。"""


PackHandle: TypeAlias = object
"""rules-core 的 load_pack 返回的句柄，对调用方不透明。"""


class PackInvalidError(Exception):
    """规则包不合法（包括 C07 第 1 节的依赖成环），由 `RulesEngine.load_pack` 抛出（C08 第 8 节）。"""

    message: str
    """原因；依赖成环时列出环上的规则。"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass
class RowChange:
    """变更计划中的一行。"""

    document: DocumentRef
    """所属单据。新增的单据在取得主键前，record_key 为主表行的 clientRowId。"""
    entity: str
    op: RowOp
    row_key: str | None
    """新增行在取得主键前为 None。"""
    client_row_id: str | None
    values: dict[str, Value]
    """新增：要写入的字段；修改：有变化的字段的新值；删除：空。"""
    old: dict[str, Value]
    """修改：这些字段的旧值；删除：删除前的整行（审计用）；新增：空。"""


@dataclass(frozen=True)
class RowIntent:
    """动作要做的一行修改，还没有和当前数据合并（C08 第 6 节）。operations 展开动作时写入 `CommandState.intents`，
    write-pipeline 对所属单据不在 `involved` 中的先加锁读取、做冻结检查，再合并（WP-18）。"""

    document: DocumentRef
    entity: str
    op: RowOp
    row_key: str | None
    client_row_id: str | None
    values: dict[str, Value] = dc_field(hash=False)
    fill_defaults: bool = True
    """新增行没有写的字段是否按 WP-16 补默认值。按钮 `replaceDetails` 新增的行为 False：只写 SQL 给出的字段、关联字段、
    主键和计算字段，其余列不写，取数据库的列默认值（旧 P_COST_BOM_INSERT）；审批通过时写入的新增行为 True
    （复制出的行除外，见 `copy_of`）。"""
    copy_of: str | None = None
    """新增行是复制出来的（C02 `copyOf`）：源行的主键。approval 展开的待审新增行带它时，`values` 是提交审批那一刻
    write-pipeline 按源行解出的值（approval AP-10）；合并时不再读源行，也不补默认值（WP-16、WP-21）。"""


@dataclass
class ChangePlan:
    """只含有变化的列的写入计划，由 write-pipeline 生成并执行。"""

    rows: list[RowChange] = dc_field(default_factory=list)


@dataclass
class CommandState:
    """管道阶段之间传递的数据；每个阶段只写 C08 第 6 节表中它负责的字段。

    除 command 外各字段在命令开始时为空；outcome 在写入命令记录前由 write-pipeline 或触发审批阶段给出。
    """

    command: Command
    involved: list[DocumentRef] = dc_field(default_factory=list)
    current: dict[DocumentRef, DocumentData] = dc_field(default_factory=dict)
    actions: list[ActionStep] = dc_field(default_factory=list)
    intents: list[RowIntent] = dc_field(default_factory=list)
    candidate: dict[DocumentRef, DocumentData] = dc_field(default_factory=dict)
    effects: list[RuleEffect] = dc_field(default_factory=list)
    changes: ChangePlan = dc_field(default_factory=ChangePlan)
    approvals: list[ApprovalState] = dc_field(default_factory=list)
    notifications: list[NotificationIntent] = dc_field(default_factory=list)
    delivery_ids: list[str] = dc_field(default_factory=list)
    prompts: list[Prompt] = dc_field(default_factory=list)
    skipped: list[SkippedRow] = dc_field(default_factory=list)
    pending_documents: set[DocumentRef] = dc_field(default_factory=set)
    escape_hatch_calls: list[dict[str, Any]] = dc_field(default_factory=list)
    """逃生舱的调用记录（OP-04）：每次调用一项，已是写进命令记录的 JSON（键为 camelCase，值按 C01 写成文本）。"""
    outcome: Outcome | None = None
    defer_lock: bool = False
    """为 True 时"加锁读取"只普通读取 `involved` 中的单据、不加锁（WP-03）：approval 在"确定涉及的单据"按配置判断触发审批
    要冻结排在本单据之前或同层的数据时设置（例如物料清单改价冻结成本单）；由"触发审批"把这些单据和要冻结的数据按统一
    顺序一次锁完并核对（AP-02）。"""
