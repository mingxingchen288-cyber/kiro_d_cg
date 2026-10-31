"""配置项的保存、删除、校验和读取（CF-01、CF-02、CF-04、CF-07～CF-10）。

一次保存（CF-04）：
1. 开启 Oracle 事务，读出全部配置，按 C06 第 10 节校验（不通过时 422 VALIDATION_FAILED，什么都不写）；
2. `SELECT … FOR UPDATE` 锁代号行，读出当前代号 G-1（多次保存在这里排队）；锁到时代号已经变了，就重读配置、重新校验；
3. 从全部配置重新生成页面视图和规则包，只留内容有变化的；在 Redis 的待生效哈希中登记 G 和本次改动的配置项，
   Redis 不可用时回滚，返回 503 CONFIG_UNAVAILABLE；
4. 写入配置项、版本号加一，代号改为 G，提交；事务超过 30 秒时回滚；
5. 用一个 Lua 脚本写入 Redis 并切换到 G，删除待生效登记；
6. 发布 `config.changed`。
第 4 步提交后，第 5、6 步失败也返回保存成功：配置已经生效，没有同步到 Redis 的部分由恢复任务补齐（CF-05）。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cost_platform.contracts.ports import Clock, IdGenerator, RealtimePublisher, UnitOfWork, UnitOfWorkFactory
from cost_platform.contracts.types import (
    ConfigChangedEvent,
    ConfigChangedPayload,
    ConfigDraft,
    ConfigItem,
    ConfigItemSummary,
    ErrorCode,
    ErrorDetail,
    PagesAudience,
    PageView,
    PlatformError,
    SchemaColumnsResponse,
    SchemaObjectsResponse,
    WizardColumnsRequest,
    WizardColumnsResponse,
    WizardGenerateRequest,
    dump_wire,
)

from .cache import CacheUnavailable, ConfigCache, PendingEntry, SyncBatch
from .catalog import Catalog, referrers
from .packs import build_pack, pack_json
from .records import BASE_TYPES, DERIVED_TYPES, PAGE_VIEW, RULES_PACK, ItemRecord, content_text, item_id, pages_of, view_key
from .store import ConfigStore
from .validation import Validator, check_structure
from .views import build_views

TRANSACTION_SECONDS = 30
SYSTEM_USER = "0"
"""平台自己写入（启动时创建 ADMIN 角色）时的保存人。"""
ADMIN_ROLE = "ADMIN"

_log = logging.getLogger(__name__)


@dataclass
class Change:
    """一次保存的改动。"""

    drafts: list[ConfigDraft] = field(default_factory=list)
    deletes: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class SaveResult:
    generation: int
    versions: dict[tuple[str, str], int]
    """保存的配置项（不含生成的项）的新版本号。"""
    changed: list[str]
    """本次改动的全部配置项编号（含生成的页面视图、规则包和删除的项）。"""


def validation_failed(details: list[ErrorDetail]) -> PlatformError:
    return PlatformError(ErrorCode.VALIDATION_FAILED, "配置校验不通过", details)


def publish_changed(publisher: RealtimePublisher, ids: IdGenerator, pages: list[str], generation: int) -> None:
    """发布 `config.changed`（C10）；发布失败只记日志（C08 第 11 节）。"""
    if not pages:
        return
    try:
        publisher.publish(ConfigChangedEvent(event_id=ids.uuid(), topic="config.changed", audience=PagesAudience(pages=pages),
                                             payload=ConfigChangedPayload(pages=pages, version=generation)))
    except Exception:  # noqa: BLE001 - 发布失败不影响已提交的保存
        _log.exception("发布 config.changed 失败")


def _without_version(content: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in content.items() if k != "version"}


def derive(catalog: Catalog, stored: dict[str, ItemRecord], generation: int, now: datetime, user_id: str,
           core_version: str) -> tuple[list[ItemRecord], list[str]]:
    """从全部配置重新生成规则包和页面视图（CF-02、CF-03、CF-11），返回内容有变化的记录和要删除的生成项。

    规则包和页面视图内容中的 `version` 是它最后一次内容变化时的配置代号：同一版本的内容不变（C05、C09）。
    """
    upserts: list[ItemRecord] = []
    keep: set[str] = set()
    pack_versions: dict[str, int] = {}

    def record(config_type: str, key: str, name: str, content: dict[str, Any]) -> None:
        value = item_id(config_type, key)
        old = stored.get(value)
        upserts.append(ItemRecord(type=config_type, key=key, name=name, content_json=content_text(content),
                                  version=old.version + 1 if old else 1, generation=generation, updated_by=user_id,
                                  updated_at=now))

    for master in catalog.masters():
        if catalog.entity(master) is None:
            continue
        value = item_id(RULES_PACK, master)
        keep.add(value)
        fresh = pack_json(build_pack(catalog, master, 0, core_version))
        old = stored.get(value)
        if old is not None and _without_version(old.content()) == _without_version(fresh):
            pack_versions[master] = int(old.content()["version"])
            continue
        pack_versions[master] = generation
        entry = catalog.get("entity", master)
        record(RULES_PACK, master, entry.name if entry else master, {**fresh, "version": generation})

    for (page_code, role_code), view in build_views(catalog, 0, pack_versions).items():
        key = view_key(page_code, role_code)
        value = item_id(PAGE_VIEW, key)
        keep.add(value)
        fresh = dump_wire(PageView, view)
        old = stored.get(value)
        if old is not None and _without_version(old.content()) == _without_version(fresh):
            continue
        record(PAGE_VIEW, key, f"{view.title}（{role_code}）", {**fresh, "version": generation})

    deletes = [value for value, rec in stored.items() if rec.type in DERIVED_TYPES and value not in keep]
    return upserts, deletes


class ConfigService:
    def __init__(self, uow_factory: UnitOfWorkFactory, validator: Validator, cache: ConfigCache, publisher: RealtimePublisher,
                 clock: Clock, ids: IdGenerator, store: ConfigStore | None = None, *,
                 step_hook: Callable[[str], None] | None = None, monotonic: Callable[[], float] = time.monotonic) -> None:
        """`step_hook` 在保存的每一步之后被调用（`pending`、`committed`、`switched`），只用于验证在各步之后进程退出的情况。"""
        self._uow = uow_factory
        self._validator = validator
        self._cache = cache
        self._publisher = publisher
        self._clock = clock
        self._ids = ids
        self._store = store or ConfigStore()
        self._step = step_hook or (lambda _step: None)
        self._monotonic = monotonic

    # ---------------------------------------------------------------- 读取（C09 第 3 节）

    def list_items(self, config_type: str | None = None) -> list[ConfigItemSummary]:
        with self._uow.begin() as uow:
            _, records = self._store.read_all(uow, [config_type] if config_type else BASE_TYPES)
        return [ConfigItemSummary(type=r.type, key=r.key, name=r.name, version=r.version, updated_by=r.updated_by,
                                  updated_at=r.updated_at)
                for r in sorted(records.values(), key=lambda r: (r.type, r.key)) if r.type in BASE_TYPES]

    def get_item(self, config_type: str, key: str) -> ConfigItem:
        record = self._get(config_type, key) if config_type in BASE_TYPES else None
        if record is None:
            raise PlatformError(ErrorCode.NOT_FOUND, f"配置项 {config_type}/{key} 不存在")
        return ConfigItem(type=record.type, key=record.key, name=record.name, version=record.version,
                          updated_by=record.updated_by, updated_at=record.updated_at, content=record.content())

    def get_pack(self, pack_id: str, version: int) -> dict[str, Any]:
        """规则包（C07 第 1 节）。只保留当前版本；请求的版本不是当前版本时为 404。"""
        record = self._get(RULES_PACK, pack_id)
        content = record.content() if record else None
        if content is None or int(content["version"]) != version:
            raise PlatformError(ErrorCode.NOT_FOUND, f"规则包 {pack_id} 的版本 {version} 不存在")
        return content

    def _get(self, config_type: str, key: str) -> ItemRecord | None:
        with self._uow.begin() as uow:
            return self._store.get(uow, config_type, key)

    # ---------------------------------------------------------------- 新建页面向导（CF-14）

    def wizard_columns(self, request: WizardColumnsRequest) -> WizardColumnsResponse:
        from .wizard import wizard_columns

        with self._uow.begin() as uow:
            return wizard_columns(self._validator.schema, self._validator.sequences, uow, request)

    def schema_columns(self, name: str) -> SchemaColumnsResponse:
        from .wizard import schema_columns

        return schema_columns(self._validator.schema, name)

    def schema_objects(self, keyword: str) -> SchemaObjectsResponse:
        from .wizard import schema_objects

        return schema_objects(self._validator.schema, keyword)

    def wizard_generate(self, request: WizardGenerateRequest, user_id: str) -> SaveResult:
        from .wizard import generate

        return self.commit(lambda catalog: generate(self._validator.schema, request, catalog), user_id)

    # ---------------------------------------------------------------- 校验（POST /api/config/validate）

    def validate(self, drafts: list[ConfigDraft]) -> list[ErrorDetail]:
        problems = check_structure(drafts)
        if problems:
            return problems
        with self._uow.begin() as uow:
            _, records = self._store.read_all(uow, BASE_TYPES)
            catalog = Catalog.from_records(records.values()).merged(drafts)
            return self._validator.check(uow, catalog, [(d.type, d.key) for d in drafts])

    # ---------------------------------------------------------------- 写入

    def save(self, drafts: list[ConfigDraft], user_id: str) -> SaveResult:
        """保存一批配置项（PUT 接口每次一项；契约测试和向导一次几项），一个事务，代号只加一。"""
        problems = check_structure(drafts)
        if problems:
            raise validation_failed(problems)
        return self.commit(lambda _catalog: Change(drafts=list(drafts)), user_id)

    def delete(self, config_type: str, key: str, user_id: str) -> SaveResult:
        """删除一个配置项；仍被其他配置引用时 422（CF-09）。"""
        def change(catalog: Catalog) -> Change:
            if config_type not in BASE_TYPES or not catalog.has(config_type, key):
                raise PlatformError(ErrorCode.NOT_FOUND, f"配置项 {config_type}/{key} 不存在")
            return Change(deletes=[(config_type, key)])
        return self.commit(change, user_id)

    def ensure_admin_role(self) -> bool:
        """CF-10：没有 ADMIN 角色配置时创建它（`admin` 为 true，可访问全部配置和管理功能；已有页面给 `*` 权限，与旧系统
        管理员不受权限限制相同）；已存在时不改。返回是否创建了。"""
        created = []

        def change(catalog: Catalog) -> Change:
            if catalog.has("role", ADMIN_ROLE):
                return Change()
            created.append(True)
            pages = {code: {"buttons": ["*"]} for code in sorted(catalog.pages())}
            return Change(drafts=[ConfigDraft(type="role", key=ADMIN_ROLE, name="系统管理员",
                                              content={"name": "系统管理员", "admin": True, "pages": pages})])

        self.commit(change, SYSTEM_USER)
        return bool(created)

    def commit(self, make_change: Callable[[Catalog], Change], user_id: str) -> SaveResult:
        """在一个事务中按 `make_change` 改配置（CF-04）。`make_change` 拿到当前配置，返回改动；锁到代号行时配置已经变了，
        会用新的配置再调用一次。"""
        with self._uow.begin() as uow:
            started = self._monotonic()
            seen, records = self._store.read_all(uow)
            change, catalog = self._prepare(uow, records, make_change)
            if not change.drafts and not change.deletes:
                return SaveResult(seen, {}, [])
            current = self._store.lock_generation(uow)
            if current != seen:
                _, records = self._store.read_all(uow)
                change, catalog = self._prepare(uow, records, make_change)
            generation = current + 1
            now = self._clock.now().replace(microsecond=0)
            base, base_deletes, versions = self._base_records(change, records, generation, now, user_id)
            derived, derived_deletes = derive(catalog, records, generation, now, user_id,
                                              self._validator.engine.core_version())
            upserts = base + derived
            deletes = base_deletes + derived_deletes
            changed = [r.id for r in upserts] + deletes
            try:
                self._cache.register_pending(PendingEntry(generation, tuple(changed), now))
            except CacheUnavailable:
                raise PlatformError(ErrorCode.CONFIG_UNAVAILABLE, "配置缓存（Redis）不可用，配置没有保存") from None
            self._step("pending")
            for record in upserts:
                self._store.put(uow, record)
            for value in deletes:
                self._store.delete(uow, *value.split("/", 1))
            self._store.set_generation(uow, generation, now)
            if self._monotonic() - started > TRANSACTION_SECONDS:
                uow.rollback()
                raise PlatformError(ErrorCode.INTERNAL_ERROR, f"保存配置超过 {TRANSACTION_SECONDS} 秒，已回滚，配置没有改变")
            uow.commit()
        self._step("committed")
        try:
            self._cache.apply(SyncBatch(generation, upserts, [(v, generation) for v in deletes], [generation]))
        except CacheUnavailable:
            _log.warning("配置代号 %s 已提交，写 Redis 失败，由恢复任务补写", generation)
        else:
            self._step("switched")
        publish_changed(self._publisher, self._ids, pages_of(changed), generation)
        return SaveResult(generation, versions, changed)

    def _prepare(self, uow: UnitOfWork, records: dict[str, ItemRecord],
                 make_change: Callable[[Catalog], Change]) -> tuple[Change, Catalog]:
        catalog = Catalog.from_records(records.values())
        change = make_change(catalog)
        merged = catalog.merged(change.drafts)
        problems: list[ErrorDetail] = []
        for config_type, key in change.deletes:
            merged = merged.without(config_type, key)
            users = referrers(catalog, config_type, key)
            for entry, at in users:
                problems.append(ErrorDetail(message=f"仍被 {entry.type} {entry.key} 引用（{at}），不能删除",
                                            config_type=config_type, config_key=key))
        if problems:
            raise validation_failed(problems)
        if change.drafts:
            problems = self._validator.check(uow, merged, [(d.type, d.key) for d in change.drafts])
            if problems:
                raise validation_failed(problems)
        return change, merged

    @staticmethod
    def _base_records(change: Change, records: dict[str, ItemRecord], generation: int, now: datetime,
                      user_id: str) -> tuple[list[ItemRecord], list[str], dict[tuple[str, str], int]]:
        upserts, versions = [], {}
        for draft in change.drafts:
            old = records.get(item_id(draft.type, draft.key))
            version = old.version + 1 if old else 1
            versions[(draft.type, draft.key)] = version
            upserts.append(ItemRecord(type=draft.type, key=draft.key, name=draft.name, content_json=content_text(draft.content),
                                      version=version, generation=generation, updated_by=user_id, updated_at=now))
        deletes = [item_id(t, k) for t, k in change.deletes]
        return upserts, deletes, versions


def drafts_of(items: Iterable[ItemRecord]) -> list[ConfigDraft]:
    return [ConfigDraft(type=r.type, key=r.key, name=r.name, content=r.content()) for r in items if r.type in BASE_TYPES]
