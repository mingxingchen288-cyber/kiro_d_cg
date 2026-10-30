"""业务加锁只经 write-pipeline 的统一入口（用户 2026-10-30 规则 9，WP-03）。

按语法树检查 `backend/src/cost_platform` 下的源码：SQL 文本里写 `FOR UPDATE`（字符串常量和 f-string 的文字部分，文档字符串
不算），或者调用 SQLAlchemy 的 `with_for_update`，只能出现在加锁入口 `pipeline/locks.py`。业务模块要加锁时经 C08 第 5b 节
的 `BusinessLocker`（approval、operations）或 write-pipeline 内部的 `LockBook`（加锁读取、`TableWriter`），这样所有业务锁
按同一顺序加。

例外：下面几处的锁不会和业务锁同时持有（各在自己的事务中，事务里不再锁业务数据），不参与业务加锁的顺序。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import cost_platform

SRC = Path(cost_platform.__file__).parent
ENTRY = "pipeline/locks.py"
EXCEPTIONS = {
    "config/store.py": "配置代号行 PF_CONFIG_GENERATION：保存配置时排队，在配置自己的事务中",
    "identity/accounts.py": "账号行 PF_USER：账号管理改账号时，在 identity 自己的事务中",
    "delivery/store.py": "投递记录 SKIP LOCKED：后台发送时领取，在 delivery 自己的事务中",
}
_FOR_UPDATE = re.compile(r"\bFOR\s+UPDATE\b", re.IGNORECASE)


def lock_lines(path: Path) -> list[int]:
    """文件中加行锁的位置（行号）：SQL 文本里的 FOR UPDATE、`with_for_update` 调用。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs and _FOR_UPDATE.search(node.value):
            found.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr == "with_for_update":
            found.append(node.lineno)
    return sorted(found)


def _all_locks() -> dict[str, list[int]]:
    found = {}
    for path in sorted(SRC.rglob("*.py")):
        lines = lock_lines(path)
        if lines:
            found[path.relative_to(SRC).as_posix()] = lines
    return found


def test_business_locks_only_through_the_entry() -> None:
    outside = {name: lines for name, lines in _all_locks().items() if name != ENTRY and name not in EXCEPTIONS}
    assert outside == {}, f"这些地方直接加了行锁，应改用 BusinessLocker（C08 第 5b 节）：{outside}"


def test_entry_and_exceptions_are_real() -> None:
    """入口确实在加锁；例外清单里的每一处现在都还在加锁（不再加锁时从清单中去掉）。"""
    found = _all_locks()
    assert ENTRY in found
    assert sorted(EXCEPTIONS) == sorted(name for name in found if name in EXCEPTIONS)


def test_docstrings_do_not_count(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text('"""说明：这里不写 FOR UPDATE。"""\n\nSQL = f"SELECT 1 FROM T WHERE K = :k FOR UPDATE WAIT {5}"\n'
                      "rows = query.with_for_update()\n", encoding="utf-8")
    assert lock_lines(sample) == [3, 4]
