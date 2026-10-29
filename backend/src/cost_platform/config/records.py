"""配置项的存储记录：PF_CONFIG_ITEM 的一行，也是 Redis 中一个配置项的内容。

编号（id）为 `类型/编码`，例如 `page/COST_PINGGU`、`pageView/COST_PINGGU|ADMIN`、`rulesPack/COST_PINGGU`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

PAGE_VIEW = "pageView"
RULES_PACK = "rulesPack"
DERIVED_TYPES = (PAGE_VIEW, RULES_PACK)
"""config 生成的配置项：页面视图（编码为 `页面编码|角色编码`）和规则包（编码为 packId）。管理员不能直接编辑。"""

BASE_TYPES = ("entity", "page", "operation", "rule", "approvalFlow", "role", "menu", "dict", "lookup", "export")
"""C06 第 1 节的配置项类型。"""


def item_id(config_type: str, key: str) -> str:
    return f"{config_type}/{key}"


def split_id(value: str) -> tuple[str, str]:
    config_type, _, key = value.partition("/")
    return config_type, key


def view_key(page_code: str, role_code: str) -> str:
    return f"{page_code}|{role_code}"


def relevant_to_role(value: str, role_code: str) -> bool:
    """角色的配置快照用到的配置项：除了其他角色和其他角色的页面视图，都要用（CF-06）。"""
    config_type, key = split_id(value)
    if config_type == "role":
        return key == role_code
    if config_type == PAGE_VIEW:
        return key.endswith(f"|{role_code}")
    return True


def pages_of(ids: list[str] | set[str]) -> list[str]:
    """一组变化的配置项涉及的页面：页面本身和页面视图的页面编码（C10 `config.changed` 的 `pages`）。"""
    pages: set[str] = set()
    for value in ids:
        config_type, key = split_id(value)
        if config_type == "page":
            pages.add(key)
        elif config_type == PAGE_VIEW:
            pages.add(key.split("|", 1)[0])
    return sorted(pages)


@dataclass(frozen=True)
class ItemRecord:
    type: str
    key: str
    name: str
    content_json: str
    version: int
    generation: int
    """这一项最后一次变化时的配置代号。"""
    updated_by: str
    updated_at: datetime

    @property
    def id(self) -> str:
        return item_id(self.type, self.key)

    def content(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.content_json)
        return loaded

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "key": self.key, "name": self.name, "content": self.content_json,
                           "version": self.version, "generation": self.generation, "updatedBy": self.updated_by,
                           "updatedAt": self.updated_at.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> ItemRecord:
        data = json.loads(text)
        return cls(type=data["type"], key=data["key"], name=data["name"], content_json=data["content"],
                   version=int(data["version"]), generation=int(data["generation"]), updated_by=data["updatedBy"],
                   updated_at=datetime.strptime(data["updatedAt"], "%Y-%m-%dT%H:%M:%S"))


def content_text(content: Any) -> str:
    """配置内容存储时的 JSON 文本：管理员保存的内容原样存储（不补默认值），只去掉多余的空白。"""
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))
