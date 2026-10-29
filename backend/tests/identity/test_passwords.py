"""ID-04 的密码哈希：Argon2；BCrypt（旧系统 Spring Security 的 `$2a$`）能校验，并标出需要改写。"""

from __future__ import annotations

import bcrypt
import pytest

from cost_platform.identity.passwords import Passwords, is_bcrypt
from cost_platform.identity.rules import check_password_format

from .support import fast_passwords

# jBCrypt（Spring Security BCrypt 的来源）公开的测试向量；JBCRYPT_ABC 的强度 10 与旧系统导入的哈希相同（`$2a$10$`）
JBCRYPT_ABC = (b"abc", b"$2a$10$WvvTPHKwdBJ3uk0Z37EMR.hLA2W6N9AEBhEgrAOljy2Ae5MtaSIUi")
JBCRYPT_SYMBOLS = (b"~!@#$%^&*()      ~!@#$%^&*()PNBFRD", b"$2a$06$fPIsBO8qRqkjj273rfaOI.HtSV9jLDpTbZn782DC6/t7qT67P6FfO")


def test_argon2_hash_verifies() -> None:
    passwords = Passwords()
    stored = passwords.hash("admin123..")
    assert stored.startswith("$argon2id$")
    assert passwords.verify(stored, "admin123..").ok
    assert not passwords.verify(stored, "admin123..").needs_upgrade


@pytest.mark.parametrize(("password", "hashed"), [JBCRYPT_ABC, JBCRYPT_SYMBOLS])
def test_bcrypt_hash_verifies_and_needs_upgrade(password: bytes, hashed: bytes) -> None:
    stored = hashed.decode()
    assert is_bcrypt(stored)
    result = fast_passwords().verify(stored, password.decode())
    assert result.ok and result.needs_upgrade


def test_bcrypt_uses_first_72_bytes() -> None:
    """与 Spring Security 的 BCryptPasswordEncoder 相同：超过 72 字节的密码只取前 72 字节。"""
    long_password = "Abc123.." * 10  # 80 字节
    stored = bcrypt.hashpw(long_password.encode()[:72], bcrypt.gensalt(4, b"2a")).decode()
    assert fast_passwords().verify(stored, long_password).ok
    assert fast_passwords().verify(stored, long_password[:72] + "其他字符").ok


def test_old_system_password_format() -> None:
    """旧系统 ChangePasswordRequest 的格式：admin 初始密码和旧系统的重置密码都符合。"""
    check_password_format("admin123..")
    check_password_format("Abc123..")
