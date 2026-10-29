"""配置的 Redis 副本：内存实现和 Redis 实现（Lua 脚本）跑同一组用例。Redis 的用例标 `redis`（这次不运行）。

- 一次读取一个往返；读取得到的代号、索引和内容属于同一时刻；
- 一批配置项一起切换；按配置项的代号比较，不会把新版本改回旧版本，也不会把已删除的项写回；
- 待生效登记的登记、读取和删除。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest

from cost_platform.config.cache import MemoryConfigCache, PendingEntry, SyncBatch
from cost_platform.config.records import ItemRecord

NOW = datetime(2026, 10, 29, 9, 0, 0)


def rec(config_type: str, key: str, generation: int, version: int = 1, name: str = "x") -> ItemRecord:
    return ItemRecord(type=config_type, key=key, name=name, content_json='{"v": %d}' % generation, version=version,
                      generation=generation, updated_by="1", updated_at=NOW)


class CountingRedis:
    """包一层 redis 客户端，数每次读取发出的命令（往返次数）。"""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.commands: list[str] = []
        original = client.execute_command

        def counted(*args: Any, **kwargs: Any) -> Any:
            self.commands.append(str(args[0]))
            return original(*args, **kwargs)

        client.execute_command = counted


@pytest.fixture(params=["memory", pytest.param("redis", marks=pytest.mark.redis)])
def cache(request: pytest.FixtureRequest) -> Iterator[Any]:
    if request.param == "memory":
        yield MemoryConfigCache()
        return
    from cost_platform.config.redis_cache import RedisConfigCache

    from .real_support import drop_namespace, fresh_namespace, redis_client

    client, namespace = redis_client(), fresh_namespace()
    found = RedisConfigCache(client, namespace)
    found.counter = CountingRedis(client)  # type: ignore[attr-defined]
    yield found
    drop_namespace(client, namespace)


def test_read_returns_role_items_and_fast_path(cache: Any) -> None:
    cache.apply(SyncBatch(3, [rec("role", "A", 1), rec("role", "B", 2), rec("pageView", "P|A", 3), rec("pageView", "P|B", 3),
                              rec("page", "P", 1)]))
    first = cache.read("A", -1)
    assert first.generation == 3 and first.pending == {}
    assert set(first.index) == {"role/A", "pageView/P|A", "page/P"}
    assert {k: v.generation for k, v in first.contents.items() if v} == {"role/A": 1, "pageView/P|A": 3, "page/P": 1}
    counter = getattr(cache, "counter", None)
    if counter is not None:
        counter.commands.clear()
    again = cache.read("A", 3)
    assert again.index is None and again.contents == {}
    if counter is not None:
        assert len(counter.commands) == 1  # 一次读取只访问 Redis 一次
    changed = cache.read("A", 2)
    assert set(changed.contents) == {"pageView/P|A"}  # 只带出代号比已有的新的内容


def test_switch_is_by_generation_and_never_goes_back(cache: Any) -> None:
    cache.apply(SyncBatch(5, [rec("page", "P", 5, version=3, name="新")]))
    result = cache.apply(SyncBatch(4, [rec("page", "P", 4, version=2, name="旧"), rec("page", "Q", 4)]))
    assert result.generation == 5 and result.written == ["page/Q"]
    found = cache.read("A", -1)
    assert found.contents["page/P"].name == "新" and found.index["page/P"] == (3, 5)


def test_deleted_items_are_not_written_back(cache: Any) -> None:
    cache.apply(SyncBatch(2, [rec("role", "R", 2)]))
    cache.apply(SyncBatch(3, [], [("role/R", 3)]))
    cache.apply(SyncBatch(2, [rec("role", "R", 2)]))  # 慢一步的补写（读的是代号 2 的 Oracle）
    assert "role/R" not in (cache.read("R", -1).index or {})
    cache.apply(SyncBatch(6, [rec("role", "R", 6)]))  # 删除之后重新建立
    assert cache.read("R", -1).index["role/R"] == (1, 6)


def test_full_sync_removes_items_missing_from_oracle(cache: Any) -> None:
    cache.apply(SyncBatch(3, [rec("page", "P", 1), rec("page", "OLD", 2)]))
    cache.register_pending(PendingEntry(3, ("page/OLD",), NOW))
    result = cache.apply(SyncBatch(4, [rec("page", "P", 1)], full=True))
    assert result.deleted == ["page/OLD"] and result.pending_removed == [3]
    assert set(cache.read("A", -1).index) == {"page/P"}


def test_pending_registry(cache: Any) -> None:
    cache.register_pending(PendingEntry(7, ("role/R", "pageView/P|R"), NOW))
    generation, pending = cache.status()
    assert generation == 0 and pending[7].items == ("role/R", "pageView/P|R") and pending[7].registered_at == NOW
    assert cache.read("R", 0).pending[7].generation == 7
    result = cache.apply(SyncBatch(7, [rec("role", "R", 7)], [("pageView/P|R", 7)], [7]))
    assert result.pending_removed == [7] and cache.status() == (7, {})
    cache.register_pending(PendingEntry(9, ("role/R",), NOW))
    cache.remove_pending([9])
    assert cache.status()[1] == {}


def test_batch_switches_together(cache: Any) -> None:
    """一批配置项一起切换：读到的要么都是旧的，要么都是新的。"""
    cache.apply(SyncBatch(1, [rec("page", "P", 1), rec("pageView", "P|A", 1), rec("role", "A", 1)]))
    cache.apply(SyncBatch(2, [rec("page", "P", 2, 2), rec("pageView", "P|A", 2, 2)]))
    found = cache.read("A", -1)
    assert found.generation == 2 and {k: v[1] for k, v in found.index.items()} == {"page/P": 2, "pageView/P|A": 2, "role/A": 1}
