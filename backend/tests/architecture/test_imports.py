"""3. 接线代码的导入规则，写在 backend/.importlinter（plugin-imports、assembly-imports），这里只运行这两条：

- plugin.py 只能导入 contracts 和本模块（第三方库不限，例如 fastapi 的 APIRouter）；
- assembly 只能导入各模块的 plugin.py，以及 contracts、assembly 自己和第三方库（rules-core 插件导入的 cost_rules_core
  不是 cost_platform 的模块，import-linter 不检查）。

tests/unit/test_import_rules.py 运行全部规则，也包括这两条。
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from .support import BACKEND

CONTRACTS = ["plugin-imports", "assembly-imports"]


@pytest.mark.parametrize("contract", CONTRACTS)
def test_wiring_import_rule(contract: str) -> None:
    code = ("import sys; from importlinter.cli import lint_imports; "
            f"sys.exit(lint_imports(no_cache=True, limit_to_contracts=({contract!r},)))")
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    assert result.returncode == 0, result.stdout + result.stderr
