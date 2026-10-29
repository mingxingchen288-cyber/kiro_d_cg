"""真实联调共用：按 `.env` 组装的完整后端（`create_app`），等各插件启动完成后再发请求。

启动在后台执行（AS-04）：config 导入基础配置、初始化 ADMIN 角色、预热完成前，`/health` 返回 503 starting，业务请求返回
503 CONFIG_UNAVAILABLE。"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from cost_platform.assembly.app import create_app

STARTUP_SECONDS = 60


@contextmanager
def ready_client() -> Iterator[TestClient]:
    with TestClient(create_app(), base_url="http://localhost:8080") as client:
        deadline = time.monotonic() + STARTUP_SECONDS
        while (health := client.get("/health")).status_code != 200:
            assert health.json() == {"status": "starting"}, health.text
            assert time.monotonic() < deadline, f"{STARTUP_SECONDS} 秒内没有启动完成"
            time.sleep(0.2)
        yield client
