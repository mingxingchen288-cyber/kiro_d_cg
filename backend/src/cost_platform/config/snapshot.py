"""配置快照（C08 第 4 节 `ConfigSnapshot`、`ConfigSnapshotReader`；CF-05、CF-06、CF-12）。

读取一个角色的快照：
1. 一次 Redis 读取（`ConfigCache.read`）：当前代号、待生效登记；代号与进程中这个角色已有的不同时，再带上角色用到的配置项的
   索引和变化了的内容。没有待生效登记、内容也齐全时，不访问 Oracle。
2. 待生效登记涉及这个角色用到的配置项时，查一次 Oracle（一条语句读出代号和这些配置项）：用 Oracle 的内容，并按代号已达到的
   登记补写 Redis、删除登记、发布 `config.changed`（CF-05）。
3. Redis 中缺项（Redis 被清空、内容被淘汰、角色不在 Redis 中）时回查 Oracle 并补写；回查后角色仍不存在时抛 401
   SESSION_ROLE_REVOKED（C08 第 4 节）。
4. Redis 不可用时直接查 Oracle；Oracle 也不可用时抛 503 CONFIG_UNAVAILABLE。

快照创建后不变（C04）：持有它的请求按它执行到结束。解析结果和规则包句柄按（配置项、版本）缓存在进程中。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from cost_platform.contracts.ports import IdGenerator, RealtimePublisher, RulesEngine, UnitOfWorkFactory
from cost_platform.contracts.types import (
    ApprovalFlowConfig,
    EntityConfig,
    ErrorCode,
    MenuItem,
    OperationConfig,
    PackHandle,
    PageView,
    PlatformError,
    RoleConfig,
    parse_config_content,
    parse_wire,
)

from .cache import CacheUnavailable, ConfigCache, PendingEntry, SyncBatch
from .records import BASE_TYPES, PAGE_VIEW, RULES_PACK, ItemRecord, item_id, pages_of, relevant_to_role, view_key
from .service import publish_changed
from .store import ConfigStore

_log = logging.getLogger(__name__)


class ParsedCache:
    """进程内按（配置项、版本、代号）缓存的解析结果和规则包句柄（模块说明第 2 节"每个进程按版本缓存的解析结果"）。"""

    def __init__(self, engine: RulesEngine) -> None:
        self.engine = engine
        self._models: dict[tuple[str, int, int], Any] = {}
        self._packs: dict[tuple[str, int, int], PackHandle] = {}
        self._lock = threading.Lock()
        self.compiled = 0

    def model(self, record: ItemRecord) -> Any:
        key = (record.id, record.version, record.generation)
        found = self._models.get(key)
        if found is None:
            if record.type in BASE_TYPES:
                found = parse_config_content(record.type, record.content())
            elif record.type == PAGE_VIEW:
                found = parse_wire(PageView, record.content())
            else:
                found = record.content()
            with self._lock:
                self._models[key] = found
        return found

    def pack(self, record: ItemRecord) -> PackHandle:
        """规则包句柄：同一版本只编译一次（RC-03）。编译失败时抛 `PackInvalidError`。"""
        key = (record.id, record.version, record.generation)
        with self._lock:
            found = self._packs.get(key)
            if found is None:
                found = self.engine.load_pack(record.content_json.encode("utf-8"))
                self._packs[key] = found
                self.compiled += 1
            return found


def _visible_menus(items: Iterable[MenuItem], role: RoleConfig) -> list[MenuItem]:
    """CF-12：只留角色可以访问的页面；配置和管理的菜单只给管理员角色；因此变空的分组去掉。"""
    result: list[MenuItem] = []
    for item in items:
        if item.kind == "group":
            children = _visible_menus(item.children, role)
            if children:
                result.append(item.model_copy(update={"children": children}))
        elif item.kind == "page":
            if item.page_code in role.pages:
                result.append(item)
        elif role.admin:
            result.append(item)
    return result


class Snapshot:
    """`ConfigSnapshot`：某个角色在某个配置代号下的配置，创建后不变。"""

    def __init__(self, generation: int, role_code: str, records: Mapping[str, ItemRecord], parsed: ParsedCache) -> None:
        self.version = generation
        self.role_code = role_code
        self._records = dict(records)
        self._parsed = parsed

    def _model(self, config_type: str, key: str) -> Any:
        record = self._records.get(item_id(config_type, key))
        return None if record is None else self._parsed.model(record)

    def _required(self, config_type: str, key: str) -> Any:
        found = self._model(config_type, key)
        if found is None:
            raise PlatformError(ErrorCode.INTERNAL_ERROR, f"已发布的配置中没有 {config_type} {key}")
        return found

    def page_view(self, page_code: str) -> PageView:
        view = self._model(PAGE_VIEW, view_key(page_code, self.role_code))
        if view is not None:
            return view
        if item_id("page", page_code) not in self._records:
            raise PlatformError(ErrorCode.NOT_FOUND, f"页面 {page_code} 不存在")
        if page_code in self.role().pages:
            raise PlatformError(ErrorCode.INTERNAL_ERROR, f"已发布的配置中没有页面 {page_code} 的页面视图")
        raise PlatformError(ErrorCode.PERMISSION_DENIED, f"当前角色不能访问页面 {page_code}")

    def entity(self, code: str) -> EntityConfig:
        found: EntityConfig = self._required("entity", code)
        return found

    def operation(self, code: str) -> OperationConfig:
        found: OperationConfig = self._required("operation", code)
        return found

    def approval_flows(self, page: str) -> list[ApprovalFlowConfig]:
        flows = []
        for record in self._records.values():
            if record.type == "approvalFlow":
                flow: ApprovalFlowConfig = self._parsed.model(record)
                if flow.page == page and flow.enabled:
                    flows.append((flow.order, record.key, flow))
        return [f for _, _, f in sorted(flows, key=lambda x: (x[0], x[1]))]

    def approval_flow(self, code: str) -> ApprovalFlowConfig:
        found: ApprovalFlowConfig = self._required("approvalFlow", code)
        return found

    def role(self) -> RoleConfig:
        found: RoleConfig = self._required("role", self.role_code)
        return found

    def menus(self) -> list[MenuItem]:
        menus = sorted((r for r in self._records.values() if r.type == "menu"), key=lambda r: r.key)
        items = [item for r in menus for item in self._parsed.model(r).items]
        return _visible_menus(items, self.role())

    def rules_pack(self, pack_id: str) -> PackHandle:
        record = self._records.get(item_id(RULES_PACK, pack_id))
        if record is None:
            raise PlatformError(ErrorCode.INTERNAL_ERROR, f"已发布的配置中没有规则包 {pack_id}")
        return self._parsed.pack(record)

    # 供 config 自己使用
    def records(self) -> dict[str, ItemRecord]:
        return dict(self._records)


@dataclass(frozen=True)
class _State:
    generation: int
    records: dict[str, ItemRecord]


class _Missing(Exception):
    """Redis 中缺项：回查 Oracle。"""


class ConfigReader:
    """`ConfigSnapshotReader`。"""

    def __init__(self, uow_factory: UnitOfWorkFactory, cache: ConfigCache, engine: RulesEngine, publisher: RealtimePublisher,
                 ids: IdGenerator, store: ConfigStore | None = None, parsed: ParsedCache | None = None) -> None:
        self._uow = uow_factory
        self._cache = cache
        self._publisher = publisher
        self._ids = ids
        self._store = store or ConfigStore()
        self.parsed = parsed or ParsedCache(engine)
        self._states: dict[str, _State] = {}
        self._lock = threading.Lock()
        self.oracle_reads = 0
        """回查 Oracle 的次数（验证"没有待生效登记时不访问 Oracle"用）。"""

    # ---------------------------------------------------------------- ConfigSnapshotReader

    def read(self, role_code: str) -> Snapshot:
        known = self._states.get(role_code)
        try:
            found = self._cache.read(role_code, known.generation if known else -1)
        except CacheUnavailable:
            return self._from_oracle(role_code, None, 0)
        pending = list(found.pending.values())
        if any(relevant_to_role(i, role_code) for p in pending for i in p.items):
            return self._from_oracle(role_code, pending, found.generation)
        try:
            state = self._merge(known, found.generation, found.index, found.contents)
        except _Missing:
            return self._from_oracle(role_code, pending, found.generation, full=True)
        if item_id("role", role_code) not in state.records:
            return self._from_oracle(role_code, pending, found.generation)
        return self._keep(role_code, state)

    # ---------------------------------------------------------------- 进程中的快照

    def install(self, role_code: str, generation: int, records: Mapping[str, ItemRecord]) -> Snapshot:
        """启动预热（CF-13 第 3 步）：按 Oracle 读出的全部配置项生成这个角色的快照，放进进程缓存。"""
        state = _State(generation, {k: v for k, v in records.items() if relevant_to_role(k, role_code)})
        return self._keep(role_code, state)

    def _keep(self, role_code: str, state: _State) -> Snapshot:
        with self._lock:
            current = self._states.get(role_code)
            if current is None or current.generation <= state.generation:
                self._states[role_code] = state
        return Snapshot(state.generation, role_code, state.records, self.parsed)

    @staticmethod
    def _merge(known: _State | None, generation: int, index: dict[str, tuple[int, int]] | None,
               contents: dict[str, ItemRecord | None]) -> _State:
        if index is None:
            assert known is not None
            return known
        if generation == 0 or (known is not None and generation < known.generation):
            raise _Missing  # Redis 被清空，或者比进程中已有的还旧
        records = {}
        for value, (version, gen) in index.items():
            record = contents.get(value)
            if record is None:
                record = known.records.get(value) if known else None
            if record is None or (record.version, record.generation) != (version, gen):
                raise _Missing
            records[value] = record
        return _State(generation, records)

    # ---------------------------------------------------------------- 回查 Oracle

    def _from_oracle(self, role_code: str, sync: list[PendingEntry] | None, redis_generation: int,
                     full: bool = False) -> Snapshot:
        """查一次 Oracle。`sync` 为 None 表示 Redis 不可用，不补写；否则按 Oracle 补写 Redis（`full` 时读全部配置、整体补写）。"""
        self.oracle_reads += 1
        extra = {i for p in (sync or []) for i in p.items}
        try:
            with self._uow.begin() as uow:
                if full:
                    generation, records = self._store.read_all(uow)
                else:
                    generation, records = self._store.read_for_role(uow, role_code, extra)
        except PlatformError as error:
            raise PlatformError(ErrorCode.CONFIG_UNAVAILABLE, "读不到配置") from error
        if sync is not None:
            self._sync(generation, records, sync, redis_generation, full)
        state = _State(generation, {k: v for k, v in records.items() if relevant_to_role(k, role_code)})
        if item_id("role", role_code) not in state.records:
            raise PlatformError(ErrorCode.SESSION_ROLE_REVOKED, f"角色 {role_code} 已被删除，请重新选择角色")
        return self._keep(role_code, state)

    def _sync(self, generation: int, records: dict[str, ItemRecord], pending: list[PendingEntry], redis_generation: int,
              full: bool) -> None:
        """按 Oracle 补写 Redis（CF-04 第 5 步的写法），删除代号已达到的待生效登记，并发布 `config.changed`。"""
        done = [p for p in pending if p.generation <= generation]
        if full:
            batch = SyncBatch(generation, list(records.values()), [], [p.generation for p in done], full=True)
        elif done:
            batch = delta_batch(generation, records, done, redis_generation)
        else:
            return
        try:
            result = self._cache.apply(batch)
        except CacheUnavailable:
            return
        if result.changed:
            touched = {i for p in done for i in p.items} | set(result.written) | set(result.deleted)
            publish_changed(self._publisher, self._ids, pages_of(touched), generation)


def delta_batch(generation: int, records: Mapping[str, ItemRecord], done: list[PendingEntry], redis_generation: int) -> SyncBatch:
    """按 Oracle 补写这些已生效的待生效登记中的配置项（Oracle 中已没有的项按删除处理）。

    Redis 的代号到 Oracle 的代号之间的每一次保存都在 `done` 中时，补写后 Redis 与 Oracle 一致，切换到 Oracle 的代号；
    否则只补写这些项、不切换代号，由恢复任务整体补写（CF-05）。
    """
    ids = sorted({i for p in done for i in p.items})
    deletes = [(i, max(p.generation for p in done if i in p.items)) for i in ids if i not in records]
    covered = set(range(redis_generation + 1, generation + 1)) <= {p.generation for p in done}
    return SyncBatch(generation if covered else redis_generation, [records[i] for i in ids if i in records], deletes,
                     [p.generation for p in done])
