"""旧编码到新编码的规则（任务约定）。"""

from __future__ import annotations

import re

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def page_code(old: str) -> str:
    """旧页面编码转大写，`-` 换成 `_`：cost-pinggu → COST_PINGGU。"""
    return old.upper().replace("-", "_")


def entity_code(table_code: str) -> str:
    """旧 TABLE_CODE 的驼峰转大写下划线：CostPinggu → COST_PINGGU，CostPingguLq → COST_PINGGU_LQ。"""
    return _CAMEL.sub("_", table_code).upper()


def lookup_code(old: str) -> str:
    """旧 Lookup 编码按同样的驼峰规则：costMaterialEffective → COST_MATERIAL_EFFECTIVE。"""
    return entity_code(old)


def save_operation(page: str) -> str:
    return f"{page}.save"


def dict_code(entity: str, field: str) -> str:
    return f"{entity}.{field}"
