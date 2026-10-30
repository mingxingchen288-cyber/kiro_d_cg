"""规则的条件和表达式（C06 第 5 节）转成 ZEN 表达式文本（C07 第 1 节、rules-core README 第 2 节）。

- 可视化条件：每项 `source`（`row` 本行、`master` 主表）、`field`、`op`、`value`，按 `logic` 用 and、or 连接。
- 计算规则：只有 `expression` 时就是它；有 `when` 时为 `(when) ? (expression) : 字段`；`branches` 按顺序取第一个成立的分支，
  `(w1) ? (e1) : ((w2) ? (e2) : 字段)`，都不成立时字段不变。写法与 `rules-core/fixtures/gen_packs.py` 的 `calc_expression` 相同。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from cost_platform.contracts.types import Branch, Condition, RuleConditionItem, RuleConfig, VisualCondition

FieldType = Callable[[str, str], str | None]
"""（`row` 或 `master`，字段名）→ 字段类型（C06 的 `type`），没有这个字段时为 None。"""

_OPS = {"eq": "==", "ne": "!=", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}


def _string(value: str) -> str:
    """ZEN 的字符串常量没有转义，到下一个同样的引号为止（zen-expression 2.1.6）：含单引号时用双引号。"""
    return f'"{value}"' if "'" in value else f"'{value}'"


def _literal(value: Any, field_type: str | None) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if field_type == "number":
        try:
            Decimal(text)
            return text
        except InvalidOperation:
            pass
    if field_type == "boolean" and text in ("true", "false"):
        return text
    return _string(text)


def _like_regex(pattern: str) -> str:
    """SQL 的 like 写法（`%` 任意多个字符，`_` 一个字符）转成正则；没有通配符时按包含处理（与旧系统相同）。"""
    if "%" not in pattern and "_" not in pattern:
        return re.escape(pattern)
    body = "".join(".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern)
    return f"^{body}$"


def _item(item: RuleConditionItem, field_type: FieldType) -> str:
    name = item.field if item.source == "row" else f"master.{item.field}"
    kind = field_type(item.source, item.field)
    if item.op in _OPS:
        return f"{name} {_OPS[item.op]} {_literal(item.value, kind)}"
    if item.op == "isNull":
        return f"{name} == null"
    if item.op == "isNotNull":
        return f"{name} != null"
    if item.op == "in":
        values = item.value if isinstance(item.value, list) else [item.value]
        return f"{name} in [{', '.join(_literal(v, kind) for v in values)}]"
    # like
    return f"matches({name}, {_string(_like_regex(str(item.value or '')))})"


def condition_text(condition: Condition | None, field_type: FieldType) -> str | None:
    """条件转成表达式文本；为空表示总是成立，返回 None。"""
    if condition is None:
        return None
    if isinstance(condition, str):
        return condition
    if not condition.conditions:
        return None
    joiner = " and " if condition.logic == "AND" else " or "
    return joiner.join(f"({_item(c, field_type)})" for c in condition.conditions)


def visual_fields(condition: Condition | None) -> list[RuleConditionItem]:
    return list(condition.conditions) if isinstance(condition, VisualCondition) else []


def calc_expression(rule: RuleConfig, field_type: FieldType) -> str:
    """计算规则的表达式（C07 第 1 节）。"""
    field = rule.field or ""
    if rule.branches:
        expression = field
        for branch in reversed(rule.branches):
            expression = _branch(branch, expression, field_type)
        return expression
    when = condition_text(rule.when, field_type)
    if when is not None:
        return f"({when}) ? ({rule.expression}) : ({field})"
    return rule.expression or field


def _branch(branch: Branch, otherwise: str, field_type: FieldType) -> str:
    when = condition_text(branch.when, field_type)
    if when is None:
        return f"({branch.expression})"
    return f"({when}) ? ({branch.expression}) : ({otherwise})"


def literal_text(value: str) -> str:
    """字符串常量（规则包中校验规则的提示文字等）。"""
    return _string(value)
