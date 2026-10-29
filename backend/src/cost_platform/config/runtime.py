"""启动预热（CF-13）和恢复任务（CF-05）。

- `warm_up()` 由 assembly 在启动时调用，完成前进程不接受业务请求：
  1. 一条 SQL 从 Oracle 读出全部配置项（含生成的页面视图和规则包）；
  2. 对每个规则包调用 `RulesEngine.load_pack`，句柄放进进程缓存（编译失败时启动失败）；
  3. 按角色配置逐个角色生成配置快照，放进进程缓存；
  4. 把 Redis 中缺少或版本更旧的项补写进去（Redis 中已有更新的版本时不覆盖），Redis 不可用时每 5 秒重试一次；
  之后 `ready` 为 true，日志记录角色数、规则包数和耗时。Oracle 不可用或有规则包编译失败时抛 `ConfigStartupError`。
- 恢复任务 `RecoveryTask.run_once()` 每 5 秒运行一次，只读一行代号：
  - Redis 的代号落后于 Oracle，或有代号已达到的待生效登记时，按 Oracle 补写 Redis，并发布 `config.changed`；
  - 待生效登记超过 60 秒、而 Oracle 代号仍小于登记的代号时，那次保存已经回滚，删除这条登记。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from cost_platform.contracts.ports import Clock, IdGenerator, RealtimePublisher, UnitOfWorkFactory
from cost_platform.contracts.types import PackInvalidError, PlatformError

from .cache import CacheUnavailable, ConfigCache, SyncBatch
from .records import RULES_PACK, pages_of
from .snapshot import ConfigReader, delta_batch
from .service import publish_changed
from .store import ConfigStore

RETRY_SECONDS = 5.0
RECOVERY_SECONDS = 5.0
PENDING_TIMEOUT = timedelta(seconds=60)

_log = logging.getLogger(__name__)


class ConfigStartupError(Exception):
    """启动预热失败：Oracle 不可用或规则包编译失败，进程以非零退出码结束（CF-13）。"""


@dataclass(frozen=True)
class WarmUpReport:
    roles: int
    packs: int
    seconds: float
    generation: int


class ConfigRuntime:
    def __init__(self, uow_factory: UnitOfWorkFactory, cache: ConfigCache, reader: ConfigReader, *,
                 store: ConfigStore | None = None, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic, retry_seconds: float = RETRY_SECONDS) -> None:
        self._uow = uow_factory
        self._cache = cache
        self._reader = reader
        self._store = store or ConfigStore()
        self._sleep = sleep
        self._monotonic = monotonic
        self._retry = retry_seconds
        self.ready = False

    def warm_up(self) -> WarmUpReport:
        started = self._monotonic()
        try:
            with self._uow.begin() as uow:
                generation, records = self._store.read_all(uow)
        except PlatformError as error:
            raise ConfigStartupError(f"启动预热读不到 Oracle 中的配置：{error.message}") from error
        packs = [r for r in records.values() if r.type == RULES_PACK]
        for record in packs:
            try:
                self._reader.parsed.pack(record)
            except PackInvalidError as invalid:
                raise ConfigStartupError(f"规则包 {record.key} 编译失败：{invalid.message}") from None
        roles = sorted(r.key for r in records.values() if r.type == "role")
        for role in roles:
            self._reader.install(role, generation, records)
        while True:
            try:
                self._cache.apply(SyncBatch(generation, list(records.values()), full=True))
                break
            except CacheUnavailable:
                _log.warning("启动预热：Redis 不可用，%s 秒后重试", self._retry)
                self._sleep(self._retry)
        report = WarmUpReport(roles=len(roles), packs=len(packs), seconds=self._monotonic() - started, generation=generation)
        _log.info("配置预热完成：角色 %s 个，规则包 %s 个，耗时 %.3f 秒，配置代号 %s", report.roles, report.packs,
                  report.seconds, report.generation)
        self.ready = True
        return report


@dataclass
class RecoveryTask:
    uow_factory: UnitOfWorkFactory
    cache: ConfigCache
    publisher: RealtimePublisher
    clock: Clock
    ids: IdGenerator
    store: ConfigStore = field(default_factory=ConfigStore)
    interval: float = RECOVERY_SECONDS
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def run_once(self) -> list[str]:
        """运行一次，返回补写后发布了 `config.changed` 的页面。"""
        try:
            redis_generation, pending = self.cache.status()
        except CacheUnavailable:
            return []
        with self.uow_factory.begin() as uow:
            generation = self.store.generation(uow)
        now = self.clock.now()
        stale = [g for g, p in pending.items() if g > generation and now - p.registered_at > PENDING_TIMEOUT]
        if stale:
            try:
                self.cache.remove_pending(stale)
            except CacheUnavailable:
                return []
        done = [p for g, p in sorted(pending.items()) if g <= generation]
        if redis_generation >= generation and not done:
            return []
        covered = set(range(redis_generation + 1, generation + 1)) <= {p.generation for p in done}
        with self.uow_factory.begin() as uow:
            if covered:
                generation, records = self.store.read_ids(uow, {i for p in done for i in p.items})
                batch = delta_batch(generation, records, done, redis_generation)
            else:
                generation, records = self.store.read_all(uow)
                batch = SyncBatch(generation, list(records.values()), [], [p.generation for p in done], full=True)
        try:
            result = self.cache.apply(batch)
        except CacheUnavailable:
            return []
        touched = {i for p in done for i in p.items} | set(result.written) | set(result.deleted)
        pages = pages_of(touched)
        if result.changed:
            publish_changed(self.publisher, self.ids, pages, result.generation)
        return pages

    def start(self) -> None:
        """在后台线程中每 `interval` 秒运行一次，直到 `stop`。"""
        def loop() -> None:
            while not self._stop.wait(self.interval):
                try:
                    self.run_once()
                except Exception:  # noqa: BLE001 - 后台任务出错只记日志，下一轮照常运行
                    _log.exception("配置恢复任务出错")

        self._stop.clear()
        self._thread = threading.Thread(target=loop, name="config-recovery", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 1)
