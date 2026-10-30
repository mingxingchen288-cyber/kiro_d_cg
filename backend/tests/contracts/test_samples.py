"""T-CT-1：契约文档中的 JSON 样例都能解析成类型，再转回 JSON 后内容不变；格式不合法的样例被拒绝。

代码块中的样例直接从 docs/契约/ 读取，文档改了样例，这里自动跟着验证。C09 表格中写在行内的样例含"…"占位，
在本文件中改写为合法值后测试（INLINE）。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cost_platform.contracts import types as t

DOCS = Path(__file__).resolve().parents[3] / "docs" / "契约"


def _blocks(prefix: str, lang: str = "json") -> list[str]:
    text = next(DOCS.glob(f"{prefix}-*.md")).read_text(encoding="utf-8")
    return re.findall(rf"```{lang}\n(.*?)```", text, flags=re.S)


def _json(prefix: str, index: int) -> Any:
    return json.loads(_blocks(prefix)[index])


def _lines(prefix: str, index: int) -> list[Any]:
    return [json.loads(line) for line in _blocks(prefix)[index].splitlines() if line.strip()]


# C06 第 7.8、7.9、7.10 节的三个审批流样例：块 6、7、8。
FLOW_1 = _json("C06", 6)
FLOW_2 = _json("C06", 7)
FLOW_3 = _json("C06", 8)

_UUID = "3f2b6c1e-8a4d-4c2e-9b1a-0d6e5f7a8b9c"
_TMP = "tmp-6a1f2c3d-0b4e-4f5a-8c7d-9e0f1a2b3c4d"
_FP = "sha256:5b1e0c6d9a3f47e28b1c6d0e9f3a2b4c5d6e7f8091a2b3c4d5e6f708192a3b4c"
_ROW = {"rowKey": "1001", "values": {"QTY": "12"}, "frozen": None}
_USER = {"userId": "112", "username": "yangna", "displayName": "杨娜", "departmentId": "10"}
_ROLE = {"code": "COST_ACCOUNTANT", "name": "成本会计", "admin": False}


def _command(document: Any) -> Any:
    return {"requestKey": _UUID, "page": "COST_PINGGU", "operation": "COST_PINGGU.save", "documents": [document], "params": {}}


def _broken(path: list[Any], value: Any, base: Any) -> Any:
    data = copy.deepcopy(base)
    node = data
    for key in path[:-1]:
        node = node[key]
    if value is _DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return data


def _renamed(path: list[Any], old: str, new: str, base: Any) -> Any:
    data = copy.deepcopy(base)
    node = data
    for key in path:
        node = node[key]
    node[new] = node.pop(old)
    return data


_DELETE = object()


# 后端会输出或接收的样例：解析后按 dump_wire 输出，与样例逐字段相同。
SAMPLES: list[tuple[str, Any, Any]] = [
    ("C02 页面保存", _json("C02", 0), t.Command),
    ("C02 审批处理", _json("C02", 1), t.Command),
    ("C02 新增单据", _command({"entity": "COST_PINGGU", "master": {"op": "add", "clientRowId": _TMP, "values": {"QTY": "1"}},
                             "details": [{"entity": "COST_MATERIAL", "op": "add", "clientRowId": _TMP, "values": {"GOODSID": "115"}}]}), t.Command),
    ("C02 删除单据", _command({"entity": "COST_PINGGU", "master": {"op": "delete", "rowKey": "1001"}, "details": []}), t.Command),
    ("C02 只改明细", _command({"entity": "COST_PINGGU", "master": {"op": "none", "rowKey": "1001"},
                             "details": [{"entity": "COST_MATERIAL", "op": "modify", "rowKey": "5001", "changes": {"PRICE": None}}]}), t.Command),
    ("C02 已写入", _json("C02", 2), t.CommandResult),
    ("C02 已提交审批", _json("C02", 3), t.CommandResult),
    ("C02 新增行的提示", {"requestKey": _UUID, "outcome": "saved", "rows": [], "idMap": {}, "prompts": [
        {"rule": "R_PRICE_LOW", "message": "单价偏低", "entity": "COST_MATERIAL", "clientRowId": _TMP, "field": "PRICE"}],
        "skipped": [], "approvals": []}, t.CommandResult),
    ("C03 错误", _json("C03", 0), t.ErrorResponse),
    ("C03 配置校验错误", {"code": "VALIDATION_FAILED", "message": "配置校验不通过", "details": [
        {"message": "入口至少要有一个审批人", "entity": None, "rowKey": None, "clientRowId": None, "field": None, "approvalId": None,
         "configType": "approvalFlow", "configKey": "GOODS_TO_COST", "path": "levels[0].nodes[0].approvers"}]}, t.ErrorResponse),
    ("C05 页面视图", _json("C05", 0), t.PageView),
    ("C05 带筛选的多选 Lookup", _broken(["details", 0, "fields", 0, "lookup"],
                                   {"code": "GOODS", "fill": {"GOODSID": "GOODSID"}, "multiple": True,
                                    "filter": {"column": "GOODSTYPE", "from": "row", "field": "PACKTYPE"}, "fillBack": False},
                                   _json("C05", 0)), t.PageView),
    ("C06 配置项", _json("C06", 0), t.ConfigItem),
    ("C06 审批流样例一", FLOW_1, t.ConfigDraft),
    ("C06 审批流样例二", FLOW_2, t.ConfigDraft),
    ("C06 审批流样例三", FLOW_3, t.ConfigDraft),
    ("C07 规则包", _json("C07", 0), t.RulesPack),
    ("C07 求值请求", _json("C07", 1), t.EvaluationRequest),
    ("C07 求值结果", _json("C07", 2), t.EvaluationResult),
    ("C07 显示求值请求", _json("C07", 3), t.EvaluationRequest),
    ("C07 显示求值结果", _json("C07", 4), t.EvaluationResult),
    ("C07 新增行的结果", {"ok": True, "rows": [{"entity": "COST_MATERIAL", "clientRowId": _TMP, "computed": {"AMOUNT": "1.20"},
                                                "fields": {}, "style": {"row": None, "cells": {}}}],
                       "effects": [{"kind": "prompt", "rule": "R_PRICE_LOW", "message": "单价偏低", "entity": "COST_MATERIAL",
                                    "clientRowId": _TMP, "field": "PRICE"}]}, t.EvaluationResult),
    ("C07 失败结果", {"ok": False, "error": {"code": "PACK_INVALID", "message": "规则包不能编译"}}, t.EvaluationResult),
    ("C09 列表请求", _json("C09", 0), t.ListRequest),
    ("C09 个人配置", _json("C09", 1), t.PersonalConfig),
    ("C09 待办摘要", _json("C09", 2), t.ApprovalSummary),
    ("C09 审批详情", _json("C09", 3), t.ApprovalDetail),
    ("C10 频道事件", _json("C10", 0), t.ChannelEvent),
    *[(f"C10 浏览器消息 {i}", m, t.ClientMessage) for i, m in enumerate(_lines("C10", 1))],
    *[(f"C10 服务端消息 {i}", m, t.ServerMessage) for i, m in enumerate(_lines("C10", 2))],
]

INLINE: list[tuple[str, Any, Any]] = [
    ("C09 选角色请求", {"roleCode": "COST_ACCOUNTANT"}, t.SelectRoleRequest),
    ("C09 修改账号", {"displayName": "张三", "departmentId": "10", "roleCodes": [], "enabled": False}, t.AccountUpdate),
    ("C09 部门列表", {"items": [{"departmentId": "10", "name": "成本部", "parentId": None}]}, t.DepartmentList),
    ("C09 配置项列表", {"items": [{"type": "page", "key": "COST_PINGGU", "name": "成本核算", "version": 13, "updatedBy": "1",
                               "updatedAt": "2026-10-24T10:00:00"}]}, t.ConfigItemList),
    ("C09 保存配置请求", {"name": "成本核算", "content": {}}, t.ConfigSaveRequest),
    ("C09 保存配置响应", {"type": "page", "key": "COST_PINGGU", "version": 14}, t.ConfigSaveResponse),
    ("C09 向导读列请求", {"readView": "T_COST_GOODS_PRICE_V", "table": "T_COST_GOODS"}, t.WizardColumnsRequest),
    ("C09 向导读列响应", {"primaryKey": "GOODSID", "sequence": {"name": "T_COST_GOODS_SEQ", "exists": True},
                       "columns": [{"name": "ZX_PRICE", "type": "number", "label": "执行价", "inTable": True}]}, t.WizardColumnsResponse),
    ("C09 向导生成请求", {"parentMenu": "cost", "pageCode": "GOODS_PRICE_MANAGE", "title": "物料清单及成本", "layout": "single",
                       "detailMode": "tabs", "audit": True, "master": {}, "details": []}, t.WizardGenerateRequest),
    ("C09 列表响应", {"rows": [_ROW], "total": 1234, "aggregates": {"TOTAL_COST": "98765.43"}}, t.ListResponse),
    ("C09 按主键读行", {"entity": "COST_PINGGU", "rowKeys": ["1001", "1002"]}, t.ByKeysRequest),
    ("C09 单据响应", {"master": _ROW, "details": {"COST_MATERIAL": [_ROW]}}, t.RecordResponse),
    ("C09 Lookup 查询请求", {"keyword": "胶", "filter": {"column": "GOODSTYPE", "value": "瓶"}, "startRow": 0, "endRow": 50},
     t.LookupSearchRequest),
    ("C09 Lookup 查询响应", {"rows": [{"values": {"GOODSID": "115", "NAME": "胶囊壳"}}], "total": 3, "keywordSearch": True},
     t.LookupSearchResponse),
    ("C09 不支持关键字搜索的 Lookup 查询响应", {"rows": [], "total": 0, "keywordSearch": False}, t.LookupSearchResponse),
    ("C09 字典", {"items": [{"value": "1", "label": "启用"}]}, t.DictResponse),
    ("C09 导出列表", {"items": [{"exportCode": "cost-pinggu-export", "name": "物料成本核算表导出"}]}, t.ExportList),
    ("C09 默认导出", {"mode": "page", "request": _json("C09", 0), "columns": ["DOCID", "GOODSNAME"]}, t.ExportRequest),
    ("C09 按配置导出", {"mode": "config", "exportCode": "cost-pinggu-export", "scope": "current", "request": _json("C09", 0)},
     t.ExportRequest),
    ("C09 通过请求", {"requestKey": _UUID, "fingerprint": _FP,
                    "checkedRows": [{"flow": "GOODS_TO_COST", "block": "costMaterial", "key": "206323"}],
                    "comment": "价格已核对", "params": {"effectiveDate": "2026-11-01"}}, t.PassRequest),
    ("C09 预览请求", {"checkedRows": [{"flow": "GOODS_TO_COST", "block": "costMaterial", "key": "206323"}]}, t.PreviewRequest),
    ("C09 预览响应", {"view": _json("C09", 3)["view"], "fingerprint": _FP}, t.PreviewResponse),
    ("C09 读表结构请求", {"name": "V_COST_PINGGU_MATERIAL"}, t.SchemaColumnsRequest),
    ("C09 读表结构响应", {"objectType": "view", "primaryKey": None, "columns": [{"name": "DTLID", "type": "number"}]},
     t.SchemaColumnsResponse),
    ("C09 驳回请求", {"requestKey": _UUID, "comment": "价格偏高"}, t.RejectRequest),
    ("C09 撤回请求", {"requestKey": _UUID, "comment": "录入有误"}, t.WithdrawRequest),
    ("C09 通知列表", {"rows": [{"deliveryId": _UUID, "title": "您有来自于物料清单及成本页面，业务单据为115的审批", "body": "",
                              "link": "/approval/203", "createdAt": "2026-10-24T09:30:01", "read": False}],
                    "total": 3, "unread": 2}, t.InboxList),
    ("C09 投递列表", {"rows": [{"deliveryId": _UUID, "recipient": "111", "status": "abandoned", "attempts": 5, "nextRetryAt": None,
                              "lastError": "连接被拒绝"}], "total": 1}, t.DeliveryList),
    ("C09 命令审查开关", {"enabled": False}, t.CommandReviewToggle),
    ("C09 健康检查 ok", {"status": "ok", "coreVersion": "0.1.0", "configVersion": 13}, t.HealthResponse),
    ("C09 健康检查 starting", {"status": "starting"}, t.HealthResponse),
    ("C09 登录响应", {"user": _USER, "roles": [_ROLE], "selectedRole": _ROLE, "csrfToken": "c"}, t.LoginResponse),
    ("C09 登录响应（多个角色未选定）", {"user": _USER, "roles": [_ROLE, _ROLE], "selectedRole": None, "csrfToken": "c"}, t.LoginResponse),
    ("C09 选角色响应", {"selectedRole": _ROLE}, t.SelectRoleResponse),
    ("C09 当前用户", {"user": _USER, "role": _ROLE, "menus": [{"key": "cost", "title": "成本", "kind": "group", "children": [
        {"key": "COST_PINGGU", "title": "成本核算", "kind": "page", "pageCode": "COST_PINGGU"}]}], "configVersion": 13, "csrfToken": "c"},
     t.MeResponse),
    ("C09 账号列表", {"rows": [{"userId": "112", "username": "yangna", "displayName": "杨娜", "departmentId": "10", "enabled": True,
                               "roleCodes": ["COST_ACCOUNTANT"]}], "total": 120}, t.AccountList),
    ("C09 配置校验请求", {"items": [FLOW_1]}, t.ConfigValidateRequest),
    ("C09 配置校验响应", {"ok": False, "errors": [{"message": "入口至少要有一个审批人", "entity": None, "rowKey": None, "clientRowId": None,
                                                 "field": None, "approvalId": None, "configType": "approvalFlow",
                                                 "configKey": "GOODS_TO_COST", "path": "levels[0].nodes[0].approvers"}]},
     t.ConfigValidateResponse),
    ("C09 按主键读行响应", {"rows": [_ROW, {**_ROW, "rowKey": "1002", "frozen": {"approvalId": "203"},
                                       "compare": {"PRICE": {"value": "3.50", "diff": "0.30", "percent": "8.57"}}}]}, t.RowsResponse),
    ("C09 待办列表", {"rows": [_json("C09", 2)], "total": 7}, t.ApprovalList),
    ("C09 命令审查记录", {"enabled": True, "rows": [{
        "requestKey": _UUID, "user": "admin", "page": "COST_PINGGU", "operation": "COST_PINGGU.save", "result": "rejected",
        "errorCode": "RULE_REJECTED", "message": "价格超出范围", "startedAt": "2026-10-24T09:30:00", "durationMs": 35, "sqlCount": 2,
        "sqlMs": 4.5, "sql": [{"text": "SELECT 1 FROM DUAL", "binds": {}, "ms": 1.2, "rows": 1, "error": None}]}], "total": 12},
     t.CommandReviewList),
    ("C10 通知事件", {"eventId": _UUID, "topic": "notification", "audience": {"users": ["111"]},
                      "payload": {"deliveryId": _UUID, "title": "您有来自于物料清单及成本页面，业务单据为115的审批", "body": "",
                                  "link": "/approval/203"}}, t.ChannelEvent),
    ("C10 会话失效事件（按用户）", {"eventId": _UUID, "topic": "session.revoked", "audience": {"users": ["112"]},
                                   "payload": {"reason": "accountDisabled"}}, t.ChannelEvent),
    ("C10 会话失效事件（按会话）", {"eventId": _UUID, "topic": "session.revoked", "audience": {"sessions": ["s1"]},
                                   "payload": {"reason": "loggedOut"}}, t.ChannelEvent),
    ("C09 审批详情的来源行没有触发审批", _broken(["view", "master", "rows", 0, "flows"], [], _json("C09", 3)), t.ApprovalDetail),
]

# C06 的配置内容由管理员编写，原样保存；模型只用于读取和校验结构，所以只比较解析时给出的字段（exclude_unset）。
_ENTITY_EXAMPLES = {
    "table": "T_COST_GOODS", "readView": "T_COST_GOODS_PRICE_V", "primaryKey": "GOODSID", "freezable": True,
    "erpRow": {"column": "ISERP", "value": "1", "localValue": "0"},
    "fields": [
        {"name": "GOODSID", "column": "GOODSID", "label": "物料", "type": "number", "scale": 0, "source": "own", "role": "system"},
        {"name": "UNIT", "column": "UNIT", "label": "单位", "type": "text", "source": "own", "role": "input",
         "default": {"type": "static", "value": "1"}},
        {"name": "CREATE_BY", "column": "CREATE_BY", "label": "创建人", "type": "text", "source": "own", "role": "input",
         "default": {"type": "builtin", "value": "currentUserId"}},
        {"name": "STATUS", "column": "STATUS", "label": "状态", "type": "text", "source": "own", "role": "input",
         "default": {"type": "options", "value": ["A", "B"]}},
        {"name": "PRICE", "column": "PRICE", "label": "价格", "type": "number", "scale": 4, "source": "erp", "role": "input",
         "compare": {"mode": "field", "field": "LAST_PRICE", "format": "both"}},
        {"name": "ZX_PRICE", "column": None, "label": "执行价", "type": "number", "scale": 4, "source": "own", "role": "input",
         "compare": {"mode": "query", "source": "T_COST_GOODS_HIS_V", "keys": [{"current": "GOODSID", "compare": "GOODSID"}],
                     "field": "PRICE", "format": "percent"}},
    ],
    "approvalRequired": [{"fields": ["ZX_PRICE"], "when": {"logic": "AND", "conditions": [{"field": "ISERP", "op": "eq", "value": "1"}]},
                          "sourcePages": ["GOODS_PRICE_MANAGE"]}],
}
_FLOW_EXAMPLES = {
    **FLOW_1["content"],
    "enabled": False,
    "operations": {"COST_MATERIAL": ["add", "modify", "delete"]},
    "levels": [
        {"level": 1, "nodes": [{"name": "主管审核", "conditionType": "always", "department": "1069", "mode": "and", "enabled": True,
                                "approvers": [
                                    {"type": "user", "userId": "111"},
                                    {"type": "role", "role": "COST_MANAGER"},
                                    {"type": "sql", "sql": "SELECT USER_ID FROM T_COST_DEPT_LEADER WHERE DEPT_ID = :deptId",
                                     "binds": {"deptId": "DEPT_ID"}}]}]},
    ],
    "freeze": [{"table": "T_COST_PINGGU_DTL", "condition": "GOODSID = :new_GOODSID AND DOCID <> :billId", "enabled": False}],
    # C06 7.5：写回来源单据（E27）、新增记录、删除明细、逃生舱都配成受影响单据的一块
    "display": [
        *FLOW_1["content"]["display"],
        {"key": "self", "title": "来源单据", "region": "affected", "source": "T_COST_PINGGU", "condition": "DOCID = :billId",
         "columns": [], "selection": "hidden",
         "actions": [{"action": "updateFields", "fields": [{"column": "EFFECTIVE_DATE", "value": ":params_effectiveDate"}]},
                     {"action": "insertRows", "table": "T_COST_PRICE_LOG",
                      "fields": [{"column": "DOCID", "value": ":row_DOCID"}, {"column": "REASON", "value": ":params_reason"}]},
                     {"action": "escapeHatch", "operation": "COST_PINGGU.recalc_proc"}]},
        {"key": "old", "title": "要删除的明细", "region": "affected", "source": "V_COST_PINGGU_MATERIAL",
         "condition": "GOODSID = :old_GOODSID", "targetTable": "T_COST_PINGGU_DTL", "keyColumn": "DTLID",
         "columns": [{"field": "GOODSNAME", "label": "物料", "width": 160, "targetColumn": "GOODSNAME"}],
         "selection": "checked", "actions": [{"action": "deleteRows"}]}],
    "params": [{"name": "effectiveDate", "label": "生效日期", "type": "date", "source": "manual", "required": True, "level": 1},
               {"name": "reason", "label": "原因", "type": "string", "source": "constant", "required": False, "value": "调价"}],
    "notify": [{"event": "submitted", "to": "levelApprovers"}, {"event": "passed", "to": {"users": ["111"]}},
               {"event": "rejected", "to": {"role": "COST_MANAGER"}}],
}
_OPERATION_EXAMPLES = {"label": "同步价格", "kind": "action", "writableFields": {"COST_PINGGU": ["PRICE"]}, "impact": ["COST_PINGGU"],
                       "actions": [{"action": "escapeHatch", "operation": "COST_PINGGU.recalc_proc"}], "rowNotFound": "reject",
                       "propagation": "end"}
_PAGE_FIELD_EXAMPLES = _broken(["master", "fields"], {"GOODSID": {"lookup": {
    "code": "GOODS", "fill": {"GOODSID": "GOODSID", "GOODSNAME": "NAME"}, "multiple": False,
    "filter": {"column": "GOODSTYPE", "from": "row", "field": "PACKTYPE"}, "fillBack": True}, "dictType": "GOODS_TYPE"}}, _json("C06", 2))
_ROLE_SQL_ROWS = _broken(["pages", "COST_PINGGU", "rows"], "CREATE_BY = ${username}", _json("C06", 9))

CONFIG_CONTENTS: list[tuple[str, Any, Any]] = [
    ("C06 正文例子：entity", _ENTITY_EXAMPLES, t.EntityConfig),
    ("C06 正文例子：审批流", _FLOW_EXAMPLES, t.ApprovalFlowConfig),
    ("C06 正文例子：operation", _OPERATION_EXAMPLES, t.OperationConfig),
    ("C06 正文例子：页面字段的 Lookup", _PAGE_FIELD_EXAMPLES, t.PageConfig),
    ("C06 正文例子：自定义 SQL 行权限", _ROLE_SQL_ROWS, t.RoleConfig),
    ("C06 entity", _json("C06", 1), t.EntityConfig),
    ("C06 page", _json("C06", 2), t.PageConfig),
    ("C06 operation", _json("C06", 3), t.OperationConfig),
    ("C06 计算规则", _json("C06", 4), t.RuleConfig),
    ("C06 界面规则", _json("C06", 5), t.RuleConfig),
    ("C06 审批流样例一的内容", FLOW_1["content"], t.ApprovalFlowConfig),
    ("C06 审批流样例二的内容", FLOW_2["content"], t.ApprovalFlowConfig),
    ("C06 审批流样例三的内容", FLOW_3["content"], t.ApprovalFlowConfig),
    ("C06 role", _json("C06", 9), t.RoleConfig),
    ("C06 menu", _json("C06", 10), t.MenuConfig),
    ("C06 dict", _json("C06", 11), t.DictConfig),
    ("C06 lookup", _json("C06", 12), t.LookupConfig),
    ("C06 正文例子：不按关键字搜索的 Lookup", _broken(["keywordColumns"], [], _json("C06", 12)), t.LookupConfig),
    ("C06 export", _json("C06", 13), t.ExportConfig),
]


@pytest.mark.parametrize(("name", "data", "model"), SAMPLES + INLINE, ids=[s[0] for s in SAMPLES + INLINE])
def test_sample_roundtrip(name: str, data: Any, model: Any) -> None:
    assert t.dump_wire(model, t.parse_wire(model, data)) == data


@pytest.mark.parametrize(("name", "data", "model"), CONFIG_CONTENTS, ids=[s[0] for s in CONFIG_CONTENTS])
def test_config_content_parses_without_loss(name: str, data: Any, model: Any) -> None:
    value = t.parse_wire(model, data)
    assert t.adapter(model).dump_python(value, mode="json", by_alias=True, exclude_unset=True) == data


def test_config_items_parse_by_type() -> None:
    for item in (FLOW_1, FLOW_2):
        draft = t.parse_wire(t.ConfigDraft, item)
        assert isinstance(t.parse_config_content(draft.type, draft.content), t.ApprovalFlowConfig)


def test_password_is_masked_when_dumped() -> None:
    login = t.parse_wire(t.LoginRequest, {"username": "admin", "password": "secret"})
    assert login.password.get_secret_value() == "secret"
    assert "secret" not in repr(login)
    assert t.dump_wire(t.LoginRequest, login)["password"] == "**********"
    change = t.parse_wire(t.PasswordChange, {"password": "secret"})  # C09 重设密码的请求
    assert change.password.get_secret_value() == "secret"
    assert t.dump_wire(t.PasswordChange, change) == {"password": "**********"}
    with pytest.raises(ValidationError):
        t.parse_wire(t.PasswordChange, {"password": "secret", "oldPassword": "x"})
    account = t.parse_wire(t.AccountCreate, {"username": "zhangsan", "displayName": "张三", "departmentId": "10",
                                             "password": "secret", "roleCodes": ["COST_ACCOUNTANT"]})
    assert account.password.get_secret_value() == "secret"


def test_constructed_values_dump_in_sample_shape() -> None:
    """后端用构造函数生成结果时，输出形状与样例相同：可选字段没有值时省略，写明为 null 的字段总是出现。"""
    row = t.ResultRow(entity="COST_PINGGU", row_key="1001", values={"QTY": "12"}, frozen=None)
    assert t.dump_wire(t.ResultRow, row) == {"entity": "COST_PINGGU", "rowKey": "1001", "values": {"QTY": "12"}, "frozen": None}
    row = t.ResultRow(entity="COST_PINGGU", row_key="1001", client_row_id=None, values={}, frozen=None)
    assert "clientRowId" not in t.dump_wire(t.ResultRow, row)
    assert t.dump_wire(t.HealthResponse, t.HealthResponse(status="starting")) == {"status": "starting"}
    menu = t.MenuItem(key="COST_PINGGU", title="成本核算", kind="page", page_code="COST_PINGGU")
    assert t.dump_wire(t.MenuItem, menu) == {"key": "COST_PINGGU", "title": "成本核算", "kind": "page", "pageCode": "COST_PINGGU"}
    detail = t.ErrorDetail(message="PRICE 不能修改", field="PRICE")
    assert t.dump_wire(t.ErrorDetail, detail) == {"message": "PRICE 不能修改", "entity": None, "rowKey": None, "clientRowId": None,
                                                  "field": "PRICE", "approvalId": None, "configType": None, "configKey": None,
                                                  "path": None}
    with pytest.raises(ValidationError):
        t.ResultRow(entity="COST_PINGGU", row_key="1001", values={})  # type: ignore[call-arg]  # 未冻结时也必须给出 frozen=None
    assert t.dump_wire(t.ViewRow, t.ViewRow(op="modify", cells=[], flows=[])) == {"op": "modify", "cells": [], "flows": []}
    assert t.dump_wire(t.ViewRow, t.ViewRow(op="modify", cells=[])) == {"op": "modify", "cells": []}
    lost = t.ViewRow(op="none", cells=[t.ViewCell(before="2601", after="2601")], missing=True)
    assert t.dump_wire(t.ViewRow, lost) == {"op": "none", "cells": [{"before": "2601", "after": "2601"}], "missing": True}
    table = t.ViewAffectedTable(flow="GOODS_TO_COST", key="costs", title="受影响的成本单", selection="checked", editable=False,
                                columns=[], rows=[])
    assert t.dump_wire(t.ViewAffectedTable, table) == {"flow": "GOODS_TO_COST", "key": "costs", "title": "受影响的成本单",
                                                       "selection": "checked", "editable": False, "columns": [], "rows": []}
    assert t.dump_wire(t.EvaluationResult, t.EvalComputed(ok=True, rows=[], effects=[])) == {"ok": True, "rows": [], "effects": []}


def test_datetime_is_dumped_to_seconds() -> None:
    from datetime import datetime

    item = t.ConfigItemSummary(type="page", key="COST_PINGGU", name="成本核算", version=13, updated_by="1",
                               updated_at=datetime(2026, 10, 24, 10, 0, 0, 500000))
    assert t.dump_wire(t.ConfigItemSummary, item)["updatedAt"] == "2026-10-24T10:00:00"


def test_error_detail_keeps_one_key_style() -> None:
    detail = t.ErrorDetail(message="x", field="F")
    assert set(detail.model_dump()) == set(t.dump_wire(t.ErrorDetail, detail))
    assert len(detail.model_dump()) == 9
    assert set(detail.model_dump(by_alias=False)) == set(t.ErrorDetail.model_fields)


def test_c06_documented_defaults() -> None:
    """C06 写明的默认值：Lookup 默认单选并回填且不筛选、导出默认 Calibri 和每张主单一张明细表、要修改的行已删除时默认跳过、
    审批流默认启用、传播边界固定为 end、冻结和展示数据省略时为空。"""
    lookup = t.parse_wire(t.LookupSetting, {"code": "GOODS", "fill": {}})
    assert (lookup.multiple, lookup.fill_back, lookup.filter) == (False, True, None)
    export = t.parse_wire(t.ExportConfig, {k: v for k, v in _json("C06", 13).items() if k not in ("font", "detailLayout")})
    assert (export.font, export.detail_layout) == ("Calibri", "perMaster")
    assert t.parse_wire(t.OperationConfig, {"label": "保存", "kind": "save", "propagation": "continue"}).row_not_found == "skip"
    flow = {k: v for k, v in FLOW_1["content"].items() if k not in ("enabled", "propagation", "freeze", "display")}
    parsed = t.parse_wire(t.ApprovalFlowConfig, flow)
    assert (parsed.enabled, parsed.propagation, parsed.freeze, parsed.display) == (True, "end", [], [])
    with pytest.raises(ValidationError):
        t.parse_wire(t.ApprovalFlowConfig, {**FLOW_1["content"], "propagation": "continue"})
    button = t.parse_wire(t.ButtonConfig, {"action": "copyRow", "label": "复制"})
    assert (button.operation, button.requires_selection) == (None, None)


def _section_1_1() -> dict[str, dict[str, Any]]:
    """C06 第 1.1 节的表格：每个结构可以省略的字段和省略时的值（"无"为 None，"空"为空数组或空对象，其余为 JSON 字面量）。"""
    text = next(DOCS.glob("C06-*.md")).read_text(encoding="utf-8")
    section = text.split("### 1.1 字段的省略", 1)[1].split("\n## ", 1)[0]
    table: dict[str, dict[str, Any]] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) != 2 or cells[0] in ("结构", "---"):
            continue
        fields: dict[str, Any] = {}
        for part in cells[1].split("；"):
            names, _, value = part.partition("：")
            parsed: Any
            if value == "无":
                parsed = None
            elif value == "空":
                parsed = "空"
            else:
                parsed = json.loads(value.strip("`"))
            for name in re.findall(r"`([^`]+)`", names):
                fields[name] = parsed
        table[cells[0]] = fields
    return table


# C06 第 1.1 节表格的每一行对应的模型。
_SECTION_1_1_MODELS: dict[str, tuple[Any, ...]] = {
    "`entity` 的内容": (t.EntityConfig,),
    "entity 的 `fields[]`": (t.EntityField,),
    "entity 的 `approvalRequired[]`": (t.ApprovalRequiredRule,),
    "`approvalRequired[].when.conditions[]`": (t.RequiredConditionItem,),
    "字段的可见、可编辑、必填（entity 的 `fieldDefaults`，role 的 `columns`）": (t.FieldFlags,),
    "`page` 的内容": (t.PageConfig,),
    "page 的 `master`、`details[]`": (t.PageMasterConfig, t.PageDetailConfig),
    "page 区域 `fields` 中的每个字段": (t.FieldSetting,),
    "page 字段的 `lookup`": (t.LookupSetting,),
    "page 字段的 `lookup.filter`": (t.LookupFilter,),
    "page 区域的 `buttons[]`": (t.ButtonConfig,),
    "`operation` 的内容": (t.OperationConfig,),
    "`updateTargets` 的 `targets[]`": (t.TargetUpdate,),
    "关联 SQL（6.1，用于 `updateRecords`）": (t.SqlFinder,),
    "`replaceDetails`（第 6 节）": (t.ReplaceDetails,),
    "`updateRows`（第 6 节）": (t.UpdateRows,),
    "`rule` 的内容": (t.RuleConfig,),
    "可视化条件的 `conditions[]`（第 5 节）": (t.RuleConditionItem,),
    "rule 的 `branches[]`": (t.Branch,),
    "rule 的 `effect`": (t.UiEffect,),
    "`dataItems[]`": (t.DataItem,),
    "`approvalFlow` 的内容": (t.ApprovalFlowConfig,),
    "approvalFlow 的 `levels[].nodes[]`": (t.FlowNode,),
    "SQL 审批人": (t.SqlApprover,),
    "approvalFlow 的 `freeze[]`": (t.FreezeItem,),
    "approvalFlow 的 `display[]`": (t.DisplayBlock,),
    "`display[].columns[]`": (t.DisplayColumn,),
    "approvalFlow 的 `params[]`": (t.FlowParam,),
    "`role` 的内容": (t.RoleConfig,),
    "role `pages` 中的每个页面": (t.RolePage,),
    "行权限可视化条件的 `conditions[]`（第 8 节）": (t.RowConditionItem,),
    "menu 的 `items[]`（含 `children`）": (t.MenuItem,),
    "`lookup` 的内容": (t.LookupConfig,),
    "`export` 的内容": (t.ExportConfig,),
}


def _reachable_models(roots: Any) -> set[Any]:
    """从各类配置内容的模型出发，经字段类型能到达的全部模型。"""
    import typing

    from pydantic import BaseModel

    found: set[Any] = set()

    def visit(tp: Any) -> None:
        if isinstance(tp, type) and issubclass(tp, BaseModel):
            if tp in found:
                return
            found.add(tp)
            for info in tp.model_fields.values():
                visit(info.annotation)
            return
        for arg in typing.get_args(tp):
            visit(arg)

    for root in roots:
        visit(root)
    return found


def _omittable(model: Any) -> dict[str, Any]:
    """模型中带默认值的字段（JSON 字段名）和默认值；空数组、空对象记为"空"。"""
    result = {}
    for name, info in model.model_fields.items():
        if info.is_required():
            continue
        default = info.get_default(call_default_factory=True)
        result[info.alias or name] = "空" if default in ([], {}) else default
    return result


def test_c06_omittable_fields_match_section_1_1() -> None:
    """C06 第 1.1 节：表中列出的字段可以省略、省略时取表中的值；没有列出的字段都必须写出。"""
    table = _section_1_1()
    assert set(table) == set(_SECTION_1_1_MODELS)
    problems = []
    for label, models in _SECTION_1_1_MODELS.items():
        for model in models:
            if _omittable(model) != table[label]:
                problems.append(f"{label}（{model.__name__}）：模型 {_omittable(model)}，文档 {table[label]}")
    listed = {m for models in _SECTION_1_1_MODELS.values() for m in models}
    for model in _reachable_models(t.CONFIG_CONTENT.values()) - listed:
        if _omittable(model):
            problems.append(f"{model.__name__} 有可以省略的字段 {_omittable(model)}，C06 第 1.1 节没有列出")
    for model in listed - _reachable_models(t.CONFIG_CONTENT.values()):
        problems.append(f"{model.__name__} 不属于任何配置内容")
    assert problems == []


# C06 中必须写、但值可以为 null 的字段：实体字段的 column 为 null 表示只在 readView 中存在（C06 第 2 节）。
_C06_REQUIRED_NULLABLE = {"EntityField.column"}


def test_c06_required_fields_reject_null() -> None:
    """C06 第 1.1 节：必须写的字段（包括决定行为的字段）不能用 null 代替取值，只有正文写明可以为 null 的除外。"""
    from pydantic import TypeAdapter

    nullable = set()
    for model in _reachable_models(t.CONFIG_CONTENT.values()):
        for name, info in model.model_fields.items():
            if not info.is_required():
                continue
            try:
                TypeAdapter(info.annotation).validate_python(None)
            except ValidationError:
                continue
            nullable.add(f"{model.__name__}.{name}")
    assert nullable == _C06_REQUIRED_NULLABLE


def test_c04_c08_rules() -> None:
    """C04、C08 写明的规则：来源为审批时必须有 approval_id；CommandState 开始时除 command 外都为空、outcome 为 None。"""
    with pytest.raises(ValueError):
        t.Origin(kind="approval", approval_id=None)
    assert t.Origin(kind="approval", approval_id="203").approval_id == "203"
    state = t.CommandState(command=t.parse_wire(t.Command, _json("C02", 0)))
    assert state.outcome is None
    assert (state.involved, state.current, state.actions, state.effects, state.approvals, state.pending_documents) == ([], {}, [], [], [], set())
    assert state.changes == t.ChangePlan(rows=[])
    assert t.ImportReport(1, [("a", "b")]) == t.ImportReport(1, [("a", "b")])
    assert t.ApprovalState is t.ApprovalRef



INVALID = [
    ("请求键不是 UUID", t.Command, _broken(["requestKey"], "abc", _json("C02", 0))),
    ("请求键为大写", t.Command, _broken(["requestKey"], "3F2B6C1E-8A4D-4C2E-9B1A-0D6E5F7A8B9C", _json("C02", 0))),
    ("请求键末尾带换行", t.Command, _broken(["requestKey"], _UUID + "\n", _json("C02", 0))),
    ("缺少请求键", t.Command, _broken(["requestKey"], _DELETE, _json("C02", 0))),
    ("字段名用 snake_case", t.Command, _renamed([], "requestKey", "request_key", _json("C02", 0))),
    ("行的字段名用 snake_case", t.Command, _renamed(["documents", 0, "master"], "rowKey", "row_key", _json("C02", 0))),
    ("缺少 params", t.Command, _broken(["params"], _DELETE, _json("C02", 0))),
    ("未知的行操作", t.Command, _broken(["documents", 0, "master", "op"], "upsert", _json("C02", 0))),
    ("多出未定义的字段", t.Command, _broken(["extra"], 1, _json("C02", 0))),
    ("修改行缺少 rowKey", t.Command, _broken(["documents", 0, "master", "rowKey"], _DELETE, _json("C02", 0))),
    ("新增行缺少 clientRowId", t.Command, _broken(["documents", 0, "details", 0, "clientRowId"], _DELETE, _json("C02", 0))),
    ("新增行带 rowKey", t.Command, _broken(["documents", 0, "details", 0, "rowKey"], "9", _json("C02", 0))),
    ("临时编号格式不对", t.Command, _broken(["documents", 0, "details", 0, "clientRowId"], "new-1", _json("C02", 0))),
    ("业务值用了 JSON 数字", t.Command, _broken(["documents", 0, "master", "changes", "QTY"], 12, _json("C02", 0))),
    ("未知的结果", t.CommandResult, _broken(["outcome"], "done", _json("C02", 2))),
    ("删除的行带 values", t.CommandResult, _broken(["rows", 2, "values"], {"DTLID": "5002"}, _json("C02", 2))),
    ("未冻结的行缺少 frozen", t.CommandResult, _broken(["rows", 0, "frozen"], _DELETE, _json("C02", 2))),
    ("审批级别写成字符串", t.CommandResult, _broken(["approvals", 0, "level"], "1", _json("C02", 3))),
    ("审批级别写成布尔", t.CommandResult, _broken(["approvals", 0, "level"], True, _json("C02", 3))),
    ("审批编号不是十进制文本", t.CommandResult, _broken(["approvals", 0, "approvalId"], "A203", _json("C02", 3))),
    ("缺少 skipped", t.CommandResult, _broken(["skipped"], _DELETE, _json("C02", 2))),
    ("删除标记写成 1", t.CommandResult, _broken(["rows", 2, "deleted"], 1, _json("C02", 2))),
    ("删除标记写成 false", t.CommandResult, _broken(["rows", 2, "deleted"], False, _json("C02", 2))),
    ("提示同时给出 rowKey 和 clientRowId", t.CommandResult, _broken(["prompts", 0, "clientRowId"], _TMP, _json("C02", 2))),
    ("错误码不存在", t.ErrorResponse, _broken(["code"], "NO_SUCH_CODE", _json("C03", 0))),
    ("页面布局未知", t.PageView, _broken(["layout"], "grid", _json("C05", 0))),
    ("页面版本写成字符串", t.PageView, _broken(["version"], "13", _json("C05", 0))),
    ("审计开关写成 1", t.PageView, _broken(["audit"], 1, _json("C05", 0))),
    ("审计开关写成字符串", t.PageView, _broken(["audit"], "yes", _json("C05", 0))),
    ("配置时间带时区", t.ConfigItem, _broken(["updatedAt"], "2026-10-24T10:00:00+08:00", _json("C06", 0))),
    ("配置时间带 Z", t.ConfigItem, _broken(["updatedAt"], "2026-10-24T10:00:00Z", _json("C06", 0))),
    ("配置时间带小数秒", t.ConfigItem, _broken(["updatedAt"], "2026-10-24T10:00:00.5", _json("C06", 0))),
    ("配置时间用空格分隔", t.ConfigItem, _broken(["updatedAt"], "2026-10-24 10:00:00", _json("C06", 0))),
    ("配置时间是时间戳", t.ConfigItem, _broken(["updatedAt"], 1792800000, _json("C06", 0))),
    ("配置类型未知", t.ConfigItem, _broken(["type"], "widget", _json("C06", 0))),
    ("向导请求缺少 audit", t.WizardGenerateRequest,
     {"parentMenu": "cost", "pageCode": "P", "title": "T", "layout": "single", "detailMode": "tabs", "master": {}, "details": []}),
    ("向导请求缺少 detailMode", t.WizardGenerateRequest,
     {"parentMenu": "cost", "pageCode": "P", "title": "T", "layout": "single", "audit": True, "master": {}, "details": []}),
    ("Lookup 查询响应缺少 keywordSearch", t.LookupSearchResponse, {"rows": [], "total": 0}),
    ("Lookup 查询响应的 keywordSearch 写成 null", t.LookupSearchResponse, {"rows": [], "total": 0, "keywordSearch": None}),
    ("向导请求的 audit 写成 null", t.WizardGenerateRequest,
     {"parentMenu": "cost", "pageCode": "P", "title": "T", "layout": "single", "detailMode": "tabs", "audit": None,
      "master": {}, "details": []}),
    ("向导请求的 detailMode 写成 null", t.WizardGenerateRequest,
     {"parentMenu": "cost", "pageCode": "P", "title": "T", "layout": "single", "detailMode": None, "audit": True,
      "master": {}, "details": []}),
    # C06 第 1.1 节中决定行为、必须写出的字段
    ("页面缺少 audit", t.PageConfig, _broken(["audit"], _DELETE, _json("C06", 2))),
    ("页面缺少 detailMode", t.PageConfig, _broken(["detailMode"], _DELETE, _json("C06", 2))),
    ("操作缺少 propagation", t.OperationConfig, _broken(["propagation"], _DELETE, _json("C06", 3))),
    ("规则缺少 order", t.RuleConfig, _broken(["order"], _DELETE, _json("C06", 4))),
    ("审批流参数缺少 required", t.ApprovalFlowConfig, _broken(["params", 1, "required"], _DELETE, _FLOW_EXAMPLES)),
    ("角色缺少 admin", t.RoleConfig, _broken(["admin"], _DELETE, _json("C06", 9))),
    ("字典项缺少 order", t.DictConfig, _broken(["items", 0, "order"], _DELETE, _json("C06", 11))),
    ("Lookup 缺少 keywordColumns", t.LookupConfig, _broken(["keywordColumns"], _DELETE, _json("C06", 12))),
    ("Lookup 筛选写成空对象", t.PageConfig, _broken(["master", "fields", "GOODSID", "lookup", "filter"], {}, _PAGE_FIELD_EXAMPLES)),
    ("求值阶段未知", t.EvaluationRequest, _broken(["phase"], "draft", _json("C07", 1))),
    ("求值日期带时间", t.EvaluationRequest, _broken(["context", "today"], "2026-10-24T00:00:00", _json("C07", 1))),
    ("求值日期是时间戳", t.EvaluationRequest, _broken(["context", "today"], 1792800000, _json("C07", 1))),
    ("效果种类未知", t.EvaluationResult, _broken(["effects", 0, "kind"], "warn", _json("C07", 2))),
    ("计算结果缺少 effects", t.EvaluationResult, _broken(["effects"], _DELETE, _json("C07", 2))),
    ("计算结果只有 ok", t.EvaluationResult, {"ok": True}),
    ("ok 写成 1", t.EvaluationResult, _broken(["ok"], 1, _json("C07", 2))),
    ("失败结果的 ok 为 true", t.EvaluationResult, {"ok": True, "error": {"code": "PACK_INVALID", "message": "x"}}),
    ("失败结果缺少 error", t.EvaluationResult, {"ok": False}),
    ("结果行两种定位都没有", t.EvaluationResult, _broken(["rows", 0, "rowKey"], _DELETE, _json("C07", 2))),
    ("结果行两种定位都有", t.EvaluationResult, _broken(["rows", 0, "clientRowId"], _TMP, _json("C07", 2))),
    ("拒绝效果两种定位都有", t.EvaluationResult, _broken(["effects", 1, "clientRowId"], _TMP, _json("C07", 2))),
    ("请求的行两种定位都没有", t.EvaluationRequest, _broken(["document", "master", "rowKey"], _DELETE, _json("C07", 1))),
    ("请求的行两种定位都有", t.EvaluationRequest, _broken(["document", "details", "COST_MATERIAL", 1, "rowKey"], "5009", _json("C07", 1))),
    ("列表起始行写成字符串", t.ListRequest, _broken(["startRow"], "0", _json("C09", 0))),
    ("审批状态未知", t.ApprovalSummary, _broken(["status"], "done", _json("C09", 2))),
    ("提交时间带时区", t.ApprovalSummary, _broken(["submittedAt"], "2026-10-24T09:30:00Z", _json("C09", 2))),
    ("审批详情缺少来源单据", t.ApprovalDetail, _broken(["source"], _DELETE, _json("C09", 3))),
    ("审批详情缺少人工参数", t.ApprovalDetail, _broken(["params"], _DELETE, _json("C09", 3))),
    ("人工参数类型未知", t.ApprovalDetail, _broken(["params"], [{"name": "d", "label": "日期", "type": "time", "source": "manual"}],
                                            _json("C09", 3))),
    ("Lookup 的取值来源未知", t.PageView, _broken(["details", 0, "fields", 0, "lookup", "filter"],
                                          {"column": "GOODSTYPE", "from": "page"}, _json("C05", 0))),
    ("新增行的临时编号格式不对", t.EvaluationResult, _broken(["rows", 0, "clientRowId"], "new-1",
                                                     {"ok": True, "rows": [{"entity": "E", "computed": {}, "fields": {},
                                                                            "style": {"row": None, "cells": {}}}]})),
    ("勾选写成字符串", t.ApprovalDetail, _broken(["view", "affected", 0, "rows", 0, "checked"], "true", _json("C09", 3))),
    ("对比值不是十进制文本", t.DataRow,
     {**_ROW, "compare": {"PRICE": {"value": "3.5", "diff": "0.3", "percent": "8.57%"}}}),
    ("事件主题未知", t.ChannelEvent, _broken(["topic"], "other", _json("C10", 0))),
    ("服务端消息类型未知", t.ServerMessage, {"type": "hello"}),
]


@pytest.mark.parametrize(("name", "model", "data"), INVALID, ids=[s[0] for s in INVALID])
def test_invalid_sample_rejected(name: str, model: Any, data: Any) -> None:
    with pytest.raises(ValidationError):
        t.parse_wire(model, data)


def test_error_codes_map_to_c03_status() -> None:
    expected = {
        400: {"INVALID_REQUEST"},
        401: {"SESSION_REQUIRED", "SESSION_ROLE_REVOKED", "LOGIN_FAILED"},
        403: {"PERMISSION_DENIED", "CSRF_FAILED", "ORIGIN_REJECTED", "ROLE_SELECTION_REQUIRED"},
        404: {"NOT_FOUND"},
        409: {"DOCUMENT_BUSY", "REQUEST_IN_PROGRESS", "FROZEN_BY_APPROVAL",
              "RECONFIRM_REQUIRED", "ROW_NOT_FOUND", "APPROVAL_REQUIRED"},
        422: {"IDEMPOTENCY_KEY_REUSED", "RULE_REJECTED", "VALIDATION_FAILED", "FIELD_NOT_WRITABLE"},
        503: {"CONFIG_UNAVAILABLE", "DATABASE_UNAVAILABLE"},
        500: {"INTERNAL_ERROR"},
    }
    actual: dict[int, set[str]] = {}
    for code in t.ErrorCode:
        actual.setdefault(code.http_status, set()).add(code.value)
    assert actual == expected


def test_platform_error_carries_code_and_details() -> None:
    detail = t.ErrorDetail(message="PRICE 不能修改", entity="COST_GOODS_PRICE", row_key="115", field="PRICE")
    error = t.PlatformError(t.ErrorCode.FIELD_NOT_WRITABLE, "有字段不能修改", [detail])
    body = error.to_response()
    assert body.code is t.ErrorCode.FIELD_NOT_WRITABLE
    assert error.http_status == 422
    dumped = t.dump_wire(t.ErrorResponse, body)
    assert dumped["details"][0]["rowKey"] == "115"
    assert dumped["details"][0]["approvalId"] is None


def test_content_digest_ignores_request_key_and_whitespace() -> None:
    a = t.parse_wire(t.Command, _json("C02", 0))
    data = _json("C02", 0)
    data["requestKey"] = "00000000-0000-4000-8000-000000000000"
    b = t.parse_wire(t.Command, json.loads(json.dumps(data, indent=4)))
    assert a.content_digest() == b.content_digest()
    data["params"] = {"x": 1}
    c = t.parse_wire(t.Command, data)
    assert c.content_digest() != a.content_digest()


# ---------------------------------------------------------------- C04、C08 的类型和端口

_NOT_OURS = {"Protocol", "Exception", "Decimal", "ContextManager", "Connection", "Literal", "None", "True", "False"}


def _named_in_docs() -> set[str]:
    """C04、C08 代码块中定义或引用的类型名；注释中只取驼峰复合词，例如 AccountRef。"""
    names: set[str] = set()
    for prefix in ("C04", "C08"):
        for block in _blocks(prefix, "python"):
            for line in block.splitlines():
                code, _, comment = line.partition("#")
                names |= set(re.findall(r"\b[A-Z][A-Za-z]+\b", code))
                names |= set(re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", comment))
    return names - _NOT_OURS


def test_c04_c08_types_and_ports_defined() -> None:
    from cost_platform.contracts import ports

    names = _named_in_docs()
    assert len(names) > 40
    missing = sorted(n for n in names if not hasattr(t, n) and not hasattr(ports, n))
    assert missing == []


def _normalized_annotation(text: str) -> str:
    text = text.replace("sqlalchemy.engine.Connection", "Connection").replace("AbstractContextManager", "ContextManager")
    text = re.sub(r"Literal\[['\"]saved['\"], ['\"]unchanged['\"], ['\"]approvalSubmitted['\"], ['\"]approvalProcessed['\"]\]", "Outcome", text)
    text = re.sub(r"Literal\[['\"]add['\"], ['\"]modify['\"], ['\"]delete['\"]\]", "RowOp", text)
    return text


def _class_members(node: Any) -> tuple[dict[str, tuple[str, str | None]], dict[str, tuple[list[tuple[str, str]], list[str], str]]]:
    import ast

    fields, methods = {}, {}
    for s in node.body:
        if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name):
            fields[s.target.id] = (_normalized_annotation(ast.unparse(s.annotation)), None if s.value is None else ast.unparse(s.value))
        elif isinstance(s, ast.FunctionDef) and not s.name.startswith("_"):
            params = [(a.arg, _normalized_annotation(ast.unparse(a.annotation)) if a.annotation else "") for a in s.args.args[1:]]
            methods[s.name] = (params, [ast.unparse(d) for d in s.args.defaults],
                               _normalized_annotation(ast.unparse(s.returns)) if s.returns else "")
    return fields, methods


def _ast_classes(sources: list[str]) -> dict[str, Any]:
    import ast

    return {n.name: n for src in sources for n in ast.parse(src).body if isinstance(n, ast.ClassDef)}


# 实现中允许带默认值的字段：dataclass 的 field() 只设 repr/hash/compare 时没有默认值；CommandState、ChangePlan 的初始值见 C08 第 6 节的注释。
# RowIntent.copy_of（C08 v19）默认为 None：只有 approval 展开的复制出的待审新增行带它，其余意图不用写
_ALLOWED_DEFAULTS = {"CommandState", "ChangePlan", "RowIntent"}


def test_c04_c08_annotations_and_defaults_match() -> None:
    from cost_platform.contracts import ports

    contracts_dir = Path(t.__file__).parent
    impl = _ast_classes([(contracts_dir / f).read_text(encoding="utf-8") for f in ("types.py", "ports.py")])
    documented = _ast_classes(_blocks("C04", "python") + _blocks("C08", "python"))
    problems = []
    for name, node in documented.items():
        if name == "PlatformError":
            continue  # 属性在 __init__ 中赋值，参数名由 test_c04_c08_fields_and_signatures_match 检查
        if name not in impl:
            alias = getattr(t, name, None) or getattr(ports, name, None)
            if alias is None or alias.__name__ not in impl:
                problems.append(f"{name} 没有实现")
            continue
        doc_fields, doc_methods = _class_members(node)
        impl_fields, impl_methods = _class_members(impl[name])
        for field, (annotation, _) in doc_fields.items():
            actual, default = impl_fields.get(field, (None, None))
            if actual != annotation:
                problems.append(f"{name}.{field} 的类型 {actual} 与文档 {annotation} 不同")
            if default is not None and name not in _ALLOWED_DEFAULTS and not re.fullmatch(
                    r"dc_field\((?:(?:repr|hash|compare)=\w+(?:, )?)+\)", default):
                problems.append(f"{name}.{field} 有文档没有写的默认值 {default}")
        for method, signature in doc_methods.items():
            if impl_methods.get(method) != signature:
                problems.append(f"{name}.{method} 的签名 {impl_methods.get(method)} 与文档 {signature} 不同")
    assert problems == []


def _documented_classes() -> dict[str, tuple[list[str], dict[str, list[str]]]]:
    """C04、C08 代码块中每个类的字段名（按顺序）和方法的参数名（不含 self）。"""
    import ast

    found: dict[str, tuple[list[str], dict[str, list[str]]]] = {}
    for prefix in ("C04", "C08"):
        for block in _blocks(prefix, "python"):
            for node in ast.parse(block).body:
                if not isinstance(node, ast.ClassDef):
                    continue
                fields = [s.target.id for s in node.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
                methods = {s.name: [a.arg for a in s.args.args[1:] + s.args.kwonlyargs]
                           for s in node.body if isinstance(s, ast.FunctionDef)}
                found[node.name] = (fields, methods)
    return found


def test_c04_c08_fields_and_signatures_match() -> None:
    import dataclasses
    import inspect

    from cost_platform.contracts import ports

    problems = []
    documented = _documented_classes()
    assert len(documented) > 30
    for name, (fields, methods) in documented.items():
        impl = getattr(t, name, None) or getattr(ports, name)
        if dataclasses.is_dataclass(impl):
            actual_fields = [f.name for f in dataclasses.fields(impl)]
        elif isinstance(impl, type) and issubclass(impl, Exception):
            actual_fields = [p for p in inspect.signature(impl.__init__).parameters if p != "self"]
        else:
            actual_fields = list(getattr(impl, "__annotations__", {}))
        if actual_fields != fields:
            problems.append(f"{name} 的字段 {actual_fields} 与文档 {fields} 不同")
        for method, params in methods.items():
            func = getattr(impl, method, None)
            actual = None if func is None else [p for p in inspect.signature(func).parameters if p != "self"]
            if actual != params:
                problems.append(f"{name}.{method} 的参数 {actual} 与文档 {params} 不同")
    assert problems == []
