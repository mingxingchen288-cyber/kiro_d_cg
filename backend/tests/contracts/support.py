"""契约测试共用的样例：从 docs/契约/ 读取 JSON 样例，以及执行上下文的构造。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeConfigSnapshot

DOCS = Path(__file__).resolve().parents[3] / "docs" / "契约"


def doc_blocks(prefix: str, lang: str = "json") -> list[str]:
    text = next(DOCS.glob(f"{prefix}-*.md")).read_text(encoding="utf-8")
    return re.findall(rf"```{lang}\n(.*?)```", text, flags=re.S)


def doc_json(prefix: str, index: int) -> Any:
    return json.loads(doc_blocks(prefix)[index])


def sample_command(**changes: Any) -> t.Command:
    """C02 第 1 节的页面保存命令。"""
    return t.parse_wire(t.Command, {**doc_json("C02", 0), **changes})


ROLE = t.RoleConfig(name="成本会计", admin=False, pages={})


# ---------------------------------------------------------------- 一套自洽的最小配置（C06）
#
# 引用都能在这套配置中找到，字段属于实体，可以经 config 的真实保存流程保存（C06 第 10 节）。表 T_CT_GOODS
# （列 GOODSID、NAME、PRICE）和序列 T_CT_GOODS_SEQ 由真实实现的 harness 在数据库中准备。

CT_ENTITY = "CT_GOODS"
CT_TABLE = "T_CT_GOODS"
CT_PAGE_A = "CT_PAGE_A"
CT_PAGE_B = "CT_PAGE_B"
CT_ROLE_A = "CT_ROLE_A"
CT_ROLE_B = "CT_ROLE_B"
CT_SAVE_A = "CT_PAGE_A.save"
CT_SAVE_B = "CT_PAGE_B.save"


def _draft(config_type: str, key: str, name: str, content: dict[str, Any]) -> t.ConfigDraft:
    return t.ConfigDraft(type=config_type, key=key, name=name, content=content)


def ct_entity() -> t.ConfigDraft:
    return _draft("entity", CT_ENTITY, "契约测试物料", {
        "table": CT_TABLE, "primaryKey": "GOODSID", "freezable": True,
        "fields": [
            {"name": "GOODSID", "column": "GOODSID", "label": "物料", "type": "number", "scale": 0, "source": "own", "role": "system"},
            {"name": "NAME", "column": "NAME", "label": "名称", "type": "text", "source": "own", "role": "input"},
            {"name": "PRICE", "column": "PRICE", "label": "价格", "type": "number", "scale": 2, "source": "own", "role": "input"},
        ],
    })


def ct_page(key: str, save_operation: str) -> t.ConfigDraft:
    return _draft("page", key, f"契约测试页面 {key}", {
        "title": f"契约测试页面 {key}", "layout": "single", "detailMode": "tabs", "audit": False, "saveOperation": save_operation,
        "master": {"entity": CT_ENTITY, "grid": {"sideBar": True, "cellSelection": True, "groupBy": []}},
    })


def ct_save_operation(key: str) -> t.ConfigDraft:
    return _draft("operation", key, "保存", {
        "label": "保存", "kind": "save", "writableFields": {CT_ENTITY: ["NAME", "PRICE"]}, "impact": [CT_ENTITY],
        "propagation": "continue",
    })


def ct_role(key: str, page: str, name: str) -> t.ConfigDraft:
    return _draft("role", key, name, {"name": name, "admin": False, "pages": {page: {"buttons": ["system:save"]}}})


def ct_flow(key: str, source_operation: str, entry_name: str) -> t.ConfigDraft:
    """审批流：`createdSeq` 由 config 在第一次保存时分配（CF-07），这里给出的值不作数，测试也不比较它。"""
    return _draft("approvalFlow", key, key, {
        "createdSeq": 1, "sourceOperation": source_operation,
        "trigger": {"operations": ["modify"], "changedFields": {CT_ENTITY: ["PRICE"]}},
        "levels": [{"level": 1, "entries": [{"name": entry_name, "mode": "or", "approvers": [{"type": "role", "role": CT_ROLE_B}]}]}],
    })


def ct_base_items(role_a_name: str = "契约测试角色甲") -> list[t.ConfigDraft]:
    """实体、两个页面和它们的保存操作、两个角色：角色甲只能访问页面 A，角色乙只能访问页面 B。"""
    return [ct_entity(), ct_save_operation(CT_SAVE_A), ct_save_operation(CT_SAVE_B), ct_page(CT_PAGE_A, CT_SAVE_A),
            ct_page(CT_PAGE_B, CT_SAVE_B), ct_role(CT_ROLE_A, CT_PAGE_A, role_a_name), ct_role(CT_ROLE_B, CT_PAGE_B, "契约测试角色乙")]


def without_created_seq(content: Any) -> Any:
    """比较审批流内容时去掉 config 分配的 createdSeq。"""
    return content.model_copy(update={"created_seq": 0}) if isinstance(content, t.ApprovalFlowConfig) else content


def snapshot(role_code: str = "COST_ACCOUNTANT", version: int = 13) -> FakeConfigSnapshot:
    return FakeConfigSnapshot(version=version, role_code=role_code, role=ROLE)


def identity(user_id: str = "112", role_code: str = "COST_ACCOUNTANT", session_id: str = "s-112") -> t.Identity:
    return t.Identity(user_id=user_id, username=f"user{user_id}", display_name=f"用户{user_id}", department_id="10",
                      role_code=role_code, session_id=session_id)


def context(user_id: str = "112", *, origin: t.Origin | None = None, config: Any = None) -> t.ExecutionContext:
    who = identity(user_id)
    snap = config if config is not None else snapshot(who.role_code)
    return t.ExecutionContext(request_id="00000000-0000-4000-8000-0000000000aa", identity=who, config=snap,
                              config_version=snap.version, origin=origin or t.Origin(kind="user", approval_id=None),
                              now=datetime(2026, 10, 24, 10, 0, 0))
