"""身份与会话的数据形状。会话存在服务端（Redis），浏览器只持有会话 Cookie。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Principal:
    """当前请求的身份。由会话适配器给出，从不从请求体解析。"""

    user_id: str
    username: str
    display_name: str
    role_code: str | None
    """登录时选定的唯一角色；为空表示尚未选角色。只用这一个角色，不合并其他角色。"""
    department_id: str | None
    session_id: str


@dataclass(frozen=True, slots=True)
class SessionData:
    session_id: str
    user_id: str
    username: str
    display_name: str
    department_id: str | None
    role_code: str | None
    available_roles: tuple[str, ...]
    csrf_token: str
    created_at: datetime
    expires_at: datetime
    user_version: str = "0"
    """账号版本：停用、改角色时递增，用于让旧会话立即失效。"""


@dataclass(frozen=True, slots=True)
class UserAccount:
    user_id: str
    username: str
    display_name: str
    password_hash: str
    active: bool
    department_id: str | None
    roles: tuple[str, ...] = field(default_factory=tuple)
    version: str = "0"
