"""T-AS-1（AS-07）：模块依赖规则作为测试运行，违反时 `uv run pytest` 失败，不只靠手动运行 lint-imports。"""

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def test_import_rules_kept() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import sys; from importlinter.cli import lint_imports; sys.exit(lint_imports(no_cache=True))"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
