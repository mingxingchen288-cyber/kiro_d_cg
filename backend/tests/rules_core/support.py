"""rules-core 样例集（rules-core/fixtures/）的读取。这些测试需要 rules-core 的 Python 包：

    uv run --with ..\\rules-core\\dist\\python\\cost_rules_core-0.1.0-cp313-cp313-win_amd64.whl pytest tests/rules_core
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[3] / "rules-core" / "fixtures"


def cases() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((FIXTURES / "cases").glob("*.json"))]


def pack_bytes(rel: str) -> bytes:
    return (FIXTURES / rel).read_bytes()


def request_text(request: dict[str, Any]) -> str:
    """与浏览器端 JSON.stringify 相同的紧凑写法，两端收到同样的文本。"""
    return json.dumps(request, ensure_ascii=False, separators=(",", ":"))


def case(name: str) -> dict[str, Any]:
    return next(c for c in cases() if c["name"] == name)
