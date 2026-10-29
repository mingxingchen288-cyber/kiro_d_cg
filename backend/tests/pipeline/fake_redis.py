"""命令审查测试用的 Redis 替代：只实现 `RedisCommandReview` 用到的命令（GET、SET、DEL、LPUSH、LTRIM、LRANGE 和事务管道），
数据在内存中。真实 Redis 上的验证见 `test_redis_review.py`（标 redis）。"""

from __future__ import annotations

from typing import Any


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.fail_writes = False

    def get(self, name: str) -> Any:
        value = self.data.get(name)
        return value.encode() if isinstance(value, str) else value

    def set(self, name: str, value: str) -> bool:
        self.data[name] = value
        return True

    def delete(self, *names: str) -> int:
        return sum(1 for n in names if self.data.pop(n, None) is not None)

    def lrange(self, name: str, start: int, end: int) -> list[bytes]:
        items = self.data.get(name, [])
        return [i.encode() for i in (items[start:] if end == -1 else items[start:end + 1])]

    def pipeline(self, transaction: bool = True) -> _Pipeline:
        return _Pipeline(self)


class _Pipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    def lpush(self, name: str, value: str) -> None:
        self._ops.append(("lpush", (name, value)))

    def ltrim(self, name: str, start: int, end: int) -> None:
        self._ops.append(("ltrim", (name, start, end)))

    def execute(self) -> None:
        if self._redis.fail_writes:
            raise ConnectionError("Redis 不可用")
        for op, args in self._ops:
            items = self._redis.data.setdefault(args[0], [])
            if op == "lpush":
                items.insert(0, args[1])
            else:
                del items[args[2] + 1:]
