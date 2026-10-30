"""校验只检查本次新增、修改的行（C07 v5、rules-core RC-10）：页面保存经 write-pipeline 生成 commit 阶段的求值请求，
用 rules-core 的真实 wheel 和 `backend/seed/config` 的成本核算规则（R_MAT_PER_HL_GT0："每片含量必填且必须大于0"）求值。

数据取 d_cg 单据 2757（rules-core 样例 21–24 的请求）：原辅料"30%过氧化氢溶液"（207577）每片含量为 0、单价为空。
- 只改硬脂酸镁（207584）的单价 54 → 55：changed 只有这一行，没有修改的 207577 不检查，保存成功；
- 改 207577 的单价（空 → 12）：422 RULE_REJECTED，提示"每片含量必填且必须大于0"，定位到 207577 的 PER_HL，不写库。
两个新单价都是假设的修改。

C07 v7 起计算带出变化的行也校验（文件末尾两个测试，只改主表批量）：
- 单据 2712（样例 31，明胶空心胶囊的每片含量假设为 0）：胶囊的每批数量按批量算，跟着变了，被拒绝；
- 单据 2757（样例 33）：过氧化氢溶液的每批数量仍是 0，不检查，保存成功。

C07 v8 起算出的值先按 WP-15 处理再比较（最后一个测试）：单据 2712（样例 35）胶囊每批成本算出超过 8 位小数，
处理后与库里相同，只改硬脂酸镁的单价时不被它拒绝。

运行：`uv run --with <wheel> pytest tests/pipeline/test_validate_changed_rows.py`；没有装 wheel 时整个文件跳过。
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from cost_platform.contracts import types as t
from cost_platform.contracts.values import from_wire

from .support import MemoryStore, Pipeline, Setup, command, master_modify, master_none

cost_rules_core = pytest.importorskip("cost_rules_core", reason="需要 rules-core 的 wheel：uv run --with <wheel> pytest tests/pipeline")
from cost_rules_core import RulesEngine  # noqa: E402

from tests.config.support import Env, seed_drafts  # noqa: E402

ENGINE = RulesEngine()
CASES = Path(__file__).resolve().parents[3] / "rules-core" / "fixtures" / "cases"
MASTER, MATERIAL, PACKAGE = "COST_PINGGU", "COST_MATERIAL", "COST_PACKAGE"
PER_HL_MESSAGE = "每片含量必填且必须大于0"


class RecordingEngine:
    """真实的 rules-core，另记下 write-pipeline 发出的求值请求。"""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def load_pack(self, data: bytes) -> Any:
        return ENGINE.load_pack(data)

    def evaluate(self, handle: Any, request_json: str) -> str:
        self.requests.append(json.loads(request_json))
        return ENGINE.evaluate(handle, request_json)

    def core_version(self) -> str:
        return ENGINE.core_version()


class SeedStore(MemoryStore):
    """`MemoryStore` 换成 seed 的实体（成本核算主表、原辅料、包材）。"""

    def __init__(self, entities: dict[str, t.EntityConfig], rows: dict[str, dict[str, dict[str, Any]]]) -> None:
        super().__init__(rows)
        self._entities = entities

    def _code(self, entity: t.EntityConfig) -> str:
        return next(code for code, e in self._entities.items() if e is entity)


def _snapshot() -> Any:
    env = Env(engine=ENGINE)
    env.save(seed_drafts())
    return env.reader.read("ADMIN")


def _rows_2757(snapshot: Any, case: str = "22") -> dict[str, dict[str, dict[str, Any]]]:
    """单据在数据库中的值：取样例 `case`（默认 22，单据 2757）的请求，改过的行（含主表）用它的 `old` 还原。"""
    path = next(p for p in CASES.glob(f"{case}-*.json"))
    document = json.loads(path.read_text(encoding="utf-8"))["request"]["document"]

    def stored(entity: str, item: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        types = {f.name: f.type for f in snapshot.entity(entity).fields}
        wire = {**item["values"], **(item.get("old") or {})}
        return item["rowKey"], {name: from_wire(types[name], value) for name, value in wire.items() if name in types}

    rows: dict[str, dict[str, dict[str, Any]]] = {MASTER: dict([stored(MASTER, document["master"])])}
    for entity in (MATERIAL, PACKAGE):
        rows[entity] = dict(stored(entity, item) for item in document["details"][entity])
    return rows


def _context(snapshot: Any) -> t.ExecutionContext:
    identity = t.Identity(user_id="1", username="admin", display_name="管理员", department_id="10", role_code="ADMIN",
                          session_id="s-1")
    return t.ExecutionContext(request_id="00000000-0000-4000-8000-0000000000bb", identity=identity, config=snapshot,
                              config_version=1, origin=t.Origin(kind="user", approval_id=None), now=datetime(2026, 10, 30, 10, 0))


def _save_price(row_key: str, price: str, case: str = "22",
                docid: str = "2757") -> tuple[Pipeline, RecordingEngine, t.ExecutionContext, t.Command]:
    """页面保存只改一行原辅料的单价，数据库中的值取样例 `case` 的请求（默认单据 2757）。"""
    snapshot = _snapshot()
    engine = RecordingEngine()
    entities = {code: snapshot.entity(code) for code in (MASTER, MATERIAL, PACKAGE)}
    pipeline = Pipeline(setup=Setup(engine=engine), store=SeedStore(entities, _rows_2757(snapshot, case)))  # type: ignore[arg-type]
    cmd = command([master_none(docid, [{"entity": MATERIAL, "op": "modify", "rowKey": row_key, "changes": {"PRICE": price}}])])
    return pipeline, engine, _context(snapshot), cmd


def _save_batch(case: str, record_key: str, batch: str) -> tuple[Pipeline, RecordingEngine, t.ExecutionContext, t.Command]:
    """页面保存只改主表批量（APEX_PL），数据库中的值取样例 `case` 的请求。"""
    snapshot = _snapshot()
    engine = RecordingEngine()
    entities = {code: snapshot.entity(code) for code in (MASTER, MATERIAL, PACKAGE)}
    pipeline = Pipeline(setup=Setup(engine=engine), store=SeedStore(entities, _rows_2757(snapshot, case)))  # type: ignore[arg-type]
    cmd = command([master_modify(record_key, {"APEX_PL": batch})])
    return pipeline, engine, _context(snapshot), cmd


def test_2757_change_another_row_price_saves() -> None:
    """改硬脂酸镁的单价：changed 只有 207584，过氧化氢溶液（每片含量为 0）没有修改、不检查，保存成功。"""
    pipeline, engine, ctx, cmd = _save_price("207584", "55")
    result = pipeline.execute(cmd, ctx)
    assert result.outcome == "saved"
    [request] = engine.requests
    assert request["phase"] == "commit"
    assert request["changed"] == [{"entity": MATERIAL, "rowKey": "207584", "op": "modify", "fields": ["PRICE"]}]
    updated = [r for w in pipeline.store.writes if w.op == "update" and w.entity == MATERIAL for r in w.rows]
    assert any(r["rowKey"] == "207584" and r["PRICE"] == 55 for r in updated)
    assert pipeline.store.rows[MATERIAL]["207584"]["PRICE"] == 55
    assert result.prompts == []


def test_2757_change_zero_per_hl_row_price_rejected() -> None:
    """改过氧化氢溶液自己的单价：这一行本次修改了，按 R_MAT_PER_HL_GT0 拒绝，定位到它的每片含量，不写库。"""
    pipeline, engine, ctx, cmd = _save_price("207577", "12")
    with pytest.raises(t.PlatformError) as caught:
        pipeline.execute(cmd, ctx)
    assert caught.value.code is t.ErrorCode.RULE_REJECTED
    assert caught.value.message == PER_HL_MESSAGE
    assert [(d.message, d.entity, d.row_key, d.field) for d in caught.value.details] == [
        (PER_HL_MESSAGE, MATERIAL, "207577", "PER_HL")]
    [request] = engine.requests
    assert request["changed"] == [{"entity": MATERIAL, "rowKey": "207577", "op": "modify", "fields": ["PRICE"]}]
    assert pipeline.store.writes == []
    assert pipeline.store.rows[MATERIAL]["207577"]["PRICE"] is None


# C07 v7：计算带出变化的行也校验（旧系统 useCalcBroadcast.ts 把计算带出的变化记成修改，useWorkingSetStore.ts 保存时校验有修改的行）。
# 页面保存只改主表批量，changed 只有主表行；每批数量因此变化的原辅料行由 rules-core 按 old 判断为有修改。


def test_2712_change_batch_capsule_zero_per_hl_rejected() -> None:
    """单据 2712（样例 31，明胶空心胶囊 104679 的每片含量假设为 0）：批量 20000 → 30000，胶囊的每批数量按批量算 2 → 3，
    这一行计算带出了变化，按 R_MAT_PER_HL_GT0 拒绝，定位到它的每片含量，不写库。"""
    pipeline, engine, ctx, cmd = _save_batch("31", "2712", "30000")
    with pytest.raises(t.PlatformError) as caught:
        pipeline.execute(cmd, ctx)
    assert caught.value.code is t.ErrorCode.RULE_REJECTED
    assert caught.value.message == PER_HL_MESSAGE
    assert [(d.message, d.entity, d.row_key, d.field) for d in caught.value.details] == [
        (PER_HL_MESSAGE, MATERIAL, "104679", "PER_HL")]
    [request] = engine.requests
    assert request["changed"] == [{"entity": MASTER, "rowKey": "2712", "op": "modify", "fields": ["APEX_PL"]}]
    assert request["document"]["master"]["old"] == {"APEX_PL": "20000"}
    assert pipeline.store.writes == []
    assert pipeline.store.rows[MASTER]["2712"]["APEX_PL"] == 20000


def test_2757_change_batch_saves() -> None:
    """单据 2757（样例 33）：批量 1600000 → 1700000，过氧化氢溶液（207577，每片含量为 0）的每批数量仍是 0、没有变化，不检查；
    每批数量变了的原辅料都检查并通过，保存成功，207577 不写。"""
    pipeline, engine, ctx, cmd = _save_batch("33", "2757", "1700000")
    result = pipeline.execute(cmd, ctx)
    assert result.outcome == "saved"
    [request] = engine.requests
    assert request["changed"] == [{"entity": MASTER, "rowKey": "2757", "op": "modify", "fields": ["APEX_PL"]}]
    updated = {r["rowKey"]: r for w in pipeline.store.writes if w.op == "update" and w.entity == MATERIAL for r in w.rows}
    assert updated["207584"]["BATCH_QTY"] == Decimal("0.51")
    assert "207577" not in updated
    assert pipeline.store.rows[MASTER]["2757"]["APEX_PL"] == 1700000
    assert result.prompts == []


# C07 v8：算出的值先按 WP-15 处理成保存后的值再与 old 比较。


def test_2712_more_than_8_places_row_not_checked() -> None:
    """单据 2712（样例 35）：明胶空心胶囊 104679 的每片含量假设为 0、单价假设为 18.3333333333，库里每批成本是 36.66666667。
    只改硬脂酸镁（104670）的单价 63 → 64：胶囊每批成本算出 36.6666666666，按 WP-15 处理后与库里相同，不算变化、不检查，
    保存成功，104679 不写。"""
    pipeline, engine, ctx, cmd = _save_price("104670", "64", case="35", docid="2712")
    assert pipeline.store.rows[MATERIAL]["104679"]["COST_BATCH"] == Decimal("36.66666667")
    result = pipeline.execute(cmd, ctx)
    assert result.outcome == "saved"
    [request] = engine.requests
    assert request["changed"] == [{"entity": MATERIAL, "rowKey": "104670", "op": "modify", "fields": ["PRICE"]}]
    updated = {r["rowKey"]: r for w in pipeline.store.writes if w.op == "update" and w.entity == MATERIAL for r in w.rows}
    assert updated["104670"]["PRICE"] == 64
    assert "104679" not in updated
    assert result.prompts == []
