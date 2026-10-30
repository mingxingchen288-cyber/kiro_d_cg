"""已经结束、结束时没有保存修改内容的审批（ap_0002 之前结束的），按已有记录还原结束那一刻的修改内容，写进 FINAL_VIEW。

还原的依据和范围见 `approval/restore.py`；还原不了的保持为空，详情显示"结束时的值没有保存"。只读 PF_COMMAND
（write-pipeline 的命令记录）和 PF_CONFIG_ITEM（config 的实体配置），所以排在 wp_0001、cf_0001 之后。
只写本模块的 PF_APPROVAL，不改业务表。降级不清空已还原的值（列由 ap_0002 的降级删除）。
"""

from alembic import op

from cost_platform.approval.restore import restore_final_views

revision = "ap_0003"
down_revision = "ap_0002"
branch_labels = None
depends_on = ("wp_0001", "cf_0001")


def upgrade() -> None:
    restore_final_views(op.get_bind())


def downgrade() -> None:
    pass
