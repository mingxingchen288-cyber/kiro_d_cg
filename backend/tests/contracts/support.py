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
