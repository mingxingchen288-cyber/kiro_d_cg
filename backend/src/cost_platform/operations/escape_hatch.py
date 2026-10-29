"""逃生舱：登记和执行（OP-04、OP-06，C06 第 4、6 节 `escapeHatch`）。

只在用户点名时启用：登记表默认是空的，assembly 只登记用户点名启用的逃生舱；配置中引用了没有登记的逃生舱时拒绝执行。
首版配置中不启用任何逃生舱（T-OP-2）。

C06 第 4 节的逃生舱操作只有 `procedure` 和 `writes`，没有参数怎样绑定（contract-gaps.md 第 3 项）。和旧系统的
`approval-action-procedure-contracts.properties` 一样，调用方式由服务端登记：

| 登记的调用 | 对应旧系统 | 执行 |
|---|---|---|
| `ProcedureCall` | `ProcedureActionExecutor`（type=proc） | 调用存储过程，参数 IN、OUT、INOUT，可核对源码指纹 |
| `StatementCall` | `SqlActionExecutor`（type=sql） | 执行登记的一条写语句，参数用绑定变量（旧系统把值拼进 SQL） |
| `HandlerCall` | `JavaActionExecutor`（type=java） | 调用登记的 Python 函数（旧系统按 Spring Bean 名反射调用） |

执行时机：动作执行阶段中，排到这个动作时执行，这时涉及的单据已加锁、做过冻结检查；在命令的事务内执行，自身不提交
也不回滚，之后的动作失败时它的写入随命令一起回滚。每次调用记一条 `EscapeHatchCall`（逃生舱、参数、执行人、时间和
请求键），由 `ActionStage.escape_hatch_calls` 交给写命令记录的一方（contract-gaps.md 第 4 项）。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from sqlalchemy import CLOB, Date, DateTime, Numeric, String, bindparam, outparam, text

from cost_platform.contracts.decimal_text import format_decimal
from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    CommandState,
    DocumentRef,
    ErrorCode,
    ExecutionContext,
    OperationConfig,
    PlatformError,
    Prompt,
    Row,
    Value,
)

from .memory import EscapeHatchCall

ParamType = Literal["text", "number", "date", "datetime", "clob"]
ParamMode = Literal["IN", "OUT", "INOUT"]

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*(\.[A-Za-z][A-Za-z0-9_$#]*){0,2}$")
_CONTEXT = ("userId", "userName", "departmentId", "roleCode", "requestKey", "approvalId", "now", "today")


@dataclass(frozen=True)
class EscapeParam:
    """一个参数：从哪里取值（对应旧系统 `ActionParam.source`）。

    `source` 的写法：
    - `row.rowKey`、`row.字段`：选中的行（旧系统的 `data.id`、`data.字段`）；有这种参数时每个选中的行调用一次；
    - `document.recordKey`、`master.字段`：选中行所属的单据和它的主表；有这种参数时每张单据调用一次（没有选中行的
      命令，例如审批，为本命令涉及的单据）；
    - `context.userId`、`userName`、`departmentId`、`roleCode`、`requestKey`、`approvalId`、`now`、`today`：执行上下文；
    - `command.params`：命令参数整体（JSON 文本），`command.params.名称`：其中一项（旧系统审批的 `P_PARAMS_JSON`）；
    - `constant`：取 `value`。
    行和单据的值取前面动作计算后的数据（没有时为加锁读到的当前数据）。
    `mode` 为 OUT 或 INOUT 时取回输出值，记入审计（OUT 参数不取值，`source` 不用写）；`prompt` 为 True 时把输出值
    作为提示返回（旧系统前端显示 `vars.message`）。
    """

    name: str
    source: str = "constant"
    type: ParamType = "text"
    mode: ParamMode = "IN"
    value: Value = None
    prompt: bool = False

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", self.name):
            raise ValueError(f"参数名 {self.name!r} 只能是字母、数字和下划线")
        head, _, rest = self.source.partition(".")
        ok = (self.source == "constant" or self.source == "command.params"
              or head in ("row", "master") and bool(rest) or self.source == "document.recordKey"
              or head == "context" and rest in _CONTEXT or self.source.startswith("command.params.") and len(self.source) > 15)
        if not ok:
            raise ValueError(f"参数 {self.name} 的 source 写法不对：{self.source}")


@dataclass(frozen=True)
class ProcedureCall:
    """调用存储过程。`fingerprints` 为 `名称/类型`（例如 `P_COST_BOM_INSERT/PROCEDURE`）到 USER_SOURCE 源码 SHA-256 的
    对应，调用前核对，源码变了就拒绝执行（旧系统 ActionWriteGuard 的 sources）；为空时不核对。"""

    procedure: str
    params: tuple[EscapeParam, ...] = ()
    fingerprints: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _NAME.fullmatch(self.procedure):
            raise ValueError(f"存储过程名 {self.procedure!r} 不合法")

    @property
    def target(self) -> str:
        return self.procedure.upper()


@dataclass(frozen=True)
class StatementCall:
    """执行一条登记的写语句（UPDATE、DELETE、INSERT 或 MERGE），参数用绑定变量 `:参数名`，只有 IN 参数。"""

    name: str
    sql: str
    params: tuple[EscapeParam, ...] = ()

    def __post_init__(self) -> None:
        if any(p.mode != "IN" for p in self.params):
            raise ValueError("语句的参数只能是 IN")
        if ";" in self.sql.strip().rstrip(";"):
            raise ValueError("只能登记一条语句")

    @property
    def target(self) -> str:
        return self.name


@dataclass(frozen=True)
class EscapeHatchInvocation:
    """交给处理函数的一次调用：本命令的事务、执行上下文和绑定好的参数。"""

    uow: UnitOfWork
    ctx: ExecutionContext
    params: dict[str, Value]


@dataclass(frozen=True)
class HandlerCall:
    """调用登记的 Python 函数；返回值为输出（名称 → 值），没有输出时返回 None。只用 IN 参数。"""

    name: str
    handler: Callable[[EscapeHatchInvocation], Mapping[str, Value] | None]
    params: tuple[EscapeParam, ...] = ()

    @property
    def target(self) -> str:
        return self.name


EscapeCall = ProcedureCall | StatementCall | HandlerCall


@dataclass(frozen=True)
class EscapeHatchRegistration:
    """登记启用的一个逃生舱：`operation` 为配置中 `kind` 为 `escapeHatch` 的操作编码。"""

    operation: str
    call: EscapeCall


class EscapeHatchRegistry:
    """启用的逃生舱。默认是空的，只登记用户点名启用的。"""

    def __init__(self, registrations: Iterable[EscapeHatchRegistration] = ()) -> None:
        self._items: dict[str, EscapeHatchRegistration] = {}
        for registration in registrations:
            self.register(registration)

    def register(self, registration: EscapeHatchRegistration) -> None:
        if registration.operation in self._items:
            raise ValueError(f"逃生舱 {registration.operation} 已经登记过")
        self._items[registration.operation] = registration

    def get(self, operation: str) -> EscapeHatchRegistration | None:
        return self._items.get(operation)

    def __len__(self) -> int:
        return len(self._items)


@dataclass(frozen=True)
class BoundArg:
    """绑定好的一个参数。"""

    name: str
    mode: ParamMode
    type: ParamType
    value: Value


class EscapeHatchRunner(Protocol):
    """在命令的事务连接上执行登记的调用；不提交、不回滚。"""

    def call_procedure(self, uow: UnitOfWork, call: ProcedureCall, args: Sequence[BoundArg]) -> dict[str, Value]:
        """调用存储过程，返回 OUT、INOUT 参数的值。"""
        ...

    def execute_statement(self, uow: UnitOfWork, call: StatementCall, args: Sequence[BoundArg]) -> None: ...


_PLSQL_TYPES: dict[str, str] = {"text": "VARCHAR2(32767)", "number": "NUMBER", "date": "DATE", "datetime": "DATE",
                                "clob": "CLOB"}


def _sa_type(kind: ParamType) -> Any:
    return {"text": String(), "number": Numeric(asdecimal=True), "date": Date(), "datetime": DateTime(),
            "clob": CLOB()}[kind]


class SqlEscapeHatchRunner:
    """经 `UnitOfWork.connection`（SQLAlchemy）执行：存储过程用 PL/SQL 匿名块调用（Oracle），语句直接执行。

    数据库错误照常抛出 sqlalchemy 的 DBAPIError，由 db-core 的事务按 C08 第 2 节映射成平台错误码。"""

    def call_procedure(self, uow: UnitOfWork, call: ProcedureCall, args: Sequence[BoundArg]) -> dict[str, Value]:
        self._verify(uow, call)
        declare, before, actual, after, binds = [], [], [], [], []
        for i, arg in enumerate(args):
            if arg.mode == "IN":
                actual.append(f":a{i}")
                binds.append(bindparam(f"a{i}", arg.value, type_=_sa_type(arg.type)))
            elif arg.mode == "OUT":
                actual.append(f":o{i}")
                binds.append(outparam(f"o{i}", _sa_type(arg.type)))
            else:
                declare.append(f"v{i} {_PLSQL_TYPES[arg.type]};")
                before.append(f"v{i} := :a{i};")
                actual.append(f"v{i}")
                after.append(f":o{i} := v{i};")
                binds.append(bindparam(f"a{i}", arg.value, type_=_sa_type(arg.type)))
                binds.append(outparam(f"o{i}", _sa_type(arg.type)))
        invoke = f"{call.procedure}({', '.join(actual)})" if actual else call.procedure
        block = (("DECLARE " + " ".join(declare) + " ") if declare else "") + \
            "BEGIN " + " ".join([*before, f"{invoke};", *after]) + " END;"
        result = uow.connection.execute(text(block).bindparams(*binds))
        outputs = dict(result.out_parameters) if any(a.mode != "IN" for a in args) else {}
        return {arg.name: _from_db(arg.type, outputs.get(f"o{i}")) for i, arg in enumerate(args) if arg.mode != "IN"}

    def execute_statement(self, uow: UnitOfWork, call: StatementCall, args: Sequence[BoundArg]) -> None:
        statement = text(call.sql.strip().rstrip(";")).bindparams(
            *(bindparam(arg.name, arg.value, type_=_sa_type(arg.type)) for arg in args))
        uow.connection.execute(statement)

    @staticmethod
    def _verify(uow: UnitOfWork, call: ProcedureCall) -> None:
        """核对登记时的源码指纹（旧系统 ActionWriteGuard.source）：对象必须有效，源码按行号拼接后的 SHA-256 不变。"""
        for key, expected in call.fingerprints.items():
            name, _, kind = key.partition("/")
            kind = kind.replace("_", " ")
            status = uow.connection.execute(
                text("SELECT STATUS FROM USER_OBJECTS WHERE OBJECT_NAME = :n AND OBJECT_TYPE = :t"),
                {"n": name, "t": kind}).scalar()
            if status != "VALID":
                raise PlatformError(ErrorCode.VALIDATION_FAILED, f"逃生舱依赖的 {name} 不是有效对象，不能执行")
            lines = uow.connection.execute(
                text("SELECT TEXT FROM USER_SOURCE WHERE NAME = :n AND TYPE = :t ORDER BY LINE"),
                {"n": name, "t": kind}).scalars().all()
            actual = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
            if actual != expected:
                raise PlatformError(ErrorCode.VALIDATION_FAILED,
                                    f"逃生舱依赖的 {name} 源码已变化，需要重新核对写入范围后再登记")


def _from_db(kind: ParamType, value: object) -> Value:
    if value is None:
        return None
    if kind == "number" and isinstance(value, int | float) and not isinstance(value, bool):
        return Decimal(str(value))
    if kind == "clob" and hasattr(value, "read"):
        return str(value.read())  # type: ignore[union-attr]
    return value  # type: ignore[return-value]


# ---------------------------------------------------------------- 取参数值

def _convert(kind: ParamType, value: Value) -> Value:
    """把取到的值转成参数类型。"""
    if value is None:
        return None
    if kind == "number":
        if isinstance(value, Decimal):
            return value
        if isinstance(value, bool):
            return Decimal(int(value))
        return Decimal(str(value))
    if kind in ("text", "clob"):
        if isinstance(value, Decimal):
            return format_decimal(value)
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%dT%H:%M:%S")
        if isinstance(value, date):
            return value.isoformat()
        return str(value)
    if kind == "date":
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return datetime.fromisoformat(str(value))


def _json_value(value: Any) -> Value:
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, int | float):
        return Decimal(str(value))
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class Scope:
    """一次调用的范围：选中的行（`row.`）、它所属的单据（`document.`、`master.`）。"""

    document: DocumentRef | None = None
    master: Row | None = None
    row: Row | None = None


def _value(param: EscapeParam, scope: Scope, state: CommandState, ctx: ExecutionContext) -> Value:
    source = param.source
    if source == "constant":
        return param.value
    head, _, rest = source.partition(".")
    if head == "row":
        assert scope.row is not None
        return scope.row.row_key if rest == "rowKey" else scope.row.values.get(rest)
    if source == "document.recordKey":
        assert scope.document is not None
        return scope.document.record_key
    if head == "master":
        assert scope.master is not None
        return scope.master.values.get(rest)
    if head == "context":
        who = ctx.identity
        return {"userId": who.user_id, "userName": who.display_name, "departmentId": who.department_id,
                "roleCode": who.role_code, "requestKey": state.command.request_key, "approvalId": ctx.origin.approval_id,
                "now": ctx.now.replace(microsecond=0), "today": ctx.now.date()}[rest]
    params = state.command.params
    if source == "command.params":
        return json.dumps(params, ensure_ascii=False, sort_keys=True)
    return _json_value(params.get(source[len("command.params."):]))


def scopes(params: Sequence[EscapeParam], rows: Sequence[tuple[DocumentRef, Row]],
           documents: Sequence[tuple[DocumentRef, Row]]) -> list[Scope]:
    """每次调用的范围：有 `row.` 参数时每个选中的行一次；有 `document.`、`master.` 参数时每张单据一次；否则一次。"""
    sources = [p.source for p in params if p.mode != "OUT"]
    if any(s.startswith("row.") for s in sources):
        masters = dict(documents)
        return [Scope(document=ref, master=masters.get(ref), row=row) for ref, row in rows]
    if any(s.startswith(("document.", "master.")) for s in sources):
        return [Scope(document=ref, master=master) for ref, master in documents]
    return [Scope()]


class EscapeHatchExecutor:
    """执行动作 `escapeHatch`（OP-04）。"""

    def __init__(self, registry: EscapeHatchRegistry, runner: EscapeHatchRunner) -> None:
        self._registry = registry
        self._runner = runner

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext, operation_code: str,
            rows: Sequence[tuple[DocumentRef, Row]], documents: Sequence[tuple[DocumentRef, Row]]) -> list[EscapeHatchCall]:
        """`rows` 为选中的、仍存在的行和所属单据，`documents` 为单据和它计算后的主表行，都按选中的先后。

        返回本次的调用记录；OUT 参数中 `prompt` 为 True 的值写入 `state.prompts`。"""
        registration = self._registry.get(operation_code)
        if registration is None:
            raise PlatformError(ErrorCode.VALIDATION_FAILED,
                                f"逃生舱 {operation_code} 没有登记启用：逃生舱只在用户点名时启用")
        operation = ctx.config.operation(operation_code)
        self._check_config(operation_code, operation, registration.call)
        call = registration.call
        records: list[EscapeHatchCall] = []
        for scope in scopes(call.params, rows, documents):
            args = [BoundArg(p.name, p.mode, p.type,
                             None if p.mode == "OUT" else _convert(p.type, _value(p, scope, state, ctx)))
                    for p in call.params]
            outputs = self._invoke(uow, ctx, call, args)
            records.append(EscapeHatchCall(
                operation=operation_code,
                kind="procedure" if isinstance(call, ProcedureCall) else "statement" if isinstance(call, StatementCall)
                else "handler",
                target=call.target, params={a.name: a.value for a in args if a.mode != "OUT"}, outputs=outputs,
                writes={k: list(v) for k, v in operation.writes.items()}, user_id=ctx.identity.user_id,
                user_name=ctx.identity.display_name, at=ctx.now.replace(microsecond=0),
                request_key=state.command.request_key, approval_id=ctx.origin.approval_id))
            for param in call.params:
                message = outputs.get(param.name)
                if param.prompt and message not in (None, ""):
                    state.prompts.append(Prompt(rule=operation_code, message=str(message)))
        return records

    def _invoke(self, uow: UnitOfWork, ctx: ExecutionContext, call: EscapeCall, args: list[BoundArg]) -> dict[str, Value]:
        if isinstance(call, ProcedureCall):
            return self._runner.call_procedure(uow, call, args)
        if isinstance(call, StatementCall):
            self._runner.execute_statement(uow, call, args)
            return {}
        result = call.handler(EscapeHatchInvocation(uow=uow, ctx=ctx,
                                                    params={a.name: a.value for a in args if a.mode != "OUT"}))
        return dict(result or {})

    @staticmethod
    def _check_config(code: str, operation: OperationConfig, call: EscapeCall) -> None:
        """配置与登记一致：操作的 `kind` 为 `escapeHatch`；登记的是存储过程时，配置的 `procedure` 是同一个。"""
        if operation.kind != "escapeHatch":
            raise PlatformError(ErrorCode.VALIDATION_FAILED, f"操作 {code} 不是逃生舱（kind 为 {operation.kind}）")
        if isinstance(call, ProcedureCall) and (operation.procedure or "").upper() != call.procedure.upper():
            raise PlatformError(ErrorCode.VALIDATION_FAILED,
                                f"逃生舱 {code} 配置的存储过程 {operation.procedure} 与登记的 {call.procedure} 不同")
