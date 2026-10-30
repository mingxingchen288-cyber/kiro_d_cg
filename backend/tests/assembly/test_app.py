"""assembly 的模拟验证（T-AS-2 验收标准中适用于现在代码的各项）：经 FastAPI 的 TestClient 调用 `build_app` 组装的内存组合。

内存组合只用于这里的模拟验证，不是运行模式（AS-01）。插件清单：assembly 的 `system`、`http`、`app`，加上本文件的两个插件：
- `fakes`：contracts 的替代实现 `FakeAuthenticator`、`FakeConfigSnapshotReader`、`FakeCommandExecutor`、`FakeRulesEngine`；start 等到 `warmed`
  被设置才返回，代替 config 的预热（CF-13）。
- `ping`：一个业务模块，只有 `GET /api/ping`，经 `ContextProvider` 取执行上下文。它要用 `http` 提供的 `ContextProvider`，
  而 `http` 要用 `fakes` 提供的 `Authenticator`，所以和 `fakes` 分成两个插件，否则依赖成环。

必须在 `with TestClient(app)` 里调用，lifespan 才会运行各插件的 start。
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient

from cost_platform.assembly.app import build_app
from cost_platform.assembly.cli import main
from cost_platform.assembly.plugins import SESSION_COOKIE, AppPlugin, HttpPlugin, SystemPlugin
from cost_platform.contracts.fakes import (
    FakeAuthenticator,
    FakeClock,
    FakeCommandExecutor,
    FakeConfigSnapshotReader,
    FakeRulesEngine,
)
from cost_platform.contracts.ports import Authenticator, CommandExecutor, ConfigSnapshotReader, ContextProvider, RulesEngine
from cost_platform.contracts.registry import Plugin, PluginView

from ..contracts.support import doc_json, identity, snapshot

ORIGIN = "http://localhost:9527"   # .env.example 的 PLATFORM_ALLOWED_ORIGINS
CSRF = "csrf-112"


class Fakes:
    name = "fakes"
    provides = (Authenticator, ConfigSnapshotReader, CommandExecutor, RulesEngine)
    requires = ()

    def __init__(self) -> None:
        self.authenticator = FakeAuthenticator(FakeClock())
        self.config = FakeConfigSnapshotReader([snapshot()])   # 成本会计的配置快照，代号 13
        self.executor = FakeCommandExecutor()
        self.rules = FakeRulesEngine("0.1.0")
        self.session = self.authenticator.open_session(identity(), CSRF)   # 用户 112，已选角色成本会计
        self.warmed = asyncio.Event()

    def setup(self, reg: PluginView) -> None:
        reg.provide(Authenticator, self.authenticator)
        reg.provide(ConfigSnapshotReader, self.config)
        reg.provide(CommandExecutor, self.executor)
        reg.provide(RulesEngine, self.rules)

    async def start(self) -> None:
        await self.warmed.wait()


class Ping:
    name = "ping"
    provides = (APIRouter,)
    requires = (ContextProvider,)

    def setup(self, reg: PluginView) -> None:
        contexts = reg.get(ContextProvider)
        router = APIRouter()

        @router.get("/api/ping")
        def ping(request: Request) -> dict[str, Any]:
            ctx = contexts.context(request, False)
            return {"userId": ctx.identity.user_id, "roleCode": ctx.identity.role_code}

        reg.add(APIRouter, router)


def memory_plugins(fakes: Fakes) -> list[Plugin]:
    return [SystemPlugin(), HttpPlugin({ORIGIN}), AppPlugin(), fakes, Ping()]


@pytest.fixture
def fakes() -> Fakes:
    return Fakes()


@pytest.fixture
def client(fakes: Fakes) -> Iterator[TestClient]:
    """预热已完成、带用户 112 会话的客户端，请求来自允许的来源。"""
    fakes.warmed.set()
    with TestClient(build_app(memory_plugins(fakes)), headers={"Origin": ORIGIN}) as c:
        c.cookies.set(SESSION_COOKIE, fakes.session)
        yield c


def command(**changes: Any) -> dict[str, Any]:
    """C02 第 1 节的页面保存命令（camelCase）。"""
    return {**doc_json("C02", 0), **changes}


def test_command_and_business_request(client: TestClient) -> None:
    """正常的命令和业务请求；每个响应带 `X-Config-Version`。"""
    saved = client.post("/api/commands", json=command(), headers={"X-CSRF-Token": CSRF})
    assert saved.status_code == 200, saved.text
    assert saved.json()["outcome"] == "unchanged" and saved.headers["X-Config-Version"] == "13"
    ping = client.get("/api/ping")
    assert ping.json() == {"userId": "112", "roleCode": "COST_ACCOUNTANT"} and ping.headers["X-Config-Version"] == "13"
    health = client.get("/health")
    assert health.status_code == 200 and health.json() == {"status": "ok", "coreVersion": "0.1.0", "configVersion": 13}
    assert health.headers["X-Config-Version"] == "13"


def test_request_without_session_is_401(client: TestClient) -> None:
    client.cookies.clear()
    response = client.get("/api/ping")
    assert response.status_code == 401 and response.json()["code"] == "SESSION_REQUIRED"
    assert response.headers["X-Config-Version"] == "13"


def test_write_without_csrf_is_403(client: TestClient) -> None:
    response = client.post("/api/commands", json=command())
    assert response.status_code == 403 and response.json()["code"] == "CSRF_FAILED"
    assert response.headers["X-Config-Version"] == "13"


def test_cross_site_origin_is_rejected(client: TestClient) -> None:
    response = client.post("/api/commands", json=command(), headers={"X-CSRF-Token": CSRF, "Origin": "http://evil.example"})
    assert response.status_code == 403 and response.json()["code"] == "ORIGIN_REJECTED"
    assert response.headers["X-Config-Version"] == "13"


def test_background_request_does_not_touch_session(client: TestClient, fakes: Fakes) -> None:
    assert client.get("/api/ping").status_code == 200
    assert client.get("/api/ping", headers={"X-Background-Request": "1"}).status_code == 200
    calls = fakes.authenticator.calls_to("authenticate")
    assert [c.args for c in calls] == [(fakes.session, None, False, True), (fakes.session, None, False, False)]


def test_snake_case_command_is_rejected(client: TestClient, fakes: Fakes) -> None:
    body = command()
    body["request_key"] = body.pop("requestKey")
    response = client.post("/api/commands", json=body, headers={"X-CSRF-Token": CSRF})
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_FAILED"
    assert fakes.executor.calls_to("execute") == []


def test_requests_wait_for_warm_up(fakes: Fakes) -> None:
    """预热（`fakes` 的 start）完成前 `/health` 返回 503、业务请求返回 CONFIG_UNAVAILABLE；完成后 `/health` 返回 200。

    `warmed` 在事件循环中设置（`client.portal`）：start 随即返回、平台进入就绪，之后发出的请求排在它后面。"""
    with TestClient(build_app(memory_plugins(fakes)), headers={"Origin": ORIGIN}) as client:
        client.cookies.set(SESSION_COOKIE, fakes.session)
        health = client.get("/health")
        assert health.status_code == 503 and health.json() == {"status": "starting"}
        ping = client.get("/api/ping")
        assert ping.status_code == 503 and ping.json()["code"] == "CONFIG_UNAVAILABLE"
        assert "X-Config-Version" not in ping.headers
        assert fakes.authenticator.calls_to("authenticate") == []   # 没有进入路由

        assert client.portal is not None
        client.portal.call(fakes.warmed.set)
        health = client.get("/health")
        assert health.status_code == 200 and health.json() == {"status": "ok", "coreVersion": "0.1.0", "configVersion": 13}
        assert client.get("/api/ping").status_code == 200


def test_platform_help_lists_only_db_and_migrate(capsys: pytest.CaptureFixture[str]) -> None:
    """`platform --help` 的子命令只有 db 和 migrate（AS-05）；migrate 由 migration 提供，migration 暂停，现在只有 db。"""
    with pytest.raises(SystemExit) as exited:
        main(["--help"])
    assert exited.value.code == 0
    found = re.search(r"usage: platform \[-h\] \{(.*?)\}", capsys.readouterr().out)
    assert found is not None
    groups = found.group(1).split(",")
    assert "db" in groups and set(groups) <= {"db", "migrate"}


def test_frontend_files_are_served_with_cross_origin_isolation(fakes: Fakes, tmp_path: Path) -> None:
    """T-AS-7：后端提供前端构建产物，与 `/api` 同源。页面、Worker 脚本和 WASM 的响应带 COOP、COEP（AS-06），
    前端路由的路径（刷新 `/page/COST_PINGGU`）返回 index.html；`/api` 仍由各模块的路由处理。"""
    index = "<!doctype html><title>华益低代码平台</title>"
    (tmp_path / "index.html").write_text(index, encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "worker-C2mHxibJ.js").write_text("self.onmessage = () => {};", encoding="utf-8")
    (tmp_path / "assets" / "rules_core-yCn4y0VT.wasm").write_bytes(b"\0asm\x01\0\0\0")
    fakes.warmed.set()
    with TestClient(build_app(memory_plugins(fakes), frontend_dist=tmp_path), headers={"Origin": ORIGIN}) as client:
        client.cookies.set(SESSION_COOKIE, fakes.session)
        for path, media_type in [("/", "text/html"), ("/page/COST_PINGGU", "text/html"),
                                 ("/assets/worker-C2mHxibJ.js", "text/javascript"),
                                 ("/assets/rules_core-yCn4y0VT.wasm", "application/wasm")]:
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers["content-type"].split(";")[0] == media_type, path
            assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin", path
            assert response.headers["Cross-Origin-Embedder-Policy"] == "require-corp", path
        assert client.get("/page/COST_PINGGU").text == index
        assert client.get("/api/ping").json() == {"userId": "112", "roleCode": "COST_ACCOUNTANT"}
