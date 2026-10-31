"""默认值"当前部门名称"（`currentDeptName`，C06 第 2 节；盘点 B10）：取执行上下文的部门名称（C04 v2），同旧系统
`useWorkingSetStore.ts` 第 552–553 行取 `userInfo.departmentName`。例：技术中心的韩群新增一行，部门列默认填"技术中心"。"""

from __future__ import annotations

from dataclasses import replace

from cost_platform.pipeline.entity_rules import default_value

from .support import Setup, fld


def test_current_dept_name_comes_from_identity() -> None:
    ctx = Setup().context(display_name="韩群")
    ctx = replace(ctx, identity=replace(ctx.identity, department_name="技术中心"))
    field = fld("DEPT_NAME", default={"type": "builtin", "value": "currentDeptName"})
    assert default_value(field, ctx) == "技术中心"

    no_department = replace(ctx, identity=replace(ctx.identity, department_id=None, department_name=None))
    assert default_value(field, no_department) is None
