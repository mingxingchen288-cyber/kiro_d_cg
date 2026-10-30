"""校验只检查本次新增、修改的行（C07 v5、rules-core RC-10）：页面保存经 write-pipeline 生成 commit 阶段的求值请求，
用 rules-core 的真实 wheel 和 `backend/seed/config` 的成本核算规则（R_MAT_PER_HL_GT0："每片含量必填且必须大于0"）求值。

数据取 d_cg 单据 2757（rules-core 样例 21–24 的请求）：原辅料"30%过氧化氢溶液"（207577）每片含量为 0、单价为空。
- 只改硬脂酸镁（207584）的单价 54 → 55：changed 只有这一行，没有修改的 207577 不检查，保存成功；
- 改 207577 的单价（空 → 12）：422 RULE_REJECTED，提示"每片含量必填且必须大于0"，定位到 207577 的 PER_HL，不写库。
两个新单价都是假设的修改。

运行：`uv run --with <wheel> pytest tests/pipeline/test_validate_changed_rows.py`；没有装 wheel 时整个文件跳过。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from cost_platform.contracts import types as t
from cost_platform.contracts.values import from_wire

from .support import MemoryStore, Pipeline, Setup, command, master_none

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


def _rows_2757(snapshot: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """单据 2757 在数据库中的值：取样例 22 的请求，改过的那一行用它的 `old` 还原。"""
    path = next(p for p in CASES.glob("22-*.json"))
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


def _save_price(row_key: str, price: str) -> tuple[Pipeline, RecordingEngine, t.ExecutionContext, t.Command]:
    snapshot = _snapshot()
    engine = RecordingEngine()
    entities = {code: snapshot.entity(code) for code in (MASTER, MATERIAL, PACKAGE)}
    pipeline = Pipeline(setup=Setup(engine=engine), store=SeedStore(entities, _rows_2757(snapshot)))  # type: ignore[arg-type]
    cmd = command([master_none("2757", [{"entity": MATERIAL, "op": "modify", "rowKey": row_key, "changes": {"PRICE": price}}])])
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
