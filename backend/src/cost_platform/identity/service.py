"""登录、选角色、注销和会话认证（ID-01–ID-05 的会话部分、ID-10），即 C08 第 3 节的 `Authenticator`。

账号在 PF_USER、PF_USER_ROLE（`accounts.py`）；会话和账号状态在 Redis 或内存（`sessions.py`）。
assembly 从这里导入 `IdentityService`、`MemorySessions`、`OracleAccounts`，名字和原有构造参数保持不变。
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

from cost_platform.contracts.ports import Clock, ConfigSnapshotReader, IdGenerator, RealtimePublisher
from cost_platform.contracts.types import (
    CurrentUser,
    ErrorCode,
    Identity,
    LoginResponse,
    PlatformError,
    RoleRef,
    SelectRoleResponse,
    SessionRevokedEvent,
    SessionRevokedPayload,
    SessionsAudience,
    UsersAudience,
)

from .accounts import ADMIN_PASSWORD, ADMIN_ROLE, ADMIN_USERNAME, AccountRecord, OracleAccounts
from .passwords import Passwords
from .rules import check_password_format
from .sessions import AccountState, MemorySessions, RedisSessions, SessionData, SessionStore

__all__ = [
    "ADMIN_PASSWORD",
    "ADMIN_ROLE",
    "ADMIN_USERNAME",
    "IdentityService",
    "MemorySessions",
    "OracleAccounts",
    "RedisSessions",
    "RoleDescriber",
    "describe_role_from",
    "publish_revoked",
]

RoleDescriber = Callable[[str], RoleRef]
"""由角色编码得到 `RoleRef`；角色不存在时抛 PlatformError（NOT_FOUND 或 SESSION_ROLE_REVOKED）。"""


def describe_role_from(reader: ConfigSnapshotReader) -> RoleDescriber:
    """用 config 的 `ConfigSnapshotReader`（C08 第 4 节）取角色名称和是否管理员。角色已删除时 `read` 抛 SESSION_ROLE_REVOKED。"""

    def describe(code: str) -> RoleRef:
        role = reader.read(code).role()
        return RoleRef(code=code, name=role.name, admin=role.admin)

    return describe


def publish_revoked(publisher: RealtimePublisher | None, ids: IdGenerator | None,
                    audience: UsersAudience | SessionsAudience, reason: str) -> None:
    """发布 `session.revoked`（C10）。没有接入 realtime（publisher 为 None）时不发布。"""
    if publisher is None or ids is None:
        return
    publisher.publish(SessionRevokedEvent(event_id=ids.uuid(), topic="session.revoked", audience=audience,
                                          payload=SessionRevokedPayload(reason=reason)))  # type: ignore[arg-type]


def _user_of(session_id: str | None) -> str | None:
    """会话编号为 `<userId>.<随机串>`（sessions.py）；格式不对的编号对应不到会话。"""
    if not session_id:
        return None
    user_id, dot, token = session_id.partition(".")
    return user_id if dot and token and user_id.isdigit() else None


def _same(expected: str, given: str | None) -> bool:
    return given is not None and hmac.compare_digest(expected.encode(), given.encode())


def _current_user(data: SessionData) -> CurrentUser:
    return CurrentUser(user_id=data.user_id, username=data.username, display_name=data.display_name,
                       department_id=data.department_id)


class IdentityService:
    """`Authenticator`，以及登录、选角色、注销、`/api/me` 和改自己的密码用到的会话操作。

    - `describe_role`：登录时列出账号的角色、选角色时返回 `RoleRef`；可用 `describe_role_from(config 的读取方)` 生成。
    - `publisher`、`ids`：注销时发布 `session.revoked`（C10）；不给时不发布。
    - `passwords`：密码哈希，默认 Argon2 推荐参数。
    - `new_token`：生成会话编号的随机部分和 CSRF 令牌，默认 `secrets.token_urlsafe(32)`；契约测试用它预知令牌。
    """

    def __init__(self, accounts: OracleAccounts, sessions: SessionStore, clock: Clock, idle_minutes: int,
                 describe_role: RoleDescriber, *, publisher: RealtimePublisher | None = None,
                 ids: IdGenerator | None = None, passwords: Passwords | None = None,
                 new_token: Callable[[], str] | None = None) -> None:
        self._accounts = accounts
        self._sessions = sessions
        self._clock = clock
        self._idle = timedelta(minutes=idle_minutes)
        self._describe_role = describe_role
        self._publisher = publisher
        self._ids = ids
        self._passwords = passwords or Passwords()
        self._token = new_token or (lambda: secrets.token_urlsafe(32))

    # ------------------------------------------------------------ 登录、选角色、注销

    def login(self, username: str, password: str) -> tuple[str, LoginResponse]:
        """ID-01：成功时新建会话，返回会话编号和登录响应；账号只有一个角色时自动选定。
        账号不存在、停用、没有密码哈希、密码错误，都是 401 LOGIN_FAILED。ID-04：BCrypt 哈希登录成功后改写为 Argon2。"""
        account = self._accounts.find(username)
        if account is None or not account.enabled or not account.password_hash:
            raise PlatformError(ErrorCode.LOGIN_FAILED, "账号或密码错误")
        verified = self._passwords.verify(account.password_hash, password)
        if not verified.ok:
            raise PlatformError(ErrorCode.LOGIN_FAILED, "账号或密码错误")
        if verified.needs_upgrade:
            self._accounts.set_password_hash(account.user_id, self._passwords.hash(password))
        self._sessions.put_state(account.state())
        roles = [self._describe_role(code) for code in account.role_codes]
        selected = roles[0] if len(roles) == 1 else None
        session_id = f"{account.user_id}.{self._token()}"
        data = SessionData(user_id=account.user_id, username=account.username, display_name=account.display_name,
                           department_id=account.department_id, role_code=selected.code if selected else None,
                           csrf_token=self._token(), version=account.version)
        self._sessions.put(session_id, data, self._clock.now(), self._idle)
        return session_id, LoginResponse(user=_current_user(data), roles=roles, selected_role=selected,
                                         csrf_token=data.csrf_token)

    def select_role(self, session_id: str | None, csrf_token: str | None, role_code: str) -> SelectRoleResponse:
        """ID-02：选定会话的角色；角色不属于该账号时 403 PERMISSION_DENIED。原角色已被撤销的会话也可以重新选择。"""
        data, state = self._check(session_id, csrf_token, is_write=True, touch=False, require_role=False,
                                  allow_revoked_role=True)
        if role_code not in state.role_codes:
            raise PlatformError(ErrorCode.PERMISSION_DENIED, f"账号没有角色 {role_code}")
        role = self._describe_role(role_code)
        chosen = replace(data.refreshed(state), role_code=role_code)
        self._sessions.put(session_id or "", chosen, self._clock.now(), self._idle)
        return SelectRoleResponse(selected_role=role)

    def logout(self, session_id: str | None, csrf_token: str | None) -> None:
        """注销：删除会话，向这个会话发布 `session.revoked`（reason 为 loggedOut）。会话已不存在时什么也不做。"""
        user_id = _user_of(session_id)
        if user_id is None or session_id is None:
            return
        data, _ = self._sessions.read(session_id, user_id, self._clock.now())
        if data is None:
            return
        if not _same(data.csrf_token, csrf_token):
            raise PlatformError(ErrorCode.CSRF_FAILED, "请求校验失败，请刷新页面")
        self._sessions.delete(session_id)
        publish_revoked(self._publisher, self._ids, SessionsAudience(sessions=[session_id]), "loggedOut")

    def change_own_password(self, session_id: str | None, csrf_token: str | None, password: str) -> None:
        """当前用户改自己的密码（旧系统 AuthService.changePassword）。C09 没有这个接口，见 contract-gaps.md。"""
        data, _ = self._check(session_id, csrf_token, is_write=True, touch=True, require_role=False)
        check_password_format(password)
        self._accounts.set_password_hash(data.user_id, self._passwords.hash(password))

    # ------------------------------------------------------------ 会话

    def session(self, session_id: str | None, touch: bool = False) -> tuple[CurrentUser, str | None, str]:
        """`/api/me` 用：会话中的用户、选定的角色（没有选定时为 None）和 CSRF 令牌。"""
        data, _ = self._check(session_id, None, is_write=False, touch=touch, require_role=False)
        return _current_user(data), data.role_code, data.csrf_token

    def authenticate(self, session_id: str | None, csrf_token: str | None, is_write: bool, touch: bool = True) -> Identity:
        """C08 第 3 节。失败时抛 SESSION_REQUIRED、SESSION_ROLE_REVOKED、ROLE_SELECTION_REQUIRED、CSRF_FAILED。"""
        data, _ = self._check(session_id, csrf_token, is_write=is_write, touch=touch, require_role=True)
        return Identity(user_id=data.user_id, username=data.username, display_name=data.display_name,
                        department_id=data.department_id, role_code=data.role_code or "", session_id=session_id or "")

    def _check(self, session_id: str | None, csrf_token: str | None, *, is_write: bool, touch: bool,
               require_role: bool, allow_revoked_role: bool = False) -> tuple[SessionData, AccountState]:
        """模块说明第 5 节：读会话和账号版本 → 版本不一致时按账号状态判断 → 写请求核对 CSRF → touch 时顺延。"""
        user_id = _user_of(session_id)
        if user_id is None or session_id is None:
            raise PlatformError(ErrorCode.SESSION_REQUIRED, "请先登录")
        now = self._clock.now()
        data, state = self._sessions.read(session_id, user_id, now)
        if data is None or data.user_id != user_id:
            raise PlatformError(ErrorCode.SESSION_REQUIRED, "请先登录")
        if state is None:  # 账号状态键不在了（例如 Redis 被清理）：按 Oracle 中的账号重新写入
            account: AccountRecord | None = self._accounts.get(user_id)
            if account is None:
                self._sessions.delete(session_id)
                raise PlatformError(ErrorCode.SESSION_REQUIRED, "请先登录")
            state = account.state()
            self._sessions.put_state(state)
        if state.version != data.version:
            if not state.enabled:  # ID-05：停用账号后旧会话失效
                self._sessions.delete(session_id)
                raise PlatformError(ErrorCode.SESSION_REQUIRED, "账号已停用，请重新登录")
            revoked = data.role_code is not None and data.role_code not in state.role_codes
            if revoked and not allow_revoked_role:  # ID-05：撤销会话选定的角色
                raise PlatformError(ErrorCode.SESSION_ROLE_REVOKED, "当前角色已被撤销，请重新选择角色")
            if not revoked:
                data = data.refreshed(state)
                self._sessions.replace(session_id, data)
        if require_role and data.role_code is None:
            raise PlatformError(ErrorCode.ROLE_SELECTION_REQUIRED, "请先选择角色")
        if is_write and not _same(data.csrf_token, csrf_token):  # ID-03
            raise PlatformError(ErrorCode.CSRF_FAILED, "请求校验失败，请刷新页面")
        if touch:  # ID-10：只有用户自己的写入和查询请求顺延
            self._sessions.touch(session_id, now, self._idle)
        return data, state
