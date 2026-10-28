"""读取仓库根目录的 `.env`（工程约定第 1 节）；进程环境变量优先。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    db_user: str
    db_password: str = field(repr=False)
    db_dsn: str
    allowed_origins: frozenset[str]
    lock_wait_seconds: int
    session_idle_minutes: int
    config_dir: Path

    @classmethod
    def load(cls) -> Settings:
        env = {**_read_env(ROOT / ".env"), **os.environ}
        return cls(
            db_user=env["PLATFORM_DB_USER"],
            db_password=env["PLATFORM_DB_PASSWORD"],
            db_dsn=env["PLATFORM_DB_DSN"],
            allowed_origins=frozenset(o.strip() for o in env.get("PLATFORM_ALLOWED_ORIGINS", "").split(",") if o.strip()),
            lock_wait_seconds=int(env.get("PLATFORM_LOCK_WAIT_SECONDS", "5")),
            session_idle_minutes=int(env.get("PLATFORM_SESSION_IDLE_MINUTES", "120")),
            config_dir=Path(env.get("PLATFORM_CONFIG_DIR", str(BACKEND / "seed" / "config"))),
        )
