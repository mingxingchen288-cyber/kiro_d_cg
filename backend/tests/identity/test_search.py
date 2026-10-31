"""人员、部门列表的高级查询（ID-12，C09 v15 `advanced`；盘点 B12，模拟验证）。

数据取自 cmx（`.reports/modules/frontend-admin/01-人员部门角色样例.out.txt`）：部门 采购部、市场部、技术中心；
人员 程苏慧 HY260404（市场部）、汪春龙 HY090702（采购部）、朱文俊 HY190510、韩群 HY221020（技术中心，朱文俊已停用）。
同旧系统人员管理、部门管理的"高级查询"：按勾了"查询"的列（ID、用户名、姓名、部门、状态；部门的 ID、部门名称）查。
"""

from __future__ import annotations

import json

from cost_platform.contracts.types import AccountUpdate, AdvancedQuery, parse_wire

from .support import ACCOUNTANT, Env


def _query(*conditions: dict[str, object], op: str = "and") -> AdvancedQuery:
    return parse_wire(AdvancedQuery, {"op": op, "conditions": list(conditions)})  # type: ignore[no-any-return]


def _env() -> tuple[Env, dict[str, str]]:
    env = Env()
    dept = {name: env.admin.create_department(name, None).department_id for name in ("采购部", "市场部", "技术中心")}
    env.add_account("HY260404", "Abc123..", [ACCOUNTANT], display_name="程苏慧", department_id=dept["市场部"])
    env.add_account("HY090702", "Abc123..", [ACCOUNTANT], display_name="汪春龙", department_id=dept["采购部"])
    zhu = env.add_account("HY190510", "Abc123..", [ACCOUNTANT], display_name="朱文俊", department_id=dept["技术中心"])
    env.add_account("HY221020", "Abc123..", [ACCOUNTANT], display_name="韩群", department_id=dept["技术中心"])
    env.admin.update_account(zhu, AccountUpdate(display_name="朱文俊", department_id=dept["技术中心"],
                                                role_codes=[ACCOUNTANT], enabled=False))
    return env, dept


def _names(env: Env, query: AdvancedQuery, keyword: str = "") -> list[str]:
    return [a.display_name for a in env.admin.list_accounts(keyword, 0, 50, None, query).rows]


def test_accounts_by_name_and_department() -> None:
    """姓名包含"群"、部门是技术中心：查出韩群；部门 IN（采购部、市场部）：程苏慧、汪春龙。"""
    env, dept = _env()
    assert _names(env, _query({"field": "displayName", "operator": "like", "value": "群"},
                              {"field": "departmentId", "operator": "eq", "value": dept["技术中心"]})) == ["韩群"]
    assert _names(env, _query({"field": "departmentId", "operator": "in",
                               "value": [dept["采购部"], dept["市场部"]]})) == ["程苏慧", "汪春龙"]
    result = env.admin.list_accounts("", 0, 50, None, _query({"field": "departmentId", "operator": "eq",
                                                              "value": dept["技术中心"]}))
    assert result.total == 2


def test_accounts_by_username_status_and_id() -> None:
    """用户名包含 hy19（不分大小写）、状态为停用、ID 大于等于某值；和关键字一起用时是且。"""
    env, _ = _env()
    assert _names(env, _query({"field": "username", "operator": "like", "value": "hy19"})) == ["朱文俊"]
    assert _names(env, _query({"field": "enabled", "operator": "eq", "value": False})) == ["朱文俊"]
    han = env.accounts.find("HY221020")
    assert han is not None
    assert _names(env, _query({"field": "userId", "operator": "ge", "value": han.user_id})) == ["韩群"]
    assert _names(env, _query({"field": "enabled", "operator": "eq", "value": True}), keyword="HY2") == ["程苏慧", "韩群"]


def test_departments_by_name() -> None:
    """部门名称包含"部"：采购部、市场部；不填值的条件不起作用。"""
    env, dept = _env()
    found = env.admin.departments(_query({"field": "name", "operator": "like", "value": "部"}))
    assert [d.name for d in found.items] == ["采购部", "市场部"]
    found = env.admin.departments(_query({"field": "departmentId", "operator": "eq", "value": dept["技术中心"]},
                                         {"field": "name", "operator": "like", "value": ""}))
    assert [d.name for d in found.items] == ["技术中心"]


def test_router_passes_advanced_text() -> None:
    """接口的 `advanced` 是 JSON 文本，按 C09 第 4 节的格式解析。"""
    from cost_platform.identity.search import parse_advanced

    text = json.dumps({"op": "and", "conditions": [{"field": "name", "operator": "like", "value": "技术"}]})
    env, _ = _env()
    assert [d.name for d in env.admin.departments(parse_advanced(text)).items] == ["技术中心"]
    assert parse_advanced("") is None
