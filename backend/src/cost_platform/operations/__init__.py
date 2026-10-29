"""通用动作和逃生舱（docs/模块/operations.md）。

- `ButtonInvolvedStage`：管道阶段"确定涉及的单据"的按钮部分（OP-05、OP-08）。
- `ActionStage`：管道阶段"展开动作"（OP-01、OP-02、OP-07）和逃生舱的执行（OP-04、OP-06）；传播边界 OP-03 不另做，
  原因见 stages.py。
- `EscapeHatchRegistry` 等：逃生舱的登记；只登记用户点名启用的逃生舱。
- `plugin.OperationsPlugin`（name `operations`）：创建上面两个阶段并注册为 `PipelineStage`。
"""

from .escape_hatch import (
    BoundArg,
    EscapeHatchExecutor,
    EscapeHatchInvocation,
    EscapeHatchRegistration,
    EscapeHatchRegistry,
    EscapeHatchRunner,
    EscapeParam,
    HandlerCall,
    ProcedureCall,
    SqlEscapeHatchRunner,
    StatementCall,
)
from .memory import EscapeHatchCall
from .stages import ActionStage, ButtonInvolvedStage

__all__ = [
    "ActionStage",
    "BoundArg",
    "ButtonInvolvedStage",
    "EscapeHatchCall",
    "EscapeHatchExecutor",
    "EscapeHatchInvocation",
    "EscapeHatchRegistration",
    "EscapeHatchRegistry",
    "EscapeHatchRunner",
    "EscapeParam",
    "HandlerCall",
    "ProcedureCall",
    "SqlEscapeHatchRunner",
    "StatementCall",
]
