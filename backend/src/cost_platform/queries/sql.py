"""查询共用的 SQL 部件：读取来源、绑定变量、AG Grid 筛选模型和高级查询到 SQL 条件、分页子句、值的转换。

条件中的值一律用绑定变量（T-QE-1）；字段名只能是实体中已有、对当前角色可见的字段（QE-02），列名取自实体配置。
运算符与旧系统 `DynamicDataService.buildConditionClause` 相同：文本列用 `UPPER(列)` 与大写的值比较，不区分大小写；
`eq`、`ne` 的值为空时为 `IS NULL`、`IS NOT NULL`；其他运算符的值为空时忽略这一条件。

分页子句按连接的方言生成：Oracle 用 `OFFSET … FETCH NEXT … ROWS ONLY`；其他方言（只有 contracts 的 SQLite 替代事务，
用于模拟验证）用 `LIMIT … OFFSET`。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from cost_platform.contracts.decimal_text import format_decimal
from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    AdvancedCondition,
    AdvancedQuery,
    BusinessValue,
    CompareResult,
    DataRow,
    EntityConfig,
    EntityField,
    ErrorCode,
    ErrorDetail,
    FrozenMark,
    PlatformError,
    SortItem,
    SqlCondition,
    Value,
)
from cost_platform.contracts.values import from_db, from_wire, to_wire

IN_BATCH = 1000
"""Oracle 的 IN 列表最多 1000 项：按键查询时每批的键数（QE-10）。"""


# ---------------------------------------------------------------- 读取来源

@dataclass(frozen=True)
class Source:
    """实体的读取来源（QE-03）：有 readView 时读视图，列名为字段名；否则读表，列名为字段的 `column`，
    `column` 为空的字段只存在于视图中，读表时没有。"""

    code: str
    entity: EntityConfig
    name: str
    columns: dict[str, str]
    fields: dict[str, EntityField]

    @classmethod
    def of(cls, code: str, entity: EntityConfig) -> Source:
        if entity.read_view:
            columns = {f.name: f.name for f in entity.fields}
            name = entity.read_view
        else:
            columns = {f.name: str(f.column) for f in entity.fields if f.column}
            name = entity.table
        return cls(code=code, entity=entity, name=name, columns=columns,
                   fields={f.name: f for f in entity.fields if f.name in columns})

    @property
    def pk(self) -> EntityField:
        return self.fields[self.entity.primary_key]

    def column(self, field: str, alias: str | None = None) -> str:
        column = self.columns[field]
        return f"{alias}.{column}" if alias else column

    def select_list(self, alias: str) -> str:
        return ", ".join(f"{alias}.{c}" for c in self.columns.values())

    def ordered(self) -> list[EntityField]:
        """与 `select_list` 的列顺序相同的字段。"""
        return list(self.fields.values())

    def key(self, text: str) -> Value:
        """主键文本转成绑定值；格式不对时为 400。"""
        return parse_key(self.pk, text)


def parse_key(field: EntityField, text: str) -> Value:
    try:
        return from_wire(field.type, text)
    except ValueError:
        raise PlatformError(ErrorCode.INVALID_REQUEST, f"主键 {text} 的格式不对") from None


# ---------------------------------------------------------------- 方言

def dialect(uow: UnitOfWork) -> str:
    return str(uow.connection.dialect.name)


def page_clause(dialect_name: str) -> str:
    """分页：绑定变量 `qe_offset`（跳过的行数）和 `qe_limit`（行数）。"""
    if dialect_name == "oracle":
        return "OFFSET :qe_offset ROWS FETCH NEXT :qe_limit ROWS ONLY"
    return "LIMIT :qe_limit OFFSET :qe_offset"


def as_text(dialect_name: str, expr: str) -> str:
    """把列转成文本再比较（LIKE 用于非文本列、Lookup 的关键字）。"""
    return f"TO_CHAR({expr})" if dialect_name == "oracle" else f"CAST({expr} AS TEXT)"


def row_number(dialect_name: str) -> str:
    """查询结果的行号，用来在外层保持内层查询的顺序（导出）。"""
    return "ROWNUM" if dialect_name == "oracle" else "ROW_NUMBER() OVER ()"


def page_binds(start_row: int, end_row: int) -> dict[str, int]:
    """C09 第 1 节：`startRow` 含、`endRow` 不含。"""
    return {"qe_offset": start_row, "qe_limit": max(end_row - start_row, 0)}


# ---------------------------------------------------------------- 值

def db_value(raw: object) -> Value:
    """数据库读出的、没有字段类型的值（关联 SQL、Lookup、导出 SQL 的结果）：整数转 Decimal，LOB 读出文本；
    浮点只会出现在 contracts 的 SQLite 替代事务中（表达式的结果），按文本转成 Decimal。"""
    if raw is None or isinstance(raw, (bool, str, Decimal, datetime, date)):
        return raw
    if isinstance(raw, int):
        return Decimal(raw)
    if isinstance(raw, float):
        return Decimal(str(raw))
    read = getattr(raw, "read", None)
    if callable(read):
        return str(read())
    return str(raw)


def number(raw: object) -> Decimal | None:
    value = db_value(raw)
    return value if isinstance(value, Decimal) else None


def key_text(value: Value | object) -> str:
    """键值转成文本：数值为十进制文本（Decimal 115、整数 115 都是 "115"），其余为 str。"""
    value = db_value(value)
    if isinstance(value, Decimal):
        return format_decimal(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def wire_text(raw: object) -> BusinessValue:
    """没有字段类型的值转成 JSON 中的值（Lookup 的结果）：数值为十进制文本，日期时间按 C01 第 4 节。"""
    value = db_value(raw)
    if value is None or isinstance(value, bool):
        return value
    return key_text(value)


def row_values(fields: Sequence[EntityField], record: Iterable[object]) -> dict[str, Value]:
    """一行数据库值转成后端内部的值（C08 第 1 节），按字段类型。"""
    return {f.name: _field_value(f, raw) for f, raw in zip(fields, record, strict=True)}


def _field_value(field: EntityField, raw: object) -> Value:
    value = from_db(field.type, raw)
    if field.type == "number" and isinstance(value, float):
        return Decimal(str(value))  # 只在 SQLite 替代事务中出现
    if field.type == "text" and value is not None and not isinstance(value, str):
        return key_text(value)
    return value


def to_data_row(source: Source, values: Mapping[str, Value], frozen: FrozenMark | None,
                compare: dict[str, CompareResult] | None = None) -> DataRow:
    """C09 的 DataRow：实体的全部字段（QE-02），被冻结时带冻结它的审批（QE-05），配置了对比时带对比结果（QE-10）。"""
    wire = {name: to_wire(source.fields[name].type, value) for name, value in values.items()}
    return DataRow(row_key=key_text(values[source.entity.primary_key]), values=wire, frozen=frozen, compare=compare)


class Columns:
    """按列名取查询结果中的列。SQLAlchemy 的 Oracle 方言把不区分大小写的列名（例如 `DOC_ID`）转成小写，
    带引号的列名（例如 `"Summary ID"`）保持原样；这里按原名、小写、不区分大小写依次查找。"""

    def __init__(self, keys: Iterable[str]) -> None:
        self.keys = list(keys)
        self._exact = {k: i for i, k in enumerate(self.keys)}
        self._folded: dict[str, int] = {}
        for i, k in enumerate(self.keys):
            self._folded.setdefault(k.casefold(), i)

    def index(self, name: str) -> int | None:
        for candidate in (name, name.lower()):
            if candidate in self._exact:
                return self._exact[candidate]
        return self._folded.get(name.casefold())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.index(name) is not None


# ---------------------------------------------------------------- 绑定变量

class Binds:
    """一条语句的绑定变量：自己生成的名字带 `qe_b` 前缀，行权限条件的绑定变量按 authz 给出的名字原样合并。"""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self._next = 0

    def add(self, value: object) -> str:
        name = f"qe_b{self._next}"
        self._next += 1
        self.values[name] = value
        return f":{name}"

    def merge(self, binds: Mapping[str, object]) -> None:
        self.values.update(binds)


# ---------------------------------------------------------------- 条件

def _invalid(entity: str, field: str, message: str) -> PlatformError:
    return PlatformError(ErrorCode.VALIDATION_FAILED, message, [ErrorDetail(entity=entity, field=field, message=message)])


@dataclass(frozen=True)
class Scope:
    """条件的作用范围：读取来源、SQL 中的别名、可以用来查询的字段（对当前角色可见且在来源中有列）。"""

    source: Source
    alias: str
    allowed: frozenset[str]

    @classmethod
    def of(cls, source: Source, alias: str, visible: Iterable[str]) -> Scope:
        return cls(source=source, alias=alias, allowed=frozenset(f for f in visible if f in source.columns))

    def field(self, name: str) -> EntityField:
        """QE-02：引用不可见或不存在的字段时为 422。"""
        if name not in self.allowed:
            raise _invalid(self.source.code, name, f"不能按 {name} 查询或排序：字段不存在或不可见")
        return self.source.fields[name]

    def column(self, name: str) -> str:
        return self.source.column(name, self.alias)


_SYMBOLS = {"=": "eq", "==": "eq", "<>": "ne", "!=": "ne", ">": "gt", ">=": "ge", "<": "lt", "<=": "le"}
_COMPARE = {"gt": ">", "ge": ">=", "lt": "<", "le": "<="}
_LIKE = {"like": ("%", "%", False), "notLike": ("%", "%", True), "likeLeft": ("", "%", False), "likeRight": ("%", "", False)}
_NULLARY = {"isNull", "isNotNull"}
_OPERATORS = {"eq", "ne", *_COMPARE, *_LIKE, "between", "notBetween", "in", "notIn", *_NULLARY}


def escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_TRUE_TEXT = {"1", "true", "y", "yes", "是"}


class Conditions:
    """把单个条件转成 SQL：值用绑定变量，按字段类型转换。"""

    def __init__(self, binds: Binds, dialect_name: str) -> None:
        self.binds = binds
        self.dialect = dialect_name

    def value(self, scope: Scope, field: EntityField, raw: Any) -> object:
        """请求中的值按字段类型转成绑定值；格式不对时为 422。"""
        try:
            if field.type == "number":
                if isinstance(raw, bool):
                    raise ValueError(raw)
                return Decimal(str(raw).strip())
            if field.type == "boolean":
                if isinstance(raw, bool):
                    return 1 if raw else 0
                if isinstance(raw, (int, float, Decimal)):
                    return 1 if raw else 0
                return 1 if str(raw).strip().lower() in _TRUE_TEXT else 0
            if field.type == "date":
                return date.fromisoformat(str(raw).strip()[:10])
            if field.type == "datetime":
                text = str(raw).strip().replace("T", " ")
                return datetime.strptime(text, "%Y-%m-%d %H:%M:%S") if len(text) > 10 else datetime.fromisoformat(text)
        except (ValueError, InvalidOperation):
            raise _invalid(scope.source.code, field.name, f"{field.name} 的值 {raw!r} 格式不对") from None
        return str(raw)

    def build(self, scope: Scope, name: str, operator: str, value: Any, value2: Any = None) -> str | None:
        """一个条件；值为空而运算符需要值时返回 None，表示忽略这一条件（与旧系统相同）。"""
        field = scope.field(name)
        op = _SYMBOLS.get(operator, operator)
        if op not in _OPERATORS:
            raise _invalid(scope.source.code, name, f"不支持的运算符 {operator}")
        column = scope.column(name)
        text_field = field.type == "text"
        compared = f"UPPER({column})" if text_field else column

        def bind(raw: Any) -> str:
            converted = self.value(scope, field, raw)
            return self.binds.add(converted.upper() if text_field and isinstance(converted, str) else converted)

        if op in _NULLARY:
            return f"{column} IS NULL" if op == "isNull" else f"{column} IS NOT NULL"
        if op in ("eq", "ne"):
            if value is None:
                return f"{column} IS NULL" if op == "eq" else f"{column} IS NOT NULL"
            return f"{compared} {'=' if op == 'eq' else '<>'} {bind(value)}"
        if value is None or value == "":
            return None
        if op in _COMPARE:
            return f"{column} {_COMPARE[op]} {bind(value)}"
        if op in _LIKE:
            before, after, negate = _LIKE[op]
            text = str(value).upper() if text_field else str(value)
            target = compared if text_field else as_text(self.dialect, column)
            pattern = self.binds.add(f"{before}{escape_like(text)}{after}")
            return f"{target} {'NOT LIKE' if negate else 'LIKE'} {pattern} ESCAPE '\\'"
        if op in ("between", "notBetween"):
            low, high = (value[0], value[1]) if isinstance(value, list) and value2 is None else (value, value2)
            if low is None or high is None or low == "" or high == "":
                return None
            return f"{column} {'NOT BETWEEN' if op == 'notBetween' else 'BETWEEN'} {bind(low)} AND {bind(high)}"
        items = [v for v in (value if isinstance(value, list) else [value]) if v is not None and v != ""]
        if not items:
            return None
        return f"{compared} {'NOT IN' if op == 'notIn' else 'IN'} ({', '.join(bind(v) for v in items)})"


# ---- AG Grid 筛选模型（旧前端 grid-filter-conditions.ts 的对应关系）

_TEXT_TYPES = {"contains": "like", "notContains": "notLike", "startsWith": "likeLeft", "endsWith": "likeRight",
               "equals": "eq", "notEqual": "ne", "blank": "isNull", "notBlank": "isNotNull"}
_NUMBER_TYPES = {"equals": "eq", "notEqual": "ne", "lessThan": "lt", "lessThanOrEqual": "le", "greaterThan": "gt",
                 "greaterThanOrEqual": "ge", "inRange": "between", "blank": "isNull", "notBlank": "isNotNull"}
_DATE_TYPES = {"equals": "eq", "notEqual": "ne", "lessThan": "lt", "greaterThan": "gt", "inRange": "between",
               "blank": "isNull", "notBlank": "isNotNull"}


def filter_model_sql(conditions: Conditions, scope: Scope, model: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """AG Grid 服务端行模型的 filterModel：每列一个条件，各列之间为且。"""
    clauses = []
    for col_id, item in model.items():
        clause = _filter_item(conditions, scope, col_id, item)
        if clause:
            clauses.append(clause)
    return clauses


def _filter_item(conditions: Conditions, scope: Scope, col_id: str, item: Mapping[str, Any]) -> str | None:
    scope.field(col_id)
    combined = item.get("conditions")
    if combined is None and ("condition1" in item or "condition2" in item):
        combined = [c for c in (item.get("condition1"), item.get("condition2")) if c]
    if item.get("operator") and combined:
        parts = [_filter_item(conditions, scope, col_id, {"filterType": item.get("filterType"), **c}) for c in combined]
        parts = [p for p in parts if p]
        joiner = " OR " if str(item["operator"]).upper() == "OR" else " AND "
        return f"({joiner.join(parts)})" if parts else None
    kind = item.get("filterType")
    if kind == "set":
        return conditions.build(scope, col_id, "in", list(item.get("values") or []))
    kind_types = {"text": _TEXT_TYPES, "number": _NUMBER_TYPES, "date": _DATE_TYPES}.get(str(kind))
    op = kind_types.get(str(item.get("type"))) if kind_types else None
    if op is None:
        raise _invalid(scope.source.code, col_id, f"不支持的筛选 {kind}/{item.get('type')}")
    if kind == "date":
        value, value2 = item.get("dateFrom"), item.get("dateTo")
    else:
        value, value2 = item.get("filter"), item.get("filterTo")
    if op not in _NULLARY and (value is None or value == ""):
        return None
    return conditions.build(scope, col_id, op, value, value2)


# ---- 高级查询（C09 第 4 节、QE-12）

def advanced_sql(conditions: Conditions, query: AdvancedQuery, master: Scope, details: Mapping[str, tuple[Scope, str]],
                 master_pk: str) -> list[str]:
    """高级查询：不写 `entity` 的条件属于主表；写了明细实体的，同一明细实体的条件合成一个 EXISTS，由同一条明细行
    满足；`group` 相同的条件按各自的 `logic` 连接成一组；同一范围内的条件和组按 `op` 连接；主表与各明细之间为且。

    `details` 为页面上的明细：实体编码 ->（范围，明细中关联主表的字段）。
    """
    by_scope: dict[str | None, list[AdvancedCondition]] = {}
    for item in query.conditions:
        entity = None if item.entity in (None, master.source.code) else item.entity
        if entity is not None and entity not in details:
            raise _invalid(str(entity), item.field, f"页面上没有明细 {entity}")
        by_scope.setdefault(entity, []).append(item)
    joiner = f" {query.op.upper()} "
    clauses = []
    for entity, items in by_scope.items():
        scope = master if entity is None else details[entity][0]
        expr = _combine(conditions, scope, items, joiner)
        if not expr:
            continue
        if entity is None:
            clauses.append(expr)
        else:
            detail_scope, parent_key = details[entity]
            clauses.append(f"EXISTS (SELECT 1 FROM {detail_scope.source.name} {detail_scope.alias} "
                           f"WHERE {detail_scope.column(parent_key)} = {master_pk} AND {expr})")
    return clauses


def _combine(conditions: Conditions, scope: Scope, items: list[AdvancedCondition], joiner: str) -> str | None:
    parts: list[str] = []
    groups: dict[str, list[tuple[str, str]]] = {}
    order: list[tuple[str, str | None]] = []
    for item in items:
        clause = conditions.build(scope, item.field, item.operator, item.value)
        if item.group is None:
            if clause:
                order.append(("one", clause))
            continue
        if item.group not in groups:
            groups[item.group] = []
            order.append(("group", item.group))
        if clause:
            groups[item.group].append(((item.logic or "and").upper(), clause))
    for kind, value in order:
        if kind == "one":
            parts.append(str(value))
            continue
        members = groups[str(value)]
        if members:
            text = members[0][1]
            for logic, clause in members[1:]:
                text += f" {'OR' if logic == 'OR' else 'AND'} {clause}"
            parts.append(f"({text})")
    if not parts:
        return None
    return f"({joiner.join(parts)})" if len(parts) > 1 else parts[0]


def order_sql(scope: Scope, sort_model: Sequence[SortItem]) -> str:
    """QE-04：按排序模型排序，最后按主键排序，排序值相同时分页稳定；没有排序时按主键。主键的方向与最后一个排序项相同
    （旧系统 buildOrderClause 只有一个排序项，主键与它同向）。"""
    parts = [f"{scope.column(scope.field(item.col_id).name)} {item.sort.upper()}" for item in sort_model]
    direction = sort_model[-1].sort.upper() if sort_model else "ASC"
    parts.append(f"{scope.source.column(scope.source.entity.primary_key, scope.alias)} {direction}")
    return ", ".join(parts)


def row_condition_sql(condition: SqlCondition | None, binds: Binds) -> list[str]:
    """QE-01：行权限条件与其他条件用 AND 组合。"""
    if condition is None:
        return []
    binds.merge(condition.binds)
    return [f"({condition.sql})"]


def where_sql(clauses: Sequence[str]) -> str:
    return f" WHERE {' AND '.join(clauses)}" if clauses else ""


def batches(values: Sequence[Any], size: int = IN_BATCH) -> Iterable[Sequence[Any]]:
    for i in range(0, len(values), size):
        yield values[i:i + size]
