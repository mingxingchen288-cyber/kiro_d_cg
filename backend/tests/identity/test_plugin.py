"""identity 的两个插件（plugin-spec 第 2、5 节）。

- setup：用 contracts 的替代实现提供 requires 的端口，确认 provides 都注册了；
- 真实验证（d_cg + Redis）：db-core 插件提供数据库，启动时初始化 admin（ID-06），经注册的路由登录、读 `/api/me`。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from cost_platform.contracts.fakes import (
    FakeClock,
    FakeConfigSnapshotReader,
    FakeIdGenerator,
    FakeRealtimePublisher,
    FakeUnitOfWorkFactory,
)
from cost_platform.contracts.ports import (
    Authenticator,
    Clock,
    ConfigSnapshotReader,
    DirectoryReader,
    IdGenerator,
    RealtimePublisher,
    UnitOfWorkFactory,
)
from cost_platform.contracts.registry import MULTI_PORTS, PluginView, Registry
from cost_platform.contracts.types import ErrorResponse, PlatformError, dump_wire
from cost_platform.identity.accounts import ADMIN_ROLE, ADMIN_USERNAME, OracleAccounts
from cost_platform.identity.plugin import MIGRATIONS, IdentityDirectoryPlugin, IdentityPlugin
from cost_platform.identity.service import IdentityService
from cost_platform.identity.tables import pf_user, pf_user_role

from .support import ACCOUNTANT, COST_MENU, read_env, role_snapshot

ORIGIN = "http://localhost:9527"   # .env.example 的 PLATFORM_ALLOWED_ORIGINS


class Provider:
    """把给定的实现注册为端口（替代实现，或者测试中已经建好的真实实现）。"""

    requires: tuple[type, ...] = ()

    def __init__(self, name: str, impls: dict[type, Any]) -> None:
        self.name = name
        self.provides = tuple(impls)
        self._impls = impls

    def setup(self, reg: PluginView) -> None:
        for port, impl in self._impls.items():
            reg.provide(port, impl)


class Probe:
    """只声明 requires 的插件：在 setup 中取出被测插件注册的实现（boot 结束后注册表冻结，不能再取）。"""

    name = "probe"
    provides: tuple[type, ...] = ()

    def __init__(self, *ports: type) -> None:
        self.requires = ports
        self.got: dict[type, Any] = {}

    def setup(self, reg: PluginView) -> None:
        self.got = {port: reg.all(port) if port in MULTI_PORTS else reg.get(port) for port in self.requires}


def _fakes(uow: UnitOfWorkFactory, config: ConfigSnapshotReader) -> Provider:
    return Provider("fakes", {UnitOfWorkFactory: uow, Clock: FakeClock(), IdGenerator: FakeIdGenerator(),
                              ConfigSnapshotReader: config, RealtimePublisher: FakeRealtimePublisher()})


def _paths(router: APIRouter) -> set[str]:
    return {route.path for route in router.routes}  # type: ignore[attr-defined]


def test_setup_registers_ports() -> None:
    directory = IdentityDirectoryPlugin()
    identity = IdentityPlugin("redis://127.0.0.1:6379/0", "ct-identity-plugin", 120, frozenset({ORIGIN}))
    probe = Probe(DirectoryReader, Authenticator, APIRouter)
    ordered = Registry().boot([probe, identity, directory, _fakes(FakeUnitOfWorkFactory(), FakeConfigSnapshotReader())])
    assert [p.name for p in ordered] == ["fakes", "identity", "identity.directory", "probe"]
    assert isinstance(probe.got[DirectoryReader], OracleAccounts)
    assert isinstance(probe.got[Authenticator], IdentityService)
    [router] = probe.got[APIRouter]
    assert {"/api/auth/login", "/api/auth/role", "/api/auth/logout", "/api/me", "/api/admin/accounts",
            "/api/admin/departments"} <= _paths(router)
    assert (MIGRATIONS / "id_0001_pf_user.py").is_file()


# ---------------------------------------------------------------- 真实验证：d_cg + Redis

USERNAME = "ct_id_plugin"
PASSWORD = "Abc123.."


@pytest.fixture
def real() -> Iterator[tuple[IdentityPlugin, dict[str, Any]]]:
    """db-core 插件连 d_cg、identity 插件连 Redis（命名空间 `<ns>:ct-identity-plugin`）；结束时删测试账号和键。"""
    import redis

    from cost_platform.assembly.settings import Settings
    from cost_platform.db_core.plugin import DbCorePlugin

    s = Settings.load()
    env = read_env("PLATFORM_REDIS_URL", "PLATFORM_REDIS_NAMESPACE")
    url, namespace = env["PLATFORM_REDIS_URL"], f"{env.get('PLATFORM_REDIS_NAMESPACE', 'cp')}:ct-identity-plugin"
    db = DbCorePlugin(s.db_user, s.db_password, s.db_dsn)
    config = FakeConfigSnapshotReader([role_snapshot(ADMIN_ROLE, "系统管理员", True, COST_MENU),
                                       role_snapshot(ACCOUNTANT, "成本会计", False, COST_MENU)])
    identity = IdentityPlugin(url, namespace, s.session_idle_minutes, frozenset({ORIGIN}))
    probe = Probe(UnitOfWorkFactory, DirectoryReader, APIRouter)
    others = Provider("fakes", {Clock: FakeClock(), IdGenerator: FakeIdGenerator(), ConfigSnapshotReader: config,
                                RealtimePublisher: FakeRealtimePublisher()})
    Registry().boot([db, IdentityDirectoryPlugin(), identity, others, probe])
    client = redis.Redis.from_url(url)

    def cleanup() -> None:
        test_user = pf_user.c.username == USERNAME
        with probe.got[UnitOfWorkFactory].begin() as uow:
            uow.connection.execute(delete(pf_user_role).where(pf_user_role.c.user_id.in_(
                select(pf_user.c.user_id).where(test_user))))
            uow.connection.execute(delete(pf_user).where(test_user))
            uow.commit()
        for key in client.scan_iter(f"{namespace}:*"):
            client.delete(key)

    cleanup()
    yield identity, {"probe": probe, "uow": probe.got[UnitOfWorkFactory]}
    cleanup()
    client.close()
    asyncio.run(db.stop())


@pytest.mark.oracle
@pytest.mark.redis
def test_start_and_login_on_d_cg_and_redis(real: tuple[IdentityPlugin, dict[str, Any]]) -> None:
    identity, parts = real
    asyncio.run(identity.start())   # ID-06：d_cg 上已有 admin 时不改任何内容
    directory: DirectoryReader = parts["probe"].got[DirectoryReader]
    assert ADMIN_USERNAME in [a.username for a in directory.enabled_accounts_with_role(ADMIN_ROLE)]

    OracleAccounts(parts["uow"]).create_account(USERNAME, "插件验证", "581", _argon2(PASSWORD), [ACCOUNTANT])
    app = FastAPI()

    @app.exception_handler(PlatformError)
    async def platform_error(_request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(dump_wire(ErrorResponse, exc.to_response()), status_code=exc.http_status)

    [router] = parts["probe"].got[APIRouter]
    app.include_router(router)
    client = TestClient(app, headers={"Origin": ORIGIN})
    login = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert login.status_code == 200, login.text
    assert login.json()["selectedRole"] == {"code": ACCOUNTANT, "name": "成本会计", "admin": False}
    me = client.get("/api/me").json()
    assert me["user"]["username"] == USERNAME and me["role"]["code"] == ACCOUNTANT and me["configVersion"] == 13


def _argon2(password: str) -> str:
    from cost_platform.identity.passwords import Passwords

    return Passwords().hash(password)
