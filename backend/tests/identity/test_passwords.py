"""ID-04 的密码哈希：Argon2；BCrypt（旧系统 Spring Security 的 `$2a$`）能校验，并标出需要改写。"""

from __future__ import annotations

from cost_platform.identity import _bcrypt
from cost_platform.identity.passwords import Passwords, is_bcrypt
from cost_platform.identity.rules import check_password_format

from .support import fast_passwords

# jBCrypt（Spring Security BCrypt 的来源）公开的测试向量
JBCRYPT_ABC = (b"abc", b"$2a$06$If6bvum7DFjUnE9p2uDeDu0YHzrHM6tf.iqN8.yx.jNN1ILEf7h0i")
JBCRYPT_SYMBOLS = (b"~!@#$%^&*()      ~!@#$%^&*()PNBFRD", b"$2a$06$fPIsBO8qRqkjj273rfaOI.HtSV9jLDpTbZn782DC6/t7qT67P6FfO")


def test_argon2_hash_verifies() -> None:
    passwords = Passwords()
    stored = passwords.hash("admin123..")
    assert stored.startswith("$argon2id$")
    assert passwords.verify(stored, "admin123..").ok
    assert not passwords.verify(stored, "admin123..").needs_upgrade


def test_blowfish_constants_are_pi_digits() -> None:
    words = _bcrypt.pi_words()
    assert (words[0], words[17], words[18], words[-1]) == (0x243F6A88, 0x8979FB1B, 0xD1310BA6, 0x3AC372E6)


def test_bcrypt_matches_published_vectors() -> None:
    for password, hashed in (JBCRYPT_ABC, JBCRYPT_SYMBOLS):
        assert _bcrypt.hash_with_salt(password, hashed) == hashed


def test_bcrypt_hash_verifies_and_needs_upgrade() -> None:
    stored = JBCRYPT_ABC[1].decode()
    assert is_bcrypt(stored)
    result = fast_passwords().verify(stored, "abc")
    assert result.ok and result.needs_upgrade


def test_old_system_password_format() -> None:
    """旧系统 ChangePasswordRequest 的格式：admin 初始密码和旧系统的重置密码都符合。"""
    check_password_format("admin123..")
    check_password_format("Abc123..")
