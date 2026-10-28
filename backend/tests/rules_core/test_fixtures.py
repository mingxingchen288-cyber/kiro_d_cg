"""rules-core 样例集在 Python 包上运行（C07 第 6 节），以及 T-RC-2 验收中的几条性质。"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# 没有装 rules-core 的 wheel 时（backend 依赖里还没有它，由 assembly 接入），整个模块跳过，不影响 backend 其余测试的收集
cost_rules_core = pytest.importorskip("cost_rules_core", reason="需要 rules-core 的 wheel：uv run --with <wheel> pytest tests/rules_core")

from cost_rules_core import RulesEngine  # noqa: E402

from cost_platform.contracts.types import PackInvalidError  # noqa: E402

from .support import case, cases, pack_bytes, request_text  # noqa: E402

ENGINE = RulesEngine()
EVALUATE = [c for c in cases() if c["kind"] == "evaluate"]
CONSISTENCY = [x for c in cases() if c["kind"] == "consistency" for x in c["cases"]]


@pytest.mark.parametrize("item", EVALUATE, ids=[c["name"] for c in EVALUATE])
def test_evaluate(item: dict) -> None:
    handle = ENGINE.load_pack(pack_bytes(item["pack"]))
    result = ENGINE.evaluate(handle, request_text(item["request"]))
    if item["match"] == "errorCode":
        got = json.loads(result)
        assert got["ok"] is False and got["error"]["code"] == item["expected"]["error"]["code"]
    else:
        assert cost_rules_core.compare_json(result, json.dumps(item["expected"], ensure_ascii=False)) == []


@pytest.mark.parametrize("item", CONSISTENCY, ids=[f"{x['a']}~{x['b']}" for x in CONSISTENCY])
def test_c01_boundary(item: dict) -> None:
    """C01 第 3 节的边界样例，用 Rust 版判定。"""
    assert cost_rules_core.numbers_consistent(item["a"], item["b"]) is item["consistent"]


def test_cycle_is_pack_invalid() -> None:
    """跨实体依赖成环：load_pack 抛 PackInvalidError，列出环上的规则（RC-09）。"""
    item = next(c for c in cases() if c["kind"] == "packInvalid")
    with pytest.raises(PackInvalidError) as caught:
        ENGINE.load_pack(pack_bytes(item["pack"]))
    for rule in item["expected"]["messageContains"]:
        assert rule in caught.value.message


def test_repeated_evaluate_does_not_recompile() -> None:
    """同一规则包重复求值不重新编译（RC-03）。"""
    item = case("成本核算-单据200726")
    handle = ENGINE.load_pack(pack_bytes(item["pack"]))
    before = cost_rules_core.compile_count()
    first = ENGINE.evaluate(handle, request_text(item["request"]))
    for _ in range(20):
        assert ENGINE.evaluate(handle, request_text(item["request"])) == first
    assert cost_rules_core.compile_count() == before


DEMO = case("精度和old-preview")
DEMO_HANDLE = ENGINE.load_pack(pack_bytes(DEMO["pack"]))
decimals = st.decimals(min_value=Decimal("-1000000"), max_value=Decimal("1000000"), places=6, allow_nan=False, allow_infinity=False)
_MAX = Decimal(2**96 - 1)


def fit28(x: Decimal) -> Decimal:
    """按 rust_decimal 的精度取值：尾数不超过 96 位、小数位不超过 28（"28 位有效数字"）。"""
    for scale in range(28, -1, -1):
        q = x.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_EVEN)
        if abs(q.scaleb(scale)) <= _MAX:
            return q
    raise OverflowError(x)


@settings(max_examples=200, deadline=None)
@given(qty=decimals, price=decimals)
def test_same_request_same_result_and_full_precision(qty: Decimal, price: Decimal) -> None:
    """同一请求求值两次结果相同；上游结果按全部精度参与下游计算：THIRD = QTY / 3，BACK = THIRD * 3，
    结果与逐步按 28 位有效数字计算的值相同，不因中间舍入改变。"""
    request = json.loads(json.dumps(DEMO["request"]))
    request["document"]["master"]["values"].update({"QTY": format(qty, "f"), "PRICE": format(price, "f")})
    text = request_text(request)
    first = ENGINE.evaluate(DEMO_HANDLE, text)
    assert ENGINE.evaluate(DEMO_HANDLE, text) == first
    computed = json.loads(first)["rows"][0]["computed"]
    with localcontext() as ctx:
        ctx.prec = 80
        third = fit28(qty / 3)
        assert Decimal(computed["THIRD"]) == third
        assert Decimal(computed["BACK"]) == fit28(third * 3)
        assert Decimal(computed["AMOUNT"]) == fit28(qty * price)
