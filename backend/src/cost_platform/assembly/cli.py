"""命令行 `platform`（AS-05）：`db` 交给 db-core；`migrate` 以后由 migration 提供。

  platform db upgrade                          执行各模块的平台表迁移
  platform db check                            核对迁移是否为最新，不是时退出码为 1
  platform db copy-business-tables [--refresh 表名 ...]   从 cmx 复制业务表
"""

from __future__ import annotations

import argparse
import sys

from cost_platform.db_core import copy_tables, migrate
from cost_platform.db_core.engine import create_oracle_engine

from .settings import Settings
from .wiring import MIGRATION_DIRS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="platform")
    groups = parser.add_subparsers(dest="group", required=True)
    db = groups.add_parser("db").add_subparsers(dest="action", required=True)
    db.add_parser("upgrade")
    db.add_parser("check")
    copy = db.add_parser("copy-business-tables")
    copy.add_argument("--refresh", nargs="*", default=[])
    args = parser.parse_args(argv)

    settings = Settings.load()
    engine = create_oracle_engine(settings.db_user, settings.db_password, settings.db_dsn)
    if args.action == "upgrade":
        migrate.upgrade(engine, MIGRATION_DIRS)
        print("平台表已是最新")
        return 0
    if args.action == "check":
        missing = migrate.check(engine, MIGRATION_DIRS)
        print("平台表已是最新" if not missing else f"未执行的迁移：{', '.join(missing)}")
        return 0 if not missing else 1
    for line in copy_tables.copy_business_tables(engine, copy_tables.table_specs(), args.refresh):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
