"""配置项表 PF_CONFIG_ITEM 和配置代号表 PF_CONFIG_GENERATION（config 模块说明第 2 节、CF-04）。

- PF_CONFIG_ITEM：每个配置项一行，只有当前版本。管理员保存的 C06 配置项和 config 生成的页面视图（`pageView`，
  编码为 `页面编码|角色编码`）、规则包（`rulesPack`，编码为 packId）都在这里。`generation` 是这一项最后一次变化时的配置代号。
- PF_CONFIG_GENERATION：只有一行（id = 1），记录当前配置代号；保存时 `SELECT … FOR UPDATE` 锁这一行排队。
"""

import sqlalchemy as sa
from alembic import op

revision = "cf_0001"
down_revision = None
branch_labels = ("config",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pf_config_item",
        sa.Column("config_type", sa.String(32), nullable=False),
        sa.Column("config_key", sa.String(200), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("content", sa.Text, nullable=False),  # Oracle 中为 CLOB
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("generation", sa.BigInteger, nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),  # Oracle 中为 DATE，精确到秒（C01 第 4 节）
        sa.PrimaryKeyConstraint("config_type", "config_key", name="pk_pf_config_item"),
    )
    op.create_table(
        "pf_config_generation",
        sa.Column("id", sa.Integer, nullable=False),
        sa.Column("generation", sa.BigInteger, nullable=False),
        sa.Column("updated_at", sa.DateTime),
        sa.PrimaryKeyConstraint("id", name="pk_pf_config_generation"),
    )
    op.execute("INSERT INTO pf_config_generation (id, generation) VALUES (1, 0)")


def downgrade() -> None:
    op.drop_table("pf_config_generation")
    op.drop_table("pf_config_item")
