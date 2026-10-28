"""平台表迁移（DB-04）：用 Alembic 执行各模块 `migrations/` 目录中的脚本，版本表为 PF_ALEMBIC_VERSION。

各模块的第一个脚本用自己的 `branch_labels`、`down_revision = None`，升级到全部 heads。
模块目录由 assembly 传入，db-core 不导入其他模块。
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine

VERSION_TABLE = "pf_alembic_version"
_ENV_DIR = Path(__file__).resolve().parent / "migrations"


def _config(connection: Connection | None, version_locations: Sequence[Path]) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_ENV_DIR))
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("version_locations", os.pathsep.join(str(p) for p in version_locations))
    cfg.attributes["connection"] = connection
    cfg.attributes["version_table"] = VERSION_TABLE
    return cfg


def upgrade(engine: Engine, version_locations: Sequence[Path]) -> None:
    with engine.begin() as connection:
        command.upgrade(_config(connection, version_locations), "heads")


def check(engine: Engine, version_locations: Sequence[Path]) -> list[str]:
    """返回未执行的迁移版本；为空表示平台表是最新的。"""
    script = ScriptDirectory.from_config(_config(None, version_locations))
    with engine.connect() as connection:
        current = set(MigrationContext.configure(connection, opts={"version_table": VERSION_TABLE}).get_current_heads())
    return sorted(set(script.get_heads()) - current)
