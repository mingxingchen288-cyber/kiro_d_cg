"""真实联调共用的 fixture：两个后端进程（servers.py）、d_cg 引擎和测试数据清理（dcg.py）。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from .dcg import Cleanup, oracle_engine
from .servers import Backend, backends


@pytest.fixture(scope="session")
def servers(tmp_path_factory: pytest.TempPathFactory) -> Iterator[list[Backend]]:
    """两个后端进程 A、B，共用一个 Redis 命名空间；整个测试会话共用，结束时停止。"""
    with backends(Path(tmp_path_factory.mktemp("backends"))) as started:
        assert len(started) == 2, "需要两个后端端口（E2E_BACKEND_PORTS）"
        yield started


@pytest.fixture(scope="session")
def dcg() -> Engine:
    return oracle_engine()


@pytest.fixture
def cleanup(dcg: Engine) -> Iterator[Cleanup]:
    found = Cleanup(dcg)
    yield found
    found.run()
