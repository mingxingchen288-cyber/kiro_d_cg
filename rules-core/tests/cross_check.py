"""两端逐条比较（C07 第 4、6 节，工程约定第 6 节）：样例集在 Python 包上求值，与浏览器的结果按 C01 第 3 节判定一致。

运行（在 backend 目录，带上 rules-core 的 wheel）：
    uv run --with ..\\rules-core\\dist\\python\\cost_rules_core-0.1.0-cp313-cp313-win_amd64.whl python ..\\rules-core\\tests\\cross_check.py <browser-results.json> <python-results.json>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cost_rules_core
from cost_rules_core import PackInvalidError, RulesEngine

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def request_text(request: dict) -> str:
    return json.dumps(request, ensure_ascii=False, separators=(",", ":"))


def main(browser_path: str, out_path: str) -> int:
    browser = json.loads(Path(browser_path).read_text(encoding="utf-8"))
    engine = RulesEngine()
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((FIXTURES / "cases").glob("*.json"))]
    report, failed, byte_equal = [], 0, 0
    for c in cases:
        b = next(r for r in browser["results"] if r["name"] == c["name"])
        item = {"name": c["name"], "kind": c["kind"]}
        if c["kind"] == "evaluate":
            handle = engine.load_pack((FIXTURES / c["pack"]).read_bytes())
            start = time.perf_counter()
            item["result"] = engine.evaluate(handle, request_text(c["request"]))
            item["ms"] = (time.perf_counter() - start) * 1000
            item["diffs"] = cost_rules_core.compare_json(item["result"], b["result"])
            item["byteEqual"] = item["result"] == b["result"]
        elif c["kind"] == "packInvalid":
            try:
                engine.load_pack((FIXTURES / c["pack"]).read_bytes())
                item["diffs"] = ["Python 端加载成功"]
            except PackInvalidError as e:
                item["error"] = e.message
                same = b.get("error", {}).get("code") == "PACK_INVALID" and b["error"]["message"] == e.message
                item["diffs"] = [] if same else [f"浏览器 {b.get('error')}，Python {e.message}"]
                item["byteEqual"] = same
        else:
            verdicts = [cost_rules_core.numbers_consistent(x["a"], x["b"]) for x in c["cases"]]
            item["verdicts"] = verdicts
            item["diffs"] = [] if verdicts == b["verdicts"] else [f"浏览器 {b['verdicts']}，Python {verdicts}"]
            item["byteEqual"] = verdicts == b["verdicts"]
        failed += bool(item["diffs"])
        byte_equal += bool(item.get("byteEqual"))
        report.append(item)
        print(("一致" if not item["diffs"] else "不一致"), c["name"], *item["diffs"])

    cost = next(c for c in cases if c["name"] == "成本核算-单据200726")
    handle = engine.load_pack((FIXTURES / cost["pack"]).read_bytes())
    text, repeat = request_text(cost["request"]), 200
    start = time.perf_counter()
    for _ in range(repeat):
        engine.evaluate(handle, text)
    avg_ms = (time.perf_counter() - start) * 1000 / repeat
    versions = {"python": engine.core_version(), "wasm": browser["coreVersion"]}
    if versions["python"] != versions["wasm"]:
        failed += 1
        print("core_version 不同", versions)
    summary = {"cases": len(cases), "consistent": len(cases) - failed if versions["python"] == versions["wasm"] else len(cases) - failed + 1,
               "inconsistent": failed, "byteEqual": byte_equal, "coreVersion": versions,
               "timing": {"python": {"repeat": repeat, "avgMs": avg_ms, "fixture": cost["name"]}, "browser": browser["timing"]}}
    Path(out_path).write_text(json.dumps({"summary": summary, "results": report}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
