"""账号数据的业务规则。"""

from __future__ import annotations

import re

from cost_platform.contracts.types import ErrorCode, ErrorDetail, PlatformError

PASSWORD_PATTERN = re.compile(r'[\w!@#$%^&*(),.?":{}|<>]{6,18}', re.ASCII)
"""旧系统的密码格式：6–18 位字母、数字、下划线或 `!@#$%^&*(),.?":{}|<>`。

来源：旧后端 `auth/dto/ChangePasswordRequest.java` 的 `@Pattern`，旧前端 `constants/reg.ts` 的 `REG_PWD`。
admin 的初始密码 admin123.. 符合这个格式。
"""


def check_password_format(password: str) -> None:
    if not PASSWORD_PATTERN.fullmatch(password):
        raise PlatformError(ErrorCode.VALIDATION_FAILED, "密码格式不正确，6-18位字符",
                            [ErrorDetail(message="密码格式不正确，6-18位字符", field="password")])
