"""操作、按钮、行和字段权限（docs/模块/authz.md）"""

from .checker import RolePermissionChecker
from .stage import OperationPermissionStage

__all__ = ["OperationPermissionStage", "RolePermissionChecker"]
