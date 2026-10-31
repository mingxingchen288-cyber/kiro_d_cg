"""按业务对象生成规则包（C07 第 1 节、CF-11）。

业务对象是页面的主表实体及其明细实体，`packId` 为主表实体编码。包含的规则：
- `layer` 为 `entity`：`target` 是这个业务对象中的实体；
- `layer` 为 `operation`：`target` 是这个业务对象的页面保存或区域按钮引用的操作；
- `layer` 为 `page`：`target` 是主表实体为它的页面。
`operation`、`page` 层的规则作用在哪个实体上：`field` 属于主表实体时为主表，否则为含有这个字段的明细；`field` 为空时为主表
（C06 第 5 节没有给出这两层规则的实体，见 contract-gaps）。

JDM 的写法（rules-core README 第 2 节，与 `rules-core/fixtures/gen_packs.py` 相同）：输入 → 表达式 → 输出。
- 计算规则：表达式节点只有一个表达式，`key` 是作用的字段，`value` 是 `expressions.calc_expression` 的结果。
- 校验、界面规则（rules-core README 第 2 节）：表达式节点依次为 `matched`（条件，为空时 `true`）、`field`（作用的字段，
  字符串常量；为空时不写，界面规则作用于整行）；校验规则另有 `level`、`message`（字符串常量）；界面规则另有 `effect` 中写了的
  `editable`、`required`（true/false）和 `rowStyle`、`cellStyle`（样式的 JSON 文本作字符串常量）。
"""

from __future__ import annotations

import json
from typing import Any

from cost_platform.contracts.types import (
    JdmGraph,
    PackField,
    PackRule,
    RuleConfig,
    RulesPack,
    dump_wire,
)

from .catalog import Catalog
from .expressions import calc_expression, condition_text, literal_text


def rule_entity(catalog: Catalog, rule: RuleConfig, master: str) -> str:
    """规则作用的实体。"""
    if rule.layer == "entity":
        return rule.target
    if rule.field is None:
        return master
    for code in catalog.business_entities(master):
        entity = catalog.entity(code)
        if entity is not None and any(f.name == rule.field for f in entity.fields):
            return code
    return master


def rule_masters(catalog: Catalog, rule: RuleConfig) -> list[str]:
    """规则进入哪些业务对象的规则包。"""
    if rule.layer == "entity":
        return catalog.masters_of(rule.target)
    if rule.layer == "operation":
        return sorted({catalog.pages()[p].master.entity for p in catalog.pages_using_operation(rule.target)})
    page = catalog.page(rule.target)
    return [page.master.entity] if page else []


def _field_types(catalog: Catalog, entity_code: str, master: str) -> Any:
    def lookup(source: str, name: str) -> str | None:
        entity = catalog.entity(entity_code if source == "row" else master)
        found = next((f for f in entity.fields if f.name == name), None) if entity else None
        return found.type if found else None
    return lookup


def _graph(name: str, expressions: list[tuple[str, str]]) -> JdmGraph:
    return JdmGraph(
        nodes=[
            {"id": "in", "name": "输入", "type": "inputNode", "content": {}},
            {"id": "expr", "name": name, "type": "expressionNode",
             "content": {"expressions": [{"id": f"e{i + 1}", "key": k, "value": v} for i, (k, v) in enumerate(expressions)]}},
            {"id": "out", "name": "输出", "type": "outputNode", "content": {}},
        ],
        edges=[{"id": "e-in", "sourceId": "in", "targetId": "expr"}, {"id": "e-out", "sourceId": "expr", "targetId": "out"}],
    )


def _rule_graph(catalog: Catalog, code: str, rule: RuleConfig, entity_code: str, master: str) -> JdmGraph:
    types = _field_types(catalog, entity_code, master)
    if rule.category == "calc":
        return _graph(code, [(rule.field or "", calc_expression(rule, types))])
    expressions = [("matched", condition_text(rule.when, types) or "true")]
    if rule.field is not None:
        expressions.append(("field", literal_text(rule.field)))
    if rule.category == "validate":
        expressions += [("level", literal_text(rule.level or "reject")), ("message", literal_text(rule.message or ""))]
    elif rule.effect is not None:
        if rule.effect.editable is not None:
            expressions.append(("editable", "true" if rule.effect.editable else "false"))
        if rule.effect.required is not None:
            expressions.append(("required", "true" if rule.effect.required else "false"))
        for key, style in (("rowStyle", rule.effect.row_style), ("cellStyle", rule.effect.cell_style)):
            if style is not None:
                expressions.append((key, literal_text(json.dumps(style, ensure_ascii=False, separators=(",", ":")))))
    return _graph(code, expressions)


def build_pack(catalog: Catalog, master: str, version: int, core_version: str) -> RulesPack:
    fields: dict[str, dict[str, PackField]] = {}
    for code in catalog.business_entities(master):
        entity = catalog.entity(code)
        if entity is not None:
            fields[code] = {f.name: PackField(type=f.type, scale=f.scale, role=f.role, source=f.source) for f in entity.fields}
    rules: list[PackRule] = []
    graphs: dict[str, JdmGraph] = {}
    for code, rule in sorted(catalog.rules().items()):
        if master not in rule_masters(catalog, rule):
            continue
        entity_code = rule_entity(catalog, rule, master)
        rules.append(PackRule(
            id=code, layer=rule.layer, entity=entity_code,
            operation=rule.target if rule.layer == "operation" else None,
            page=rule.target if rule.layer == "page" else None,
            # C06 v27 去掉了规则的数据项，规则都不依赖数据库数据，C07 的 serverOnly 都为 false
            category=rule.category, order=rule.order, server_only=False, jdm=code,
        ))
        graphs[code] = _rule_graph(catalog, code, rule, entity_code, master)
    return RulesPack(pack_id=master, version=version, core_version=core_version, fields=fields, rules=rules, jdm=graphs)


def pack_json(pack: RulesPack) -> dict[str, Any]:
    data: dict[str, Any] = dump_wire(RulesPack, pack)
    return data


def pack_bytes(pack: RulesPack) -> bytes:
    return json.dumps(pack_json(pack), ensure_ascii=False).encode("utf-8")


def affected_masters(catalog: Catalog, config_type: str, key: str) -> list[str]:
    """保存这一项时要重新编译的规则包（业务对象的主表实体）。"""
    if config_type == "entity":
        return catalog.masters_of(key)
    if config_type == "page":
        page = catalog.page(key)
        return [page.master.entity] if page else []
    if config_type == "operation":
        return sorted({catalog.pages()[p].master.entity for p in catalog.pages_using_operation(key)})
    if config_type == "rule":
        entry = catalog.get("rule", key)
        return rule_masters(catalog, entry.content) if entry else []
    return []
