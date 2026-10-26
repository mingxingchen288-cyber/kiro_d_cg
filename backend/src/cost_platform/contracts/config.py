"""配置快照：每项配置带版本号，同一版本的内容不再修改。

Oracle 中的 PF_ 配置表是唯一来源，Redis 常驻一份副本。每个请求用一次读取拿到会话和
各项配置的当前版本；进程内已有该版本的解析结果就直接复用，没有的连同内容一起取回。
命令开始时把配置装进只读上下文，执行中的命令一直用这份旧对象。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .identity import SessionData


def item_key(kind: str, code: str) -> str:
    """配置项键，例如 page:COST_PINGGU、role:COST_ACCOUNTANT。"""
    if not kind or not code or ":" in kind:
        raise ValueError("配置项类别和编码都不能为空，类别中不能含冒号")
    return f"{kind}:{code}"


@dataclass(frozen=True, slots=True)
class ConfigItem:
    key: str
    version: str
    content: bytes
    """JSON 文本（UTF-8）。"""


@dataclass(frozen=True, slots=True)
class SnapshotRead:
    session: SessionData | None
    versions: Mapping[str, str | None]
    """请求的每个配置项的当前版本；None 表示该项不存在。"""
    contents: Mapping[str, ConfigItem] = field(default_factory=dict)
    """调用方未持有当前版本的配置项内容。"""
    blocked: frozenset[str] = frozenset()
    """发布失败、等待对账而被阻断的配置项。"""
    missing: frozenset[str] = frozenset()
    """缓存里缺失、需要回查数据库补齐的配置项。"""

    def __post_init__(self) -> None:
        object.__setattr__(self, "versions", MappingProxyType(dict(self.versions)))
        object.__setattr__(self, "contents", MappingProxyType(dict(self.contents)))
