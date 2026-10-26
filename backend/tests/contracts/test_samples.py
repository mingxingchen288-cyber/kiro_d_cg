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


def _fragment(prefix: str, index: int) -> Any:
    """C06 7.6 的 `"display": {…}` 是审批流中的片段，补上外层花括号再解析。"""
    return json.loads("{" + _blocks(prefix)[index] + "}")["display"]


def _flow(index: int, display_index: int) -> Any:
    """C06 7.4、7.5 的审批流样例中，display 写的是"见 7.6"，换成 7.6 对应的片段。"""
    data = _json("C06", index)
    data["content"]["display"] = _fragment("C06", display_index)
    return data


# C06 第 7.6 节先给物料清单改价（样例二，块 8），再给成本核算改价（样例一，块 9）。
FLOW_1 = _flow(6, 9)
FLOW_2 = _flow(7, 8)

_UUID = "3f2b6c1e-8a4d-4c2e-9b1a-0d6e5f7a8b9c"
_TMP = "tmp-6a1f2c3d-0b4e-4f5a-8c7d-9e0f1a2b3c4d"
_FP = "sha256:5b1e0c6d9a3f47e28b1c6d0e9f3a2b4c5d6e7f8091a2b3c4d5e6f708192a3b4c"
_ROW = {"rowKey": "1001", "values": {"QTY": "12"}, "frozen": None}


def _command(document: Any) -> Any:
    return {"requestKey": _UUID, "page": "COST_PINGGU", "operation": "COST_PINGGU.save", "documents": [document], "params": {}}


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
    ("C03 错误", _json("C03", 0), t.ErrorResponse),
    ("C05 页面视图", _json("C05", 0), t.PageView),
    ("C06 配置项", _json("C06", 0), t.ConfigItem),
    ("C06 审批流样例一", FLOW_1, t.ConfigDraft),
    ("C06 审批流样例二", FLOW_2, t.ConfigDraft),
    ("C07 规则包", _json("C07", 0), t.RulesPack),
    ("C07 求值请求", _json("C07", 1), t.EvaluationRequest),
    ("C07 求值结果", _json("C07", 2), t.EvaluationResult),
    ("C07 审批入口结果", {"ok": True, "satisfied": True}, t.EvaluationResult),
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
                       "master": {}, "details": []}, t.WizardGenerateRequest),
    ("C09 列表响应", {"rows": [_ROW], "total": 1234, "aggregates": {"TOTAL_COST": "98765.43"}}, t.ListResponse),
    ("C09 按主键读行", {"entity": "COST_PINGGU", "rowKeys": ["1001", "1002"]}, t.ByKeysRequest),
    ("C09 单据响应", {"master": _ROW, "details": {"COST_MATERIAL": [_ROW]}}, t.RecordResponse),
    ("C09 Lookup 查询请求", {"keyword": "胶", "filter": {"column": "GOODSTYPE", "value": "瓶"}, "startRow": 0, "endRow": 50},
     t.LookupSearchRequest),
    ("C09 Lookup 查询响应", {"rows": [{"values": {"GOODSID": "115", "NAME": "胶囊壳"}}], "total": 3}, t.LookupSearchResponse),
    ("C09 字典", {"items": [{"value": "1", "label": "启用"}]}, t.DictResponse),
    ("C09 导出列表", {"items": [{"exportCode": "cost-pinggu-export", "name": "物料成本核算表导出"}]}, t.ExportList),
    ("C09 默认导出", {"mode": "page", "request": _json("C09", 0), "columns": ["DOCID", "GOODSNAME"]}, t.ExportRequest),
    ("C09 按配置导出", {"mode": "config", "exportCode": "cost-pinggu-export", "scope": "current", "request": _json("C09", 0)},
     t.ExportRequest),
    ("C09 通过请求", {"requestKey": _UUID, "fingerprint": _FP, "selectedObjects": [{"flow": "GOODS_TO_COST", "entity": "COST_PINGGU",
                                                                                  "recordKey": "2550"}],
                    "comment": "价格已核对", "params": {"effectiveDate": "2026-11-01"}}, t.PassRequest),
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
]

# C06 的配置内容由管理员编写，原样保存；模型只用于读取和校验结构，所以只比较解析时给出的字段（exclude_unset）。
CONFIG_CONTENTS: list[tuple[str, Any, Any]] = [
    ("C06 entity", _json("C06", 1), t.EntityConfig),
    ("C06 page", _json("C06", 2), t.PageConfig),
    ("C06 operation", _json("C06", 3), t.OperationConfig),
    ("C06 计算规则", _json("C06", 4), t.RuleConfig),
    ("C06 界面规则", _json("C06", 5), t.RuleConfig),
    ("C06 审批流样例一的内容", FLOW_1["content"], t.ApprovalFlowConfig),
    ("C06 审批流样例二的内容", FLOW_2["content"], t.ApprovalFlowConfig),
    ("C06 role", _json("C06", 10), t.RoleConfig),
    ("C06 menu", _json("C06", 11), t.MenuConfig),
    ("C06 dict", _json("C06", 12), t.DictConfig),
    ("C06 lookup", _json("C06", 13), t.LookupConfig),
    ("C06 export", _json("C06", 14), t.ExportConfig),
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
                                                  "field": "PRICE", "approvalId": None}
    with pytest.raises(ValidationError):
        t.ResultRow(entity="COST_PINGGU", row_key="1001", values={})  # type: ignore[call-arg]  # 未冻结时也必须给出 frozen=None


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
    ("冻结方式未知", t.ApprovalFlowConfig, _broken(["freeze", 0, "kind"], "rows", FLOW_1["content"])),
    ("通用动作未知", t.ApprovalFlowConfig, _broken(["afterApproval", 0, "action"], "sync", FLOW_1["content"])),
    ("触发操作未知", t.ApprovalFlowConfig, _broken(["trigger", "operations"], ["upsert"], FLOW_1["content"])),
    ("展示列的字段写法不对", t.ApprovalFlowConfig,
     _broken(["display", "details", 0, "columns", 0, "field"], "COST_MATERIAL.GOODSID", FLOW_1["content"])),
    ("求值阶段未知", t.EvaluationRequest, _broken(["phase"], "draft", _json("C07", 1))),
    ("求值日期带时间", t.EvaluationRequest, _broken(["context", "today"], "2026-10-24T00:00:00", _json("C07", 1))),
    ("求值日期是时间戳", t.EvaluationRequest, _broken(["context", "today"], 1792800000, _json("C07", 1))),
    ("效果种类未知", t.EvaluationResult, _broken(["effects", 0, "kind"], "warn", _json("C07", 2))),
    ("列表起始行写成字符串", t.ListRequest, _broken(["startRow"], "0", _json("C09", 0))),
    ("审批状态未知", t.ApprovalSummary, _broken(["status"], "done", _json("C09", 2))),
    ("提交时间带时区", t.ApprovalSummary, _broken(["submittedAt"], "2026-10-24T09:30:00Z", _json("C09", 2))),
    ("审批详情缺少来源单据", t.ApprovalDetail, _broken(["source"], _DELETE, _json("C09", 3))),
    ("可勾选写成字符串", t.ApprovalDetail, _broken(["view", "details", 0, "targets", 0, "selectable"], "true", _json("C09", 3))),
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
