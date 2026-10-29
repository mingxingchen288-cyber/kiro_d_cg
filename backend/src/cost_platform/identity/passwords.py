"""密码哈希（ID-04）：新密码用 Argon2；旧系统导入的 BCrypt 哈希能校验，登录成功时由调用方改写为 Argon2。"""

from __future__ import annotations

from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from . import _bcrypt

try:  # 有 bcrypt 包时用它；后端依赖里目前没有（contract-gaps.md），没有时用模块内的纯 Python 实现
    import bcrypt as _bcrypt_lib
except ImportError:  # pragma: no cover - 取决于环境
    _bcrypt_lib = None

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


@dataclass(frozen=True)
class Verified:
    """校验结果：`ok` 为密码一致；`needs_upgrade` 为一致、但哈希不是 Argon2（BCrypt），应改写。"""

    ok: bool
    needs_upgrade: bool = False


class Passwords:
    """`hasher` 默认用 argon2-cffi 的推荐参数；测试可以传入低强度的 `PasswordHasher` 加快速度。"""

    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._argon2 = hasher or PasswordHasher()

    def hash(self, password: str) -> str:
        return self._argon2.hash(password)

    def verify(self, stored: str | None, password: str) -> Verified:
        if not stored:
            return Verified(False)
        if stored.startswith(_BCRYPT_PREFIXES):
            return Verified(True, True) if _check_bcrypt(stored, password) else Verified(False)
        try:
            self._argon2.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return Verified(False)
        return Verified(True)


def is_bcrypt(stored: str | None) -> bool:
    return bool(stored) and stored.startswith(_BCRYPT_PREFIXES)


def _check_bcrypt(stored: str, password: str) -> bool:
    # 旧系统用 Spring Security 的 BCryptPasswordEncoder：密码按 UTF-8 编码，只取前 72 字节
    secret, hashed = password.encode("utf-8"), stored.encode("ascii")
    if _bcrypt_lib is not None:  # pragma: no cover - 取决于环境
        return bool(_bcrypt_lib.checkpw(secret[:72], hashed))
    return _bcrypt.check(secret, hashed)
