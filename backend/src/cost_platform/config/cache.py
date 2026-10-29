"""配置的 Redis 副本（CF-04～CF-06、CF-13）：接口和内存实现。Redis 实现见 `redis_cache.py`，两者行为相同。

内容：
- 当前代号 `gen`；
- 索引 `index`：配置项编号 → （版本，最后变化时的代号）；
- 每个配置项的内容（`ItemRecord.to_json()`）；
- 待生效登记 `pending`：代号 G → （本次改动的配置项，登记时间）；
- 删除墓碑 `deleted`：配置项编号 → 删除时的代号，防止慢一步的补写把已删除的项写回来。

写入按配置项的代号比较：只写比 Redis 中更新的（也比墓碑更新）；删除只删比删除代号旧的。当前代号只增不减。
因此补写可以重复执行，不会把新版本改回旧版本（CF-04 第 5 步、CF-13）。
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from .records import ItemRecord, relevant_to_role


class CacheUnavailable(Exception):
    """Redis 不可用。"""


@dataclass(frozen=True)
class PendingEntry:
    generation: int
    items: tuple[str, ...]
    """本次保存改动的配置项编号（含生成的页面视图、规则包，以及删除的项）。"""
    registered_at: datetime


@dataclass(frozen=True)
class CacheRead:
    """读取配置快照时的一次读取结果（CF-06）。"""

    generation: int
    pending: dict[int, PendingEntry]
    index: dict[str, tuple[int, int]] | None
    """角色用到的配置项：编号 →（版本，代号）。代号与调用方已有的相同时为 None（内容没变）。"""
    contents: dict[str, ItemRecord | None]
    """代号比调用方已有的新的配置项内容；内容缺失（例如被 Redis 淘汰）时为 None。"""


@dataclass(frozen=True)
class SyncBatch:
    """一次写入并切换（CF-04 第 5 步，或按 Oracle 补写）。"""

    generation: int
    """这批内容对应的 Oracle 配置代号。"""
    upserts: list[ItemRecord] = field(default_factory=list)
    deletes: list[tuple[str, int]] = field(default_factory=list)
    """（配置项编号，删除时的代号）。"""
    pending_done: list[int] = field(default_factory=list)
    """写完后删除的待生效登记。"""
    full: bool = False
    """`upserts` 是 Oracle 在 `generation` 时的全部配置项：Redis 中不在其中、代号不比 `generation` 新的项都删掉，
    代号不大于 `generation` 的待生效登记都删掉。"""


@dataclass(frozen=True)
class SyncResult:
    generation: int
    written: list[str]
    deleted: list[str]
    pending_removed: list[int]

    @property
    def changed(self) -> bool:
        return bool(self.written or self.deleted or self.pending_removed)


class ConfigCache(Protocol):
    def read(self, role_code: str, known_generation: int) -> CacheRead:
        """一次读取：当前代号、待生效登记；代号与 `known_generation` 不同时，再带上角色用到的配置项的索引和变化了的内容。"""
        ...

    def status(self) -> tuple[int, dict[int, PendingEntry]]:
        """当前代号和待生效登记（恢复任务用）。"""
        ...

    def register_pending(self, entry: PendingEntry) -> None: ...

    def remove_pending(self, generations: Iterable[int]) -> None: ...

    def apply(self, batch: SyncBatch) -> SyncResult:
        """原子地写入并切换。"""
        ...


class MemoryConfigCache:
    """内存实现：模拟验证用。`unavailable` 为 True 时每个方法都抛 CacheUnavailable；`calls` 记录每次调用（往返次数）。"""

    def __init__(self) -> None:
        self.generation = 0
        self.index: dict[str, tuple[int, int]] = {}
        self.items: dict[str, ItemRecord] = {}
        self.pending: dict[int, PendingEntry] = {}
        self.tombstones: dict[str, int] = {}
        self.unavailable = False
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def _enter(self, name: str) -> None:
        self.calls.append(name)
        if self.unavailable:
            raise CacheUnavailable("Redis 不可用")

    def read(self, role_code: str, known_generation: int) -> CacheRead:
        with self._lock:
            self._enter("read")
            pending = dict(self.pending)
            if self.generation == known_generation:
                return CacheRead(self.generation, pending, None, {})
            index = {k: v for k, v in self.index.items() if relevant_to_role(k, role_code)}
            contents = {k: self.items.get(k) for k, (_, gen) in index.items() if gen > known_generation}
            return CacheRead(self.generation, pending, index, contents)

    def status(self) -> tuple[int, dict[int, PendingEntry]]:
        with self._lock:
            self._enter("status")
            return self.generation, dict(self.pending)

    def register_pending(self, entry: PendingEntry) -> None:
        with self._lock:
            self._enter("register_pending")
            self.pending[entry.generation] = entry

    def remove_pending(self, generations: Iterable[int]) -> None:
        with self._lock:
            self._enter("remove_pending")
            for g in generations:
                self.pending.pop(g, None)

    def apply(self, batch: SyncBatch) -> SyncResult:
        with self._lock:
            self._enter("apply")
            written, deleted, removed = [], [], []
            present = set()
            for record in batch.upserts:
                present.add(record.id)
                current = max(self.index.get(record.id, (0, 0))[1], self.tombstones.get(record.id, 0))
                if record.generation > current or (record.id in self.index and record.id not in self.items):
                    self.index[record.id] = (record.version, record.generation)
                    self.items[record.id] = record
                    self.tombstones.pop(record.id, None)
                    written.append(record.id)
            for value, gen in batch.deletes:
                if value in self.index and self.index[value][1] < gen:
                    del self.index[value]
                    self.items.pop(value, None)
                    deleted.append(value)
                if gen > self.tombstones.get(value, 0) and value not in self.index:
                    self.tombstones[value] = gen
            if batch.full:
                for value in [k for k, (_, gen) in self.index.items() if k not in present and gen <= batch.generation]:
                    del self.index[value]
                    self.items.pop(value, None)
                    self.tombstones[value] = max(self.tombstones.get(value, 0), batch.generation)
                    deleted.append(value)
            done = set(batch.pending_done)
            if batch.full:
                done |= {g for g in self.pending if g <= batch.generation}
            for g in sorted(done):
                if self.pending.pop(g, None) is not None:
                    removed.append(g)
            self.generation = max(self.generation, batch.generation)
            return SyncResult(self.generation, written, deleted, removed)
