"""启动时导入基础配置（插件 `config` 的 start 第 1 步）。

PF_CONFIG_ITEM 中还没有基础配置项（C06 第 1 节的类型，不含生成的页面视图和规则包）时，把目录中的配置项文件一次保存进去：
走与前端保存相同的校验和保存流程（CF-04），配置代号只加一，日志记条数。已有基础配置项时什么都不做。

每个文件是一个配置项 `{"type", "key", "name", "content"}`（与 `files.py` 相同），按文件名排序。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from cost_platform.contracts.types import ConfigDraft, parse_wire

from .service import SYSTEM_USER, ConfigService

_log = logging.getLogger(__name__)


def read_seed(directory: Path) -> list[ConfigDraft]:
    return [parse_wire(ConfigDraft, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(directory.glob("*.json"))]


def import_seed(service: ConfigService, directory: Path) -> int:
    """返回保存的配置项数；已有基础配置项时为 0。"""
    if service.list_items():
        return 0
    drafts = read_seed(directory)
    result = service.save(drafts, SYSTEM_USER)
    _log.info("PF_CONFIG_ITEM 没有基础配置项：从 %s 导入 %s 项，配置代号 %s", directory, len(drafts), result.generation)
    return len(drafts)
