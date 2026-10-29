"""BCrypt 的纯 Python 实现（OpenBSD `$2a$`、`$2b$`、`$2y$`），只用于校验旧系统导入的哈希（ID-04）。

为什么有这个文件：后端依赖里没有 `bcrypt` 包（见 `.reports/modules/identity/contract-gaps.md`），按规定不能自己安装。
`passwords.py` 优先用 `bcrypt` 包；没有安装时才用这里的实现。结果与 `bcrypt` 包相同，但速度慢得多：
旧系统的哈希强度为 10（`$2a$10$`），一次校验要几秒（实测见汇报）。每个旧账号登录成功一次后就改写为 Argon2，
之后不再走这里。上线前应加上 `bcrypt` 依赖。

Blowfish 的初始 P 数组和 S 盒是圆周率小数部分的十六进制数字，这里按 Machin 公式用整数运算算出来，不手抄常数表。
"""

from __future__ import annotations

import base64
import hmac
from functools import cache

_MASK = 0xFFFFFFFF
_WORDS = 18 + 4 * 256
_MAGIC = b"OrpheanBeholderScryDoubt"
_BCRYPT_ALPHABET = b"./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_STD_ALPHABET = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_TO_STD = bytes.maketrans(_BCRYPT_ALPHABET, _STD_ALPHABET)
_FROM_STD = bytes.maketrans(_STD_ALPHABET, _BCRYPT_ALPHABET)


@cache
def pi_words() -> tuple[int, ...]:
    """圆周率小数部分的前 1042 个 32 位字：前 18 个是 P 数组，其后每 256 个是一个 S 盒。"""
    guard = 96
    bits = 32 * _WORDS + guard
    one = 1 << bits

    def arctan_inv(x: int) -> int:
        total = term = one // x
        square, n, sign = x * x, 1, -1
        while term:
            term //= square
            n += 2
            total += sign * (term // n)
            sign = -sign
        return total

    pi = 16 * arctan_inv(5) - 4 * arctan_inv(239)
    fraction = (pi - 3 * one) >> guard
    return tuple((fraction >> (32 * (_WORDS - 1 - i))) & _MASK for i in range(_WORDS))


def _words(data: bytes, count: int) -> list[int]:
    """把 data 当作循环字节流，依次取 count 个大端 32 位字（OpenBSD 的 Blowfish_stream2word）。"""
    out, j, size = [], 0, len(data)
    for _ in range(count):
        word = 0
        for _ in range(4):
            word = (word << 8) | data[j]
            j = j + 1 if j + 1 < size else 0
        out.append(word)
    return out


class _State:
    def __init__(self) -> None:
        words = pi_words()
        self.p = list(words[:18])
        self.s = [list(words[18 + 256 * i:18 + 256 * (i + 1)]) for i in range(4)]

    def encipher(self, left: int, right: int) -> tuple[int, int]:
        p = self.p
        s0, s1, s2, s3 = self.s
        left ^= p[0]
        for i in range(1, 17, 2):
            right ^= ((((s0[left >> 24] + s1[(left >> 16) & 255]) ^ s2[(left >> 8) & 255]) + s3[left & 255]) & _MASK) ^ p[i]
            left ^= ((((s0[right >> 24] + s1[(right >> 16) & 255]) ^ s2[(right >> 8) & 255]) + s3[right & 255]) & _MASK) ^ p[i + 1]
        return right ^ p[17], left

    def expand(self, key_words: list[int], salt_words: list[int] | None) -> None:
        """OpenBSD 的 Blowfish_expandstate（给出 salt_words）和 Blowfish_expand0state（salt_words 为 None）。"""
        p = self.p
        for i in range(18):
            p[i] ^= key_words[i]
        left = right = 0
        k = 0
        encipher = self.encipher
        for target in (p, *self.s):
            for i in range(0, len(target), 2):
                if salt_words is not None:
                    left ^= salt_words[k]
                    right ^= salt_words[k + 1]
                    k = (k + 2) % len(salt_words)
                left, right = encipher(left, right)
                target[i], target[i + 1] = left, right


def _encode(data: bytes) -> bytes:
    return base64.b64encode(data).rstrip(b"=").translate(_FROM_STD)


def _decode_salt(text: bytes) -> bytes:
    return base64.b64decode(text.translate(_TO_STD) + b"==")[:16]


def hash_with_salt(password: bytes, setting: bytes) -> bytes:
    """按 `setting`（`$2a$10$` 加 22 位盐，也可以是完整的哈希）计算 BCrypt 哈希，返回 60 字节的哈希文本。"""
    variant, cost = setting[1:3], int(setting[4:6])
    salt_text = setting[7:29]
    salt = _decode_salt(salt_text)
    key = (password + b"\x00")[:72]
    state = _State()
    key_words, salt_words = _words(key, 18), _words(salt, 4)
    salt_p = _words(salt, 18)
    state.expand(key_words, salt_words)
    for _ in range(1 << cost):
        state.expand(key_words, None)
        state.expand(salt_p, None)
    data = _words(_MAGIC, 6)
    for _ in range(64):
        for i in range(0, 6, 2):
            data[i], data[i + 1] = state.encipher(data[i], data[i + 1])
    digest = b"".join(w.to_bytes(4, "big") for w in data)[:23]
    return b"$" + variant + b"$" + f"{cost:02d}".encode() + b"$" + salt_text + _encode(digest)


def check(password: bytes, hashed: bytes) -> bool:
    """password 是否与 BCrypt 哈希 hashed 一致。"""
    return hmac.compare_digest(hash_with_salt(password, hashed), hashed)
