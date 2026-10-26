"""平台错误码与错误异常。HTTP 状态码的映射放在 adapters.http_api，不在这里。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    """请求结构不合法。"""
    SESSION_REQUIRED = "SESSION_REQUIRED"
    """未登录或会话已失效。"""
    SESSION_ROLE_REVOKED = "SESSION_ROLE_REVOKED"
    """会话所选角色已被撤销或账号已停用。"""
    ROLE_SELECTION_REQUIRED = "ROLE_SELECTION_REQUIRED"
    """有多个角色，需要先选择一个。"""
    LOGIN_FAILED = "LOGIN_FAILED"
    CSRF_FAILED = "CSRF_FAILED"
    ORIGIN_REJECTED = "ORIGIN_REJECTED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    """同一请求键携带了不同内容。"""
    REQUEST_IN_PROGRESS = "REQUEST_IN_PROGRESS"
    """同一请求键的请求仍在处理中，稍后用同一个键重试。"""
    DOCUMENT_BUSY = "DOCUMENT_BUSY"
    """加锁等待超时：单据正在被处理。"""
    FROZEN_BY_APPROVAL = "FROZEN_BY_APPROVAL"
    """数据处于审批冻结中。"""
    RULE_REJECTED = "RULE_REJECTED"
    """规则给出了“拒绝”结论。"""
    VALIDATION_FAILED = "VALIDATION_FAILED"
    """字段值不合法（类型、长度、小数位、必填）。"""
    ROW_NOT_FOUND = "ROW_NOT_FOUND"
    """要修改的行已不存在。"""
    FIELD_NOT_WRITABLE = "FIELD_NOT_WRITABLE"
    """字段不允许写入（ERP 列、计算列、主键、无写权限）。"""
    CONFIG_UNAVAILABLE = "CONFIG_UNAVAILABLE"
    """相关配置项发布失败或正在对账，暂不可用。"""
    RECONFIRM_REQUIRED = "RECONFIRM_REQUIRED"
    """审批批准时重算结果与审批人看到的不一致，需刷新后重新确认。"""
    APPROVAL_QUEUED = "APPROVAL_QUEUED"
    """同一单据前面还有待处理的审批，需按顺序处理。"""
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """定位到具体数据的错误或提示。"""

    message: str
    code: str | None = None
    entity: str | None = None
    row_key: str | None = None
    client_row_id: str | None = None
    field: str | None = None


@dataclass(eq=False)
class PlatformError(Exception):
    """业务层抛出的可预期错误。message 面向用户（中文）。"""

    code: ErrorCode
    message: str
    details: tuple[ErrorDetail, ...] = field(default_factory=tuple)
    retry_after_seconds: int | None = None

    def __post_init__(self) -> None:
        super().__init__(f"{self.code}: {self.message}")
