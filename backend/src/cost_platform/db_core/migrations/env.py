"""Alembic 环境：使用 migrate.py 传入的连接，版本表为 PF_ALEMBIC_VERSION。"""

from alembic import context

_config = context.config
context.configure(
    connection=_config.attributes["connection"],
    version_table=_config.attributes["version_table"],
    target_metadata=None,
    # Oracle 的 DDL 会自动提交：每个脚本单独一个事务，执行完立即记下版本，失败时已完成的脚本不会重复执行
    transaction_per_migration=True,
)
with context.begin_transaction():
    context.run_migrations()
