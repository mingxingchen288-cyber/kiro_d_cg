"""PF_COMMAND 加列 ESCAPE_HATCH_CALLS（OP-04）：逃生舱的调用记录，随完成命令记录的同一条 UPDATE 写入；没有调用时为空。

wp_0001 已在 d_cg 上执行，表的其他列不改。
"""

import sqlalchemy as sa
from alembic import op

revision = "wp_0002"
down_revision = "wp_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pf_command", sa.Column("escape_hatch_calls", sa.Text))


def downgrade() -> None:
    op.drop_column("pf_command", "escape_hatch_calls")
