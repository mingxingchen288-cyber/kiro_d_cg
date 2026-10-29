"""identity 测试共用的环境（模拟验证）。

- 账号表建在 contracts 的 `FakeUnitOfWorkFactory`（内存 SQLite）上，表结构取自 `identity/tables.py`；主键用计数器代替 Oracle 序列。
- 会话用 `MemorySessions`，时间用 `FakeClock`，事件发到 `FakeRealtimePublisher`。
- 角色取自 `FakeConfigSnapshotReader`（C08 第 4 节的替代实现），经 `describe_role_from` 读取，与上线时的接法相同。
- Argon2 用低强度参数，只为测试快；哈希格式和校验与默认参数相同。
"""

from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from argon2 import PasswordHasher
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.pool import StaticPool

from cost_platform.contracts.fakes import (
    FakeClock,
    FakeConfigSnapshot,
    FakeConfigSnapshotReader,
    FakeIdGenerator,
    FakeRealtimePublisher,
    FakeUnitOfWorkFactory,
)
from cost_platform.contracts.types import MenuItem, RoleConfig, RolePage
from cost_platform.identity.accounts import OracleAccounts
from cost_platform.identity.admin import AccountAdmin
from cost_platform.identity.passwords import Passwords
from cost_platform.identity.service import IdentityService, describe_role_from
from cost_platform.identity.sessions import MemorySessions
from cost_platform.identity.tables import metadata

ROOT = Path(__file__).resolve().parents[3]

ADMIN_ROLE = "ADMIN"
ACCOUNTANT = "COST_ACCOUNTANT"
BUYER = "008"
COST_MENU = [MenuItem(key="cost", title="成本管理", kind="group",
                      children=[MenuItem(key="COST_PINGGU", title="成本核算", kind="page", page_code="COST_PINGGU")])]


def threadsafe_uow() -> FakeUnitOfWorkFactory:
    """`FakeUnitOfWorkFactory`，但它的内存 SQLite 允许在别的线程使用。

    路由把账号读写放进线程池执行（router.py），而替代实现的 SQLite 连接默认只能在建它的线程使用。
    这里只换掉连接参数，事务行为不变；缺口记在 contract-gaps.md。
    """
    uow = FakeUnitOfWorkFactory()
    uow.engine = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"detect_types": sqlite3.PARSE_DECLTYPES, "check_same_thread": False})
    return uow


def fast_passwords() -> Passwords:
    return Passwords(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))


def counter_ids(start: int = 1) -> object:
    counter = itertools.count(start)

    def next_id(_connection: Connection, _sequence: str) -> int:
        return next(counter)

    return next_id


def role_snapshot(code: str, name: str, admin: bool, menus: Iterable[MenuItem] = (), version: int = 13) -> FakeConfigSnapshot:
    pages = {item.page_code: RolePage() for menu in menus for item in menu.children if item.page_code}
    return FakeConfigSnapshot(version=version, role_code=code, role=RoleConfig(name=name, admin=admin, pages=pages),
                              menus=list(menus))


@dataclass
class Env:
    """一套完整的 identity（模拟验证）。"""

    uow: FakeUnitOfWorkFactory = field(default_factory=threadsafe_uow)
    clock: FakeClock = field(default_factory=FakeClock)
    events: FakeRealtimePublisher = field(default_factory=FakeRealtimePublisher)
    ids: FakeIdGenerator = field(default_factory=FakeIdGenerator)
    config: FakeConfigSnapshotReader = field(default_factory=FakeConfigSnapshotReader)
    sessions: MemorySessions = field(default_factory=MemorySessions)
    idle_minutes: int = 120

    def __post_init__(self) -> None:
        metadata.create_all(self.uow.engine)
        self.passwords = fast_passwords()
        self.accounts = OracleAccounts(self.uow, next_id=counter_ids(), passwords=self.passwords)  # type: ignore[arg-type]
        describe = describe_role_from(self.config)
        self.identity = IdentityService(self.accounts, self.sessions, self.clock, self.idle_minutes, describe,
                                        publisher=self.events, ids=self.ids, passwords=self.passwords)
        self.admin = AccountAdmin(self.accounts, self.sessions, describe, publisher=self.events, ids=self.ids,
                                  passwords=self.passwords)
        self.config.put(role_snapshot(ADMIN_ROLE, "系统管理员", True, COST_MENU))
        self.config.put(role_snapshot(ACCOUNTANT, "成本会计", False, COST_MENU))
        self.config.put(role_snapshot(BUYER, "采购", False))

    def add_account(self, username: str, password: str, roles: Iterable[str], *, display_name: str | None = None,
                    department_id: str | None = "581", enabled: bool = True) -> str:
        """经账号存储新建账号，返回账号编号。"""
        created = self.accounts.create_account(username, display_name or username, department_id,
                                               self.passwords.hash(password), list(roles), enabled)
        return created.user_id


def read_env(*names: str) -> dict[str, str]:
    """读取根目录 `.env` 中的这些变量（进程环境变量优先），只供 oracle、redis 测试连接用，不输出。"""
    import os

    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip() in names:
                    values[key.strip()] = value.strip().strip('"').strip("'")
    values.update({n: os.environ[n] for n in names if n in os.environ})
    return values
