"""PF_APPROVAL 加列 FINAL_VIEW：审批结束（通过、驳回、撤回）那一刻的修改内容（C09 第 6 节的 `view`，JSON），已结束的
审批详情读它（C06 7.6"已结束的审批"）；待审的审批为空。

ap_0001 已在 d_cg 上执行，表的其他列不改。已经结束、没有存过的审批由 ap_0003 尽量还原。
"""

import sqlalchemy as sa
from alembic import op

revision = "ap_0002"
down_revision = "ap_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pf_approval", sa.Column("final_view", sa.Text))


def downgrade() -> None:
    op.drop_column("pf_approval", "final_view")
