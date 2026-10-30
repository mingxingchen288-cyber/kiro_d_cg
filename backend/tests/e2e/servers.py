"""真实联调用的后端进程和浏览器会话（经真实的 HTTP 和 WebSocket）。

`backends()` 按根目录 `.env` 启动若干个 uvicorn 进程（`create_app`，与生产启动方式相同），共用一个 Redis 命名空间，
等每个进程的 `/health` 为 200 后返回，结束时停止这些进程。环境变量只传给子进程，不改测试进程和终端的环境：

- 端口取 `E2E_BACKEND_PORTS`（逗号分隔），默认 `8086,8087`；
- `PLATFORM_REDIS_NAMESPACE` 取 `E2E_REDIS_NAMESPACE`，默认 `cost-platform-e2e`，与正在运行的平台（`.env` 中的命名空间）
  分开：会话、配置的 Redis 副本、事件频道、命令审查都在这个命名空间里；
- `PLATFORM_ALLOWED_ORIGINS` 为 `ORIGIN`。

`Browser` 相当于一个浏览器：登录得到会话 Cookie 和 CSRF 令牌，写请求带 Origin 和 `X-CSRF-Token`，`ws()` 带 Cookie 和
Origin 连接 `/ws`。

httpx 和 websockets 都不读系统代理（`trust_env=False`、`proxy=None`）：本机注册表里的系统代理会被 httpx 读到，
连 127.0.0.1 的请求也交给代理，后端已就绪时 `/health` 也拿不到 200。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from websockets.sync.client import ClientConnection, connect

BACKEND_DIR = Path(__file__).resolve().parents[2]
ORIGIN = "http://localhost:9534"
STARTUP_SECONDS = 180


@dataclass
class Backend:
    port: int
    process: subprocess.Popen[bytes]
    log: Path

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/ws"

    def log_tail(self, lines: int = 40) -> str:
        return "\n".join(self.log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def backend_ports() -> list[int]:
    return [int(p) for p in os.environ.get("E2E_BACKEND_PORTS", "8086,8087").split(",") if p.strip()]


def redis_namespace() -> str:
    return os.environ.get("E2E_REDIS_NAMESPACE", "cost-platform-e2e")


def _wait_ready(backend: Backend) -> None:
    deadline = time.monotonic() + STARTUP_SECONDS
    while True:
        assert backend.process.poll() is None, f"{backend.port} 的后端进程已退出：\n{backend.log_tail()}"
        try:
            if httpx.get(f"{backend.url}/health", timeout=5, trust_env=False).status_code == 200:
                return
        except httpx.TransportError:
            pass
        assert time.monotonic() < deadline, f"{backend.port} 的后端 {STARTUP_SECONDS} 秒内没有就绪：\n{backend.log_tail()}"
        time.sleep(0.5)


@contextmanager
def backends(log_dir: Path, ports: list[int] | None = None) -> Iterator[list[Backend]]:
    env = {**os.environ, "PLATFORM_REDIS_NAMESPACE": redis_namespace(), "PLATFORM_ALLOWED_ORIGINS": ORIGIN,
           "PYTHONIOENCODING": "utf-8"}
    started: list[Backend] = []
    try:
        for port in ports or backend_ports():
            log = log_dir / f"backend-{port}.log"
            with log.open("wb") as out:
                process = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "cost_platform.assembly.app:create_app", "--factory",
                     "--host", "127.0.0.1", "--port", str(port)],
                    cwd=BACKEND_DIR, env=env, stdout=out, stderr=subprocess.STDOUT)
            started.append(Backend(port, process, log))
        for backend in started:
            _wait_ready(backend)
        yield started
    finally:
        for backend in started:
            backend.process.terminate()
        for backend in started:
            try:
                backend.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                backend.process.kill()


class Browser:
    """一个浏览器：在一个后端上登录的会话。"""

    def __init__(self, backend: Backend, username: str, password: str) -> None:
        self.backend = backend
        self.http = httpx.Client(base_url=backend.url, timeout=60, headers={"Origin": ORIGIN}, trust_env=False)
        login = self.http.post("/api/auth/login", json={"username": username, "password": password})
        assert login.status_code == 200, login.text
        self.login = login.json()
        self.csrf: str = self.login["csrfToken"]

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.http.get(path, **kwargs)

    def post(self, path: str, body: Any = None) -> httpx.Response:
        return self.http.post(path, json=body, headers={"X-CSRF-Token": self.csrf})

    def put(self, path: str, body: Any) -> httpx.Response:
        return self.http.put(path, json=body, headers={"X-CSRF-Token": self.csrf})

    def ok(self, response: httpx.Response) -> Any:
        assert response.status_code in (200, 204), f"{response.request.method} {response.request.url}：{response.text}"
        return response.json() if response.status_code == 200 else None

    def config_version(self) -> int:
        """响应头 `X-Config-Version`（C09 第 1 节）。"""
        response = self.get("/api/me")
        assert response.status_code == 200, response.text
        return int(response.headers["X-Config-Version"])

    @contextmanager
    def ws(self, pages: list[str] | None = None) -> Iterator[Socket]:
        """连接 `/ws`；给了 `pages` 时订阅这些页面，并等到 `pong`（服务端按顺序处理消息，收到 pong 说明订阅已生效）。"""
        cookie = f"cp_session={self.http.cookies['cp_session']}"
        with connect(self.backend.ws_url, origin=ORIGIN, additional_headers={"Cookie": cookie},  # type: ignore[arg-type]
                     open_timeout=30, proxy=None) as conn:
            socket = Socket(conn)
            if pages:
                socket.send({"type": "subscribe", "pages": pages})
                socket.send({"type": "ping"})
                socket.wait(lambda m: m.get("type") == "pong")
            yield socket

    def close(self) -> None:
        self.http.close()


class Socket:
    def __init__(self, conn: ClientConnection) -> None:
        self.conn = conn

    def send(self, message: dict[str, Any]) -> None:
        self.conn.send(json.dumps(message))

    def wait(self, match: Callable[[dict[str, Any]], bool], seconds: float = 20) -> dict[str, Any]:
        """等到一条满足 `match` 的消息，跳过其他消息（例如别的组保存配置后，本命名空间的恢复任务补发的 config.changed）。"""
        deadline = time.monotonic() + seconds
        while True:
            left = deadline - time.monotonic()
            assert left > 0, f"{seconds} 秒内没有收到期望的消息"
            message = json.loads(self.conn.recv(timeout=left))
            if match(message):
                return message
