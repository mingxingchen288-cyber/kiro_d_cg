"""规则包中保存时执行的规则读取哪些字段（C08 第 4 节 `ConfigSnapshot.rule_fields`，WP-08）。

用户 2026-10-29 选定：保存时只有改到规则用到的字段才读明细、求值；改备注这类字段直接写入，其他列不变。

保存时执行的是实体层、操作层的计算和校验规则（C07 第 2 节 commit 阶段，界面规则只在前端预览）。对每条这样的规则，扫描它
JDM 表达式节点中的全部表达式（写法同 rules-core `core/src/scan.rs`：跳过字符串，函数名和关键字不算），按名称链归到实体：
- `X`：规则作用的实体的字段 X；是业务对象中某个实体的编码时，表示这个明细的全部行（新增、删除行总会求值，不另记）；
- `master.X`：主表实体的字段 X；`old.X`：规则作用的实体的字段 X；
- `#.X`：同一表达式中出现的明细实体的字段 X（例如 `sum(map(filter(COST_MATERIAL, …), #.COST_BATCH))`）；
- `context.*`、`data.*`、`$` 开头的不是字段。
宁多勿少：多记一个字段只会多求值一次，少记会漏算。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

_KEYWORDS = {"true", "false", "null", "and", "or", "not", "in"}
_NOT_FIELDS = {"context", "data"}
_COMMIT_LAYERS = {"entity", "operation"}
_COMMIT_CATEGORIES = {"calc", "validate"}


def _ident_start(c: str) -> bool:
    return c.isascii() and (c.isalpha() or c in "_$#")


def _ident_char(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c == "_")


def name_chains(expression: str) -> list[list[str]]:
    """表达式中出现的名称链，例如 `master.APEX_PL` 为 `["master", "APEX_PL"]`；函数名、关键字和字符串中的内容不算。"""
    chains: list[list[str]] = []
    i, n = 0, len(expression)
    while i < n:
        c = expression[i]
        if c in "'\"`":
            # ZEN 的字符串没有转义：到下一个同样的引号为止
            i += 1
            while i < n and expression[i] != c:
                i += 1
            i += 1
        elif c.isascii() and c.isdigit():
            while i < n and (expression[i].isdigit() or expression[i] in "._"):
                i += 1
        elif _ident_start(c):
            chain: list[str] = []
            while True:
                start = i
                i += 1
                while i < n and _ident_char(expression[i]):
                    i += 1
                chain.append(expression[start:i])
                if i + 1 < n and expression[i] == "." and _ident_start(expression[i + 1]):
                    i += 1
                    continue
                break
            j = i
            while j < n and expression[j].isspace():
                j += 1
            is_call = j < n and expression[j] == "("
            if not is_call and not (len(chain) == 1 and chain[0] in _KEYWORDS):
                chains.append(chain)
        else:
            i += 1
    return chains


def _expressions(graph: Mapping[str, Any]) -> Iterable[str]:
    for node in graph.get("nodes", []):
        if node.get("type") == "expressionNode":
            for item in node.get("content", {}).get("expressions", []):
                value = item.get("value")
                if isinstance(value, str):
                    yield value


def rule_fields(pack: Mapping[str, Any]) -> dict[str, frozenset[str]]:
    """规则包（C07 第 1 节的 JSON）中保存时执行的规则读取的字段，键为实体编码。"""
    master = str(pack.get("packId", ""))
    entities = set(pack.get("fields", {}))
    graphs = pack.get("jdm", {})
    found: dict[str, set[str]] = {}
    for rule in pack.get("rules", []):
        if rule.get("layer") not in _COMMIT_LAYERS or rule.get("category") not in _COMMIT_CATEGORIES:
            continue
        own = rule.get("entity") or master
        for expression in _expressions(graphs.get(rule.get("jdm"), {})):
            chains = name_chains(expression)
            details = [c[0] for c in chains if len(c) == 1 and c[0] in entities and c[0] != own]
            for chain in chains:
                head = chain[0]
                if head in _NOT_FIELDS or head.startswith("$"):
                    continue
                if len(chain) == 1:
                    if head not in entities:
                        found.setdefault(own, set()).add(head)
                elif head == "master":
                    found.setdefault(master, set()).add(chain[1])
                elif head == "old":
                    found.setdefault(own, set()).add(chain[1])
                elif head == "#":
                    for detail in details or [own]:
                        found.setdefault(detail, set()).add(chain[1])
    return {entity: frozenset(names) for entity, names in found.items()}
