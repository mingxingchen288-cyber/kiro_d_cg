"""T-CT-1：契约文档中的每个 JSON 样例都能解析成类型，再转回 JSON 后内容不变。

样例直接从 docs/契约/ 中读取，文档改了样例，这里自动跟着验证。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from cost_platform.contracts import types as t

DOCS = Path(__file__).resolve().parents[3] / "docs" / "契约"


def _blocks(prefix: str) -> list[str]:
    text = next(DOCS.glob(f"{prefix}-*.md")).read_text(encoding="utf-8")
    return re.findall(r"```json\n(.*?)```", text, flags=re.S)


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

SAMPLES: list[tuple[str, Any, type[BaseModel]]] = [
    ("C02 页面保存", _json("C02", 0), t.Command),
    ("C02 审批处理", _json("C02", 1), t.Command),
    ("C02 已写入", _json("C02", 2), t.CommandResult),
    ("C02 已提交审批", _json("C02", 3), t.CommandResult),
    ("C03 错误", _json("C03", 0), t.ErrorResponse),
    ("C05 页面视图", _json("C05", 0), t.PageView),
    ("C06 配置项", _json("C06", 0), t.ConfigItem),
    ("C06 entity", _json("C06", 1), t.EntityConfig),
    ("C06 page", _json("C06", 2), t.PageConfig),
    ("C06 operation", _json("C06", 3), t.OperationConfig),
    ("C06 计算规则", _json("C06", 4), t.RuleConfig),
    ("C06 界面规则", _json("C06", 5), t.RuleConfig),
    ("C06 审批流样例一", FLOW_1, t.ConfigDraft),
    ("C06 审批流样例一的内容", FLOW_1["content"], t.ApprovalFlowConfig),
    ("C06 审批流样例二", FLOW_2, t.ConfigDraft),
    ("C06 审批流样例二的内容", FLOW_2["content"], t.ApprovalFlowConfig),
    ("C06 role", _json("C06", 10), t.RoleConfig),
    ("C06 menu", _json("C06", 11), t.MenuConfig),
    ("C06 dict", _json("C06", 12), t.DictConfig),
    ("C06 lookup", _json("C06", 13), t.LookupConfig),
    ("C06 export", _json("C06", 14), t.ExportConfig),
    ("C07 规则包", _json("C07", 0), t.RulesPack),
    ("C07 求值请求", _json("C07", 1), t.EvaluationRequest),
    ("C07 求值结果", _json("C07", 2), t.EvaluationResult),
    ("C09 列表请求", _json("C09", 0), t.ListRequest),
    ("C09 个人配置", _json("C09", 1), t.PersonalConfig),
    ("C09 待办摘要", _json("C09", 2), t.ApprovalSummary),
    ("C09 审批详情", _json("C09", 3), t.ApprovalDetail),
    ("C10 频道事件", _json("C10", 0), t.ChannelEvent),
    *[(f"C10 浏览器消息 {i}", m, t.ClientMessage) for i, m in enumerate(_lines("C10", 1))],
    *[(f"C10 服务端消息 {i}", m, t.ServerMessage) for i, m in enumerate(_lines("C10", 2))],
]


def _roundtrip(model: type[BaseModel], data: Any) -> Any:
    adapter = t.adapter(model)
    value = adapter.validate_python(data)
    return adapter.dump_python(value, mode="json", by_alias=True, exclude_unset=True)


@pytest.mark.parametrize(("name", "data", "model"), SAMPLES, ids=[s[0] for s in SAMPLES])
def test_sample_roundtrip(name: str, data: Any, model: type[BaseModel]) -> None:
    assert _roundtrip(model, data) == data


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


_DELETE = object()

INVALID = [
    ("请求键不是 UUID", t.Command, _broken(["requestKey"], "abc", _json("C02", 0))),
    ("请求键为大写", t.Command, _broken(["requestKey"], "3F2B6C1E-8A4D-4C2E-9B1A-0D6E5F7A8B9C", _json("C02", 0))),
    ("缺少请求键", t.Command, _broken(["requestKey"], _DELETE, _json("C02", 0))),
    ("未知的行操作", t.Command, _broken(["documents", 0, "master", "op"], "upsert", _json("C02", 0))),
    ("多出未定义的字段", t.Command, _broken(["extra"], 1, _json("C02", 0))),
    ("修改行缺少 rowKey", t.Command, _broken(["documents", 0, "master", "rowKey"], _DELETE, _json("C02", 0))),
    ("新增行缺少 clientRowId", t.Command, _broken(["documents", 0, "details", 0, "clientRowId"], _DELETE, _json("C02", 0))),
    ("临时编号格式不对", t.Command, _broken(["documents", 0, "details", 0, "clientRowId"], "new-1", _json("C02", 0))),
    ("未知的结果", t.CommandResult, _broken(["outcome"], "done", _json("C02", 2))),
    ("错误码不存在", t.ErrorResponse, _broken(["code"], "NO_SUCH_CODE", _json("C03", 0))),
    ("新增行带 rowKey", t.Command, _broken(["documents", 0, "details", 0, "rowKey"], "9", _json("C02", 0))),
    ("业务值用了 JSON 数字", t.Command, _broken(["documents", 0, "master", "changes", "QTY"], 12, _json("C02", 0))),
    ("删除的行带 values", t.CommandResult, _broken(["rows", 2, "values"], {"DTLID": "5002"}, _json("C02", 2))),
    ("页面布局未知", t.PageView, _broken(["layout"], "grid", _json("C05", 0))),
    ("表单布局越出 24 列", t.PageView, _broken(["master", "formLayout", 0, "x"], 13, _json("C05", 0))),
    ("单表页带明细", t.PageView, _broken(["layout"], "single", _json("C05", 0))),
    ("冻结方式未知", t.ApprovalFlowConfig, _broken(["freeze", 0, "kind"], "rows", FLOW_1["content"])),
    ("没有查找目标却冻结候选对象", t.ApprovalFlowConfig, _broken(["targets"], _DELETE, FLOW_1["content"])),
    ("审批流没有触发操作", t.ApprovalFlowConfig, _broken(["trigger", "operations"], [], FLOW_1["content"])),
    ("审批流级别不连续", t.ApprovalFlowConfig, _broken(["levels", 0, "level"], 2, FLOW_1["content"])),
    ("来源从表取了候选单据的字段", t.ApprovalFlowConfig,
     _broken(["display", "details", 0, "columns", 0, "field"], "target.DOCID", FLOW_1["content"])),
    ("通用动作未知", t.ApprovalFlowConfig, _broken(["afterApproval", 0, "action"], "sync", FLOW_1["content"])),
    ("计算规则缺少字段", t.RuleConfig, _broken(["field"], None, _json("C06", 4))),
    ("求值阶段未知", t.EvaluationRequest, _broken(["phase"], "draft", _json("C07", 1))),
    ("效果种类未知", t.EvaluationResult, _broken(["effects", 0, "kind"], "warn", _json("C07", 2))),
    ("失败的求值结果缺少 error", t.EvaluationResult, _broken(["ok"], False, _json("C07", 2))),
    ("审批状态未知", t.ApprovalSummary, _broken(["status"], "done", _json("C09", 2))),
    ("审批详情单元格数与列数不同", t.ApprovalDetail,
     _broken(["view", "master", "rows", 0, "cells"], [{"before": "115", "after": "115"}], _json("C09", 3))),
    ("结果指纹格式不对", t.ApprovalDetail, _broken(["fingerprint"], "abc", _json("C09", 3))),
    ("事件主题未知", t.ChannelEvent, _broken(["topic"], "other", _json("C10", 0))),
]


@pytest.mark.parametrize(("name", "model", "data"), INVALID, ids=[s[0] for s in INVALID])
def test_invalid_sample_rejected(name: str, model: type[BaseModel], data: Any) -> None:
    with pytest.raises(ValidationError):
        t.adapter(model).validate_python(data)


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
    dumped = t.adapter(t.ErrorResponse).dump_python(body, mode="json", by_alias=True)
    assert dumped["details"][0]["rowKey"] == "115"


def test_content_digest_ignores_request_key_and_whitespace() -> None:
    a = t.Command.model_validate(_json("C02", 0))
    data = _json("C02", 0)
    data["requestKey"] = "00000000-0000-4000-8000-000000000000"
    b = t.Command.model_validate(json.loads(json.dumps(data, indent=4)))
    assert a.content_digest() == b.content_digest()
    data["params"] = {"x": 1}
    c = t.Command.model_validate(data)
    assert c.content_digest() != a.content_digest()


_NOT_OURS = {"Protocol", "Exception", "Decimal", "ContextManager", "Connection", "Literal", "None", "True", "False"}


def _python_blocks(prefix: str) -> list[str]:
    text = next(DOCS.glob(f"{prefix}-*.md")).read_text(encoding="utf-8")
    return re.findall(r"```python\n(.*?)```", text, flags=re.S)


def _named_in_docs() -> set[str]:
    """C04、C08 代码块中定义或引用的类型名；注释中只取驼峰复合词，例如 AccountRef。"""
    names: set[str] = set()
    for prefix in ("C04", "C08"):
        for block in _python_blocks(prefix):
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
