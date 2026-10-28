"""登录、会话和认证（ID-01、ID-03、ID-04、ID-06、ID-10）。

账号在 PF_USER、PF_USER_ROLE；密码用 Argon2。会话目前放在进程内存中（链路 0 本机没有 Redis），
换成 Redis 只替换 MemorySessions。
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import text

from cost_platform.contracts.ports import Clock, UnitOfWorkFactory
from cost_platform.contracts.types import (
    CurrentUser,
    ErrorCode,
    Identity,
    LoginResponse,
    PlatformError,
    RoleRef,
)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123.."
ADMIN_ROLE = "ADMIN"

_hasher = PasswordHasher()


@dataclass
class _Account:
    user_id: str
    username: str
    display_name: str
    department_id: str | None
    enabled: bool
    password_hash: str | None
    role_codes: list[str]


@dataclass
class _Session:
    user: CurrentUser
    role_code: str | None
    csrf_token: str
    expires_at: datetime


class OracleAccounts:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow = uow_factory

    def find(self, username: str) -> _Account | None:
        with self._uow.begin() as uow:
            row = uow.connection.execute(text(
                "SELECT user_id, username, display_name, department_id, enabled, password_hash FROM pf_user "
                "WHERE username = :u"), {"u": username}).one_or_none()
            if row is None:
                return None
            roles = uow.connection.execute(text(
                "SELECT role_code FROM pf_user_role WHERE user_id = :id ORDER BY role_code"), {"id": row.user_id}).scalars().all()
        return _Account(str(row.user_id), row.username, row.display_name, row.department_id, bool(row.enabled),
                        row.password_hash, list(roles))

    def ensure_admin(self) -> bool:
        """ID-06：没有 admin 时创建 admin / admin123..，启用，分配 ADMIN 角色；已存在时不改。返回是否新建。"""
        with self._uow.begin() as uow:
            exists = uow.connection.execute(text("SELECT COUNT(*) FROM pf_user WHERE username = :u"),
                                            {"u": ADMIN_USERNAME}).scalar()
            if exists:
                return False
            user_id = uow.connection.execute(text("SELECT pf_user_seq.NEXTVAL FROM dual")).scalar()
            uow.connection.execute(text(
                "INSERT INTO pf_user (user_id, username, display_name, department_id, enabled, password_hash, version) "
                "VALUES (:id, :u, :name, NULL, 1, :hash, 1)"),
                {"id": user_id, "u": ADMIN_USERNAME, "name": "系统管理员", "hash": _hasher.hash(ADMIN_PASSWORD)})
            uow.connection.execute(text("INSERT INTO pf_user_role (user_id, role_code) VALUES (:id, :r)"),
                                   {"id": user_id, "r": ADMIN_ROLE})
            uow.commit()
            return True


class MemorySessions:
    def __init__(self) -> None:
        self._items: dict[str, _Session] = {}
        self._lock = threading.Lock()

    def put(self, session_id: str, session: _Session) -> None:
        with self._lock:
            self._items[session_id] = session

    def get(self, session_id: str) -> _Session | None:
        with self._lock:
            return self._items.get(session_id)


class IdentityService:
    """`Authenticator`，以及登录和 `/api/me` 用到的会话数据。"""

    def __init__(self, accounts: OracleAccounts, sessions: MemorySessions, clock: Clock, idle_minutes: int,
                 describe_role: Callable[[str], RoleRef]) -> None:
        self._accounts = accounts
        self._sessions = sessions
        self._clock = clock
        self._idle = timedelta(minutes=idle_minutes)
        self._describe_role = describe_role

    def login(self, username: str, password: str) -> tuple[str, LoginResponse]:
        """ID-01：成功时返回新会话的标识和登录响应；只有一个角色时自动选定。"""
        account = self._accounts.find(username)
        if account is None or not account.enabled or not account.password_hash:
            raise PlatformError(ErrorCode.LOGIN_FAILED, "账号或密码错误")
        try:
            _hasher.verify(account.password_hash, password)
        except VerificationError:
            raise PlatformError(ErrorCode.LOGIN_FAILED, "账号或密码错误") from None
        user = CurrentUser(user_id=account.user_id, username=account.username, display_name=account.display_name,
                           department_id=account.department_id)
        roles = [self._describe_role(code) for code in account.role_codes]
        selected = roles[0] if len(roles) == 1 else None
        session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self._sessions.put(session_id, _Session(user, selected.code if selected else None, csrf,
                                                self._clock.now() + self._idle))
        return session_id, LoginResponse(user=user, roles=roles, selected_role=selected, csrf_token=csrf)

    def session(self, session_id: str | None) -> tuple[CurrentUser, str | None, str]:
        """会话中的用户、选定的角色和 CSRF 令牌（`/api/me`）。"""
        found = self._live(session_id)
        return found.user, found.role_code, found.csrf_token

    def authenticate(self, session_id: str | None, csrf_token: str | None, is_write: bool, touch: bool = True) -> Identity:
        found = self._live(session_id)
        if is_write and csrf_token != found.csrf_token:
            raise PlatformError(ErrorCode.CSRF_FAILED, "请求校验失败，请刷新页面")
        if found.role_code is None:
            raise PlatformError(ErrorCode.ROLE_SELECTION_REQUIRED, "请先选择角色")
        if touch:
            found.expires_at = self._clock.now() + self._idle
        user = found.user
        return Identity(user_id=user.user_id, username=user.username, display_name=user.display_name,
                        department_id=user.department_id, role_code=found.role_code, session_id=session_id or "")

    def _live(self, session_id: str | None) -> _Session:
        found = self._sessions.get(session_id) if session_id else None
        if found is None or found.expires_at <= self._clock.now():
            raise PlatformError(ErrorCode.SESSION_REQUIRED, "请先登录")
        return found
