"""旧元数据迁移和对账（docs/模块/migration.md）

入口：`generate(connection_factory, output_dir)`，见 `generator.py`。
"""

from .generator import GenerateResult, generate, generate_from_snapshot

__all__ = ["GenerateResult", "generate", "generate_from_snapshot"]
