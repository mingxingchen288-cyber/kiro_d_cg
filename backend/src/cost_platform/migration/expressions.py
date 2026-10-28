"""公式转换：Oracle 虚拟列表达式、旧前端 CALC 表达式 → C06 第 5 节的 ZEN 表达式。

两种来源先解析成语法树，再按同一套规则输出 ZEN 文本：
- 字段引用由调用方的 `Scope` 决定：本行字段直接写字段名，明细引用主表写 `master.字段`，主表汇总明细写成
  `sum(map(filter(明细实体, 条件), #.字段))`；引用不到的字段抛 `Unconvertible`。
- 新平台的取值规则（rules-core 第 8 节）：空值按 0 参与计算，除以 0 得 0，分支都不成立时保持原值。
  Oracle 的 `NVL(x, 0)` 因此直接写成 `x`；`x / CASE p WHEN 0 THEN NULL ELSE p END` 只在外层有 `NVL(…, 0)`
  时才等价于 `x / p`。其余写法（NVL 的默认值不是 0、外层没有 NVL 的除法或空值传播、嵌套 CASE 等）不能保证
  结果相同，抛 `Unconvertible`，由调用方列入人工改写清单（MG-02）。
- 虚拟列表达式中与另一个虚拟列完整表达式相同的子表达式，换成那个字段（例如 COST_BATCH 中的 BATCH_QTY）。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

Node = tuple  # 语法树节点：第一个元素是种类


class Unconvertible(Exception):
    """不能自动转换的写法；消息为中文原因。"""


# ============================================================ 输出 ZEN

_PREC = {"tern": 0, "or": 1, "and": 2, "not": 3, "cmp": 4, "+": 5, "-": 5, "*": 6, "/": 6, "neg": 7}


def _prec(node: Node) -> int:
    kind = node[0]
    if kind == "bin":
        return _PREC[node[1]]
    return _PREC.get(kind, 9)


def emit(node: Node) -> str:
    """把 ZEN 语法树输出为表达式文本，只在需要时加括号。"""
    kind = node[0]
    if kind in ("num", "ref"):
        return node[1]
    if kind == "str":
        return "'" + node[1].replace("\\", "\\\\").replace("'", "\\'") + "'"
    if kind == "null":
        return "null"
    if kind == "call":
        return f"{node[1]}({', '.join(emit(a) for a in node[2])})"
    if kind == "bin":
        op, left, right = node[1], node[2], node[3]
        p = _PREC[op]
        lt = emit(left) if _prec(left) >= p else f"({emit(left)})"
        rt = emit(right) if _prec(right) > p else f"({emit(right)})"
        return f"{lt} {op} {rt}"
    if kind == "cmp":
        return f"{_wrap(node[2], 4)} {node[1]} {_wrap(node[3], 4)}"
    if kind in ("and", "or"):
        p = _PREC[kind]
        return f" {kind} ".join(emit(x) if _prec(x) > p or x[0] == kind else f"({emit(x)})" for x in node[1])
    if kind == "not":
        return f"not {_wrap(node[1], 3)}"
    if kind == "neg":
        return f"-{_wrap(node[1], 7)}"
    if kind == "tern":
        return f"{_wrap(node[1], 0)} ? {emit(node[2])} : {emit(node[3])}"
    raise AssertionError(kind)


def _wrap(node: Node, p: int) -> str:
    return emit(node) if _prec(node) > p else f"({emit(node)})"


# ============================================================ 字段引用

@dataclass
class Scope:
    """表达式所在的实体及可以引用的字段。

    - `own`：规则所在实体的字段；
    - `master`：明细规则可以引用的主表字段（写作 `master.字段`），主表规则为空；
    - `details`：主表规则可以汇总的明细，键为明细实体编码；
    - `legacy_codes`：旧表代码（TABLE_CODE）到实体编码；
    - `substitutions`：虚拟列转换时，可以换成字段的其他虚拟列的语法树。
    """

    entity: str
    own: frozenset[str]
    master_entity: str | None = None
    master: frozenset[str] = frozenset()
    details: Mapping[str, frozenset[str]] = field(default_factory=dict)
    legacy_codes: Mapping[str, str] = field(default_factory=dict)
    substitutions: Mapping[Node, str] = field(default_factory=dict)
    master_refs: set[str] = field(default_factory=set)
    """转换中改为引用主表的列（输出到迁移报告）。"""

    def column(self, name: str) -> Node:
        """Oracle 虚拟列中的列：本实体字段，或主表同名字段。"""
        if name in self.own:
            return ("ref", name)
        if name in self.master:
            self.master_refs.add(name)
            return ("ref", f"master.{name}")
        raise Unconvertible(f"引用的列 {name} 不在实体 {self.entity} 中")


@dataclass(frozen=True)
class Converted:
    """转换结果：`expression` 与 `branches` 二选一；`dropped_else` 为去掉的兜底分支原文。"""

    expression: str | None
    branches: list[tuple[str, str]] | None
    dropped_else: str | None = None


# ============================================================ Oracle 虚拟列表达式

_ORA_TOKEN = re.compile(r"""
    \s*(?:
      (?P<num>\d+(?:\.\d+)?)
    | (?P<str>'(?:[^']|'')*')
    | "(?P<qid>[^"]+)"
    | (?P<id>[A-Za-z_][A-Za-z0-9_$#]*)
    | (?P<op><>|!=|>=|<=|[-+*/(),=<>])
    )""", re.VERBOSE)
_KEYWORDS = {"CASE", "WHEN", "THEN", "ELSE", "END", "AND", "OR", "NOT", "NULL", "IS"}


def _ora_tokens(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos, text = 0, text.strip()
    while pos < len(text):
        m = _ORA_TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise Unconvertible(f"无法解析的 Oracle 表达式：{text[pos:pos + 20]}")
        pos = m.end()
        if m.group("num") is not None:
            tokens.append(("num", m.group("num")))
        elif m.group("str") is not None:
            tokens.append(("str", m.group("str")[1:-1].replace("''", "'")))
        elif m.group("qid") is not None:
            tokens.append(("col", m.group("qid")))
        elif m.group("id") is not None:
            word = m.group("id").upper()
            tokens.append(("kw", word) if word in _KEYWORDS else ("id", word))
        else:
            tokens.append(("op", m.group("op")))
    return tokens


class _OraParser:
    def __init__(self, text: str) -> None:
        self.t = _ora_tokens(text)
        self.i = 0

    def peek(self, kind: str, value: str | None = None) -> bool:
        if self.i >= len(self.t):
            return False
        k, v = self.t[self.i]
        return k == kind and (value is None or v == value)

    def take(self, kind: str, value: str | None = None) -> str:
        if not self.peek(kind, value):
            got = self.t[self.i] if self.i < len(self.t) else ("结束", "")
            raise Unconvertible(f"Oracle 表达式在 {got[1]!r} 处不符合预期")
        self.i += 1
        return self.t[self.i - 1][1]

    def parse(self) -> Node:
        node = self.or_()
        if self.i != len(self.t):
            raise Unconvertible("Oracle 表达式末尾有多余内容")
        return node

    def or_(self) -> Node:
        items = [self.and_()]
        while self.peek("kw", "OR"):
            self.i += 1
            items.append(self.and_())
        return items[0] if len(items) == 1 else ("or", tuple(_flatten("or", items)))

    def and_(self) -> Node:
        items = [self.not_()]
        while self.peek("kw", "AND"):
            self.i += 1
            items.append(self.not_())
        return items[0] if len(items) == 1 else ("and", tuple(_flatten("and", items)))

    def not_(self) -> Node:
        if self.peek("kw", "NOT"):
            self.i += 1
            return ("not", self.not_())
        return self.cmp()

    def cmp(self) -> Node:
        left = self.add()
        if self.peek("kw", "IS"):
            self.i += 1
            negated = self.peek("kw", "NOT")
            if negated:
                self.i += 1
            self.take("kw", "NULL")
            return ("isnull", left, negated)
        for op in ("=", "<>", "!=", ">=", "<=", ">", "<"):
            if self.peek("op", op):
                self.i += 1
                return ("cmp", "!=" if op == "<>" else op, left, self.add())
        return left

    def add(self) -> Node:
        node = self.mul()
        while self.peek("op", "+") or self.peek("op", "-"):
            op = self.take("op")
            node = ("bin", op, node, self.mul())
        return node

    def mul(self) -> Node:
        node = self.unary()
        while self.peek("op", "*") or self.peek("op", "/"):
            op = self.take("op")
            node = ("bin", op, node, self.unary())
        return node

    def unary(self) -> Node:
        if self.peek("op", "-"):
            self.i += 1
            return ("neg", self.unary())
        return self.primary()

    def primary(self) -> Node:
        if self.peek("num"):
            return ("num", self.take("num"))
        if self.peek("str"):
            return ("str", self.take("str"))
        if self.peek("col"):
            return ("col", self.take("col"))
        if self.peek("kw", "NULL"):
            self.i += 1
            return ("null",)
        if self.peek("kw", "CASE"):
            return self.case()
        if self.peek("op", "("):
            self.i += 1
            node = self.or_()
            self.take("op", ")")
            return node
        name = self.take("id")
        if not self.peek("op", "("):
            return ("col", name)
        self.i += 1
        args: list[Node] = []
        if not self.peek("op", ")"):
            args.append(self.or_())
            while self.peek("op", ","):
                self.i += 1
                args.append(self.or_())
        self.take("op", ")")
        return ("fn", name, tuple(args))

    def case(self) -> Node:
        self.take("kw", "CASE")
        subject = None if self.peek("kw", "WHEN") else self.add()
        whens: list[tuple[Node, Node]] = []
        while self.peek("kw", "WHEN"):
            self.i += 1
            cond = self.or_()
            self.take("kw", "THEN")
            whens.append((cond, self.or_()))
        otherwise = None
        if self.peek("kw", "ELSE"):
            self.i += 1
            otherwise = self.or_()
        self.take("kw", "END")
        return ("case", subject, tuple(whens), otherwise)


def _flatten(kind: str, items: list[Node]) -> list[Node]:
    out: list[Node] = []
    for item in items:
        out.extend(item[1] if item[0] == kind else (item,))
    return out


def parse_oracle(text: str) -> Node:
    """解析 ALL_TAB_COLS.DATA_DEFAULT 中的虚拟列表达式。括号不产生节点，同样的表达式得到同样的树。"""
    return _OraParser(text).parse()


def oracle_columns(node: object) -> set[str]:
    """表达式引用的列。"""
    if not isinstance(node, tuple):
        return set()
    if len(node) == 2 and node[0] == "col":
        return {node[1]}
    found: set[str] = set()
    for part in node:
        found |= oracle_columns(part)
    return found


class _OraConverter:
    def __init__(self, scope: Scope, skip: Node) -> None:
        self.scope = scope
        self.skip = skip  # 目标列自己的表达式，不能换成自己

    def value(self, node: Node, nvl: bool) -> Node:
        """数值表达式。`nvl` 表示外层有 NVL(…, 0)：空值和除以空都会变成 0，与新平台的取值规则一致。"""
        if node != self.skip and node in self.scope.substitutions:
            return ("ref", self.scope.substitutions[node])
        kind = node[0]
        if kind == "num":
            return node
        if kind == "col":
            if not nvl:
                raise Unconvertible(f"列 {node[1]} 没有用 NVL(…, 0) 包住，Oracle 中为空时整个结果为空，新平台按 0 计算")
            return self.scope.column(node[1])
        if kind == "fn" and node[1] == "NVL" and len(node[2]) == 2:
            inner, default = node[2]
            if default != ("num", "0"):
                raise Unconvertible("NVL 的默认值不是 0")
            return self.value(inner, True)
        if kind == "fn" and node[1] == "CEIL" and len(node[2]) == 1:
            return ("call", "ceil", (self.value(node[2][0], nvl),))
        if kind == "bin":
            right = node[3]
            if node[1] == "/" and _is_nullif_zero(right):
                if not nvl:
                    raise Unconvertible("除数为 0 时 Oracle 结果为空，外层没有 NVL(…, 0)")
                return ("bin", "/", self.value(node[2], nvl), self.value(right[1], nvl))
            return ("bin", node[1], self.value(node[2], nvl), self.value(right, nvl))
        if kind == "neg":
            return ("neg", self.value(node[1], nvl))
        if kind == "case" and node[1] is not None and _is_nullif_zero(node):
            raise Unconvertible("CASE … WHEN 0 THEN NULL 只能作除数")
        if kind == "case":
            raise Unconvertible("嵌套的 CASE 不能转换")
        raise Unconvertible(f"不支持的写法：{kind} {node[1] if len(node) > 1 else ''}")

    def condition(self, node: Node) -> Node:
        kind = node[0]
        if kind in ("and", "or"):
            return (kind, tuple(self.condition(x) for x in node[1]))
        if kind == "not":
            return ("not", self.condition(node[1]))
        if kind == "cmp":
            left, right = node[2], node[3]
            if left[0] == "fn" and left[1] == "REGEXP_INSTR" and node[1] == ">" and right == ("num", "0"):
                return self.regexp(left)
            return ("cmp", "==" if node[1] == "=" else node[1], self.operand(left), self.operand(right))
        raise Unconvertible(f"不支持的条件写法：{kind}")

    def operand(self, node: Node) -> Node:
        if node[0] == "str":
            return node
        if node[0] == "col":
            return self.scope.column(node[1])
        return self.value(node, False)

    def regexp(self, node: Node) -> Node:
        args = node[2]
        if len(args) != 2 or args[1][0] != "str":
            raise Unconvertible("REGEXP_INSTR 只支持两个参数，第二个为文本")
        subject = args[0]
        if subject[0] == "fn" and subject[1] == "NVL" and len(subject[2]) == 2 and subject[2][1][0] == "str":
            subject = subject[2][0]  # NVL(列, ' ')：为空时不匹配任何关键字，与 matches 对空值的结果相同
        if subject[0] != "col":
            raise Unconvertible("REGEXP_INSTR 的第一个参数只支持列")
        _check_regex(args[1][1])
        return ("call", "matches", (self.scope.column(subject[1]), ("str", args[1][1])))


def _is_nullif_zero(node: Node) -> bool:
    """`CASE x WHEN 0 THEN NULL ELSE x END`。"""
    return (node[0] == "case" and node[1] is not None and len(node[2]) == 1
            and node[2][0] == (("num", "0"), ("null",)) and node[3] == node[1])


def convert_oracle(text: str, target: str, scope: Scope, others: Mapping[str, str] | None = None) -> Converted:
    """把列 `target` 的虚拟列表达式转为计算规则。

    `others` 为同一张表其他虚拟列的表达式（列名到原文）：子表达式与其中某一个完整相同时换成该字段。
    顶层是 CASE WHEN 时转为 `branches`；ELSE 只引用不在实体中的 `<target>_OLD` 时去掉，
    分支都不成立时字段保持原值（MG-12），去掉的原文放在 `dropped_else`。
    """
    tree = parse_oracle(text)
    subs = dict(scope.substitutions)
    for name, other in (others or {}).items():
        if name != target:
            subs[parse_oracle(other)] = name
    conv = _OraConverter(Scope(scope.entity, scope.own, scope.master_entity, scope.master, scope.details,
                               scope.legacy_codes, subs, scope.master_refs), tree)
    if tree[0] == "case" and tree[1] is None:
        branches = [(emit(conv.condition(c)), emit(conv.value(v, False))) for c, v in tree[2]]
        dropped = None
        if tree[3] is not None:
            cols = oracle_columns(tree[3])
            if cols and all(c == f"{target}_OLD" and c not in scope.own for c in cols):
                dropped = _oracle_text(tree[3])
            else:
                branches.append(("", emit(conv.value(tree[3], False))))
        return Converted(None, branches, dropped)
    return Converted(emit(conv.value(tree, False)), None)


def _oracle_text(node: Node) -> str:
    if node[0] == "col":
        return f'"{node[1]}"'
    if node[0] == "num":
        return node[1]
    if node[0] == "fn":
        return f"{node[1]}({', '.join(_oracle_text(a) for a in node[2])})"
    return str(node)


_UNSUPPORTED_REGEX = re.compile(r"\(\?[=!<]|\\[1-9]")


def _check_regex(pattern: str) -> None:
    """ZEN 的 matches 用 Rust regex：不支持前后断言和反向引用。"""
    if _UNSUPPORTED_REGEX.search(pattern):
        raise Unconvertible(f"正则 {pattern} 含断言或反向引用，新平台不支持")


# ============================================================ 旧前端 CALC 表达式

_JS_TOKEN = re.compile(r"""
    \s*(?:
      (?P<num>\d+(?:\.\d+)?)
    | '(?P<sq>(?:[^'\\]|\\.)*)'
    | "(?P<dq>(?:[^"\\]|\\.)*)"
    | (?P<id>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)
    | (?P<op>===|!==|==|!=|>=|<=|\|\||&&|[-+*/()?:,<>!&])
    )""", re.VERBOSE)


def _js_tokens(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos, text = 0, text.strip()
    while pos < len(text):
        m = _JS_TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise Unconvertible(f"无法解析的旧公式：{text[pos:pos + 20]}")
        pos = m.end()
        if m.group("num") is not None:
            tokens.append(("num", m.group("num")))
        elif m.group("sq") is not None:
            tokens.append(("str", m.group("sq")))
        elif m.group("dq") is not None:
            tokens.append(("str", m.group("dq")))
        elif m.group("id") is not None:
            tokens.append(("id", m.group("id")))
        else:
            tokens.append(("op", m.group("op")))
    return tokens


class _JsParser:
    """JavaScript 运算符的子集，优先级同 JavaScript：?: < || < && < & < == != < > < >= <= < + - < * / < 一元。"""

    def __init__(self, text: str) -> None:
        self.t = _js_tokens(text)
        self.i = 0

    def peek(self, kind: str, value: str | None = None) -> bool:
        if self.i >= len(self.t):
            return False
        k, v = self.t[self.i]
        return k == kind and (value is None or v == value)

    def take(self, kind: str, value: str | None = None) -> str:
        if not self.peek(kind, value):
            raise Unconvertible("旧公式不符合预期的写法")
        self.i += 1
        return self.t[self.i - 1][1]

    def parse(self) -> Node:
        node = self.tern()
        if self.i != len(self.t):
            raise Unconvertible("旧公式末尾有多余内容")
        return node

    def tern(self) -> Node:
        cond = self.or_()
        if self.peek("op", "?"):
            self.i += 1
            a = self.tern()
            self.take("op", ":")
            return ("tern", cond, a, self.tern())
        return cond

    def _chain(self, kind: str, ops: tuple[str, ...], sub: Callable[[], Node]) -> Node:
        items = [sub()]
        while any(self.peek("op", o) for o in ops):
            self.i += 1
            items.append(sub())
        return items[0] if len(items) == 1 else (kind, tuple(_flatten(kind, items)))

    def or_(self) -> Node:
        return self._chain("or", ("||",), self.and_)

    def and_(self) -> Node:
        return self._chain("and", ("&&",), self.bitand)

    def bitand(self) -> Node:
        # 旧公式中的 `&` 两边都是比较结果（true/false），按位与与逻辑与的结果相同
        return self._chain("and", ("&",), self.eq)

    def eq(self) -> Node:
        node = self.rel()
        while any(self.peek("op", o) for o in ("==", "!=", "===", "!==")):
            op = self.take("op")
            node = ("cmp", "==" if op in ("==", "===") else "!=", node, self.rel())
        return node

    def rel(self) -> Node:
        node = self.add()
        while any(self.peek("op", o) for o in (">=", "<=", ">", "<")):
            op = self.take("op")
            node = ("cmp", op, node, self.add())
        return node

    def add(self) -> Node:
        node = self.mul()
        while self.peek("op", "+") or self.peek("op", "-"):
            op = self.take("op")
            node = ("bin", op, node, self.mul())
        return node

    def mul(self) -> Node:
        node = self.unary()
        while self.peek("op", "*") or self.peek("op", "/"):
            op = self.take("op")
            node = ("bin", op, node, self.unary())
        return node

    def unary(self) -> Node:
        if self.peek("op", "-"):
            self.i += 1
            return ("neg", self.unary())
        if self.peek("op", "!"):
            self.i += 1
            return ("not", self.unary())
        return self.primary()

    def primary(self) -> Node:
        if self.peek("num"):
            return ("num", self.take("num"))
        if self.peek("str"):
            return ("str", self.take("str"))
        if self.peek("op", "("):
            self.i += 1
            node = self.tern()
            self.take("op", ")")
            return node
        name = self.take("id")
        if name == "null":
            return ("null",)
        if not self.peek("op", "("):
            return ("id", name)
        self.i += 1
        args: list[Node] = []
        if not self.peek("op", ")"):
            args.append(self.tern())
            while self.peek("op", ","):
                self.i += 1
                args.append(self.tern())
        self.take("op", ")")
        return ("fn", name, tuple(args))


class _JsConverter:
    def __init__(self, scope: Scope) -> None:
        self.scope = scope

    def ref(self, name: str, row: str | None) -> Node:
        """`row` 为汇总条件中当前明细的实体编码：其字段写成 `#.字段`。"""
        if "." in name:
            code, fld = name.split(".", 1)
            entity = self.scope.legacy_codes.get(code)
            if entity is None:
                raise Unconvertible(f"旧公式引用了未知的表 {code}")
        else:
            entity, fld = (row or self.scope.entity), name
        if row is not None and entity == row:
            if fld not in self.scope.details[row]:
                raise Unconvertible(f"引用的字段 {fld} 不在实体 {row} 中")
            return ("ref", f"#.{fld}")
        if entity == self.scope.entity:
            if fld not in self.scope.own:
                raise Unconvertible(f"引用的字段 {fld} 不在实体 {entity} 中")
            return ("ref", fld)
        if entity == self.scope.master_entity:
            if fld not in self.scope.master:
                raise Unconvertible(f"引用的字段 {fld} 不在实体 {entity} 中")
            return ("ref", f"master.{fld}")
        raise Unconvertible(f"明细 {entity} 的字段只能在汇总函数中引用")

    def node(self, n: Node, row: str | None = None) -> Node:
        kind = n[0]
        if kind in ("num", "str", "null"):
            return n
        if kind == "id":
            return self.ref(n[1], row)
        if kind in ("and", "or"):
            return (kind, tuple(self.node(x, row) for x in n[1]))
        if kind in ("not", "neg"):
            return (kind, self.node(n[1], row))
        if kind == "cmp":
            return ("cmp", n[1], self.node(n[2], row), self.node(n[3], row))
        if kind == "bin":
            return ("bin", n[1], self.node(n[2], row), self.node(n[3], row))
        if kind == "tern":
            return ("tern", self.node(n[1], row), self.node(n[2], row), self.node(n[3], row))
        if kind == "fn" and n[1] == "ceil" and len(n[2]) == 1:
            return ("call", "ceil", (self.node(n[2][0], row),))
        if kind == "fn" and n[1] == "SUM_IF" and len(n[2]) == 2 and row is None:
            return self.sum_if(n[2][0], n[2][1])
        raise Unconvertible(f"旧公式中的函数 {n[1] if kind == 'fn' else kind} 不能转换")

    def sum_if(self, target: Node, condition: Node) -> Node:
        if target[0] != "str" or condition[0] != "str" or "." not in target[1]:
            raise Unconvertible("SUM_IF 的参数应为 '表.字段' 和条件文本")
        code, fld = target[1].split(".", 1)
        entity = self.scope.legacy_codes.get(code)
        if entity not in self.scope.details:
            raise Unconvertible(f"SUM_IF 汇总的 {code} 不是本表的明细")
        if fld not in self.scope.details[entity]:
            raise Unconvertible(f"引用的字段 {fld} 不在实体 {entity} 中")
        cond = self.node(_JsParser(condition[1]).parse(), entity)
        rows = ("call", "filter", (("ref", entity), cond))
        return ("call", "sum", (("call", "map", (rows, ("ref", f"#.{fld}"))),))


def convert_legacy_calc(rule: Mapping[str, object], scope: Scope) -> Converted:
    """旧前端 CALC 的一项：`expression`，或 `formulaField` 加 `formulas`（按物料名等字段的正则分支）。"""
    conv = _JsConverter(scope)
    if "formulas" in rule:
        subject = conv.node(("id", str(rule["formulaField"])))
        formulas = rule["formulas"]
        assert isinstance(formulas, dict)
        branches: list[tuple[str, str]] = []
        for key in sorted(formulas, key=lambda k: int(k.rsplit("_", 1)[-1])):
            item = formulas[key]
            if item.get("matchType") != "regex":
                raise Unconvertible(f"分支匹配方式 {item.get('matchType')} 不能转换")
            _check_regex(item["key"])
            when = emit(("call", "matches", (subject, ("str", item["key"]))))
            branches.append((when, emit(conv.node(_JsParser(item["expression"]).parse()))))
        return Converted(None, branches)
    return Converted(emit(conv.node(_JsParser(str(rule["expression"])).parse())), None)
