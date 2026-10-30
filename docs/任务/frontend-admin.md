# frontend-admin 任务

模块说明：[frontend-admin](../模块/frontend-admin.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E19（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-FM-1 账号与投递管理

- 归属与目标：实现 FM-01–FM-04。
- 前置输入：开始前 T-CT-4，`ShellApi` 用模拟实现。
- 负责范围：`frontend/src/modules/admin/`。
- 交付物：账号列表、新建、修改、停用、改密码；部门列表；投递记录的查看和重新排队；命令审查的开关和记录查看。
- 接入责任：T-AS-3 注册到外壳；T-AS-7 与真实后端联调。
- 验收标准（模拟验证）：停用账号和撤销角色前先确认；只有已放弃的投递记录能重新排队；非管理员看不到入口。
- 状态与证据：完成（2026-10-29；T-AS-7 联调后在浏览器中通过，见 2026-10-31 核对；待独立复核）。
  - 交付：`frontend/src/modules/admin/`。人员管理（旧 `user-manage`：表格内新增、修改、保存，停用、启用，初始化密码）、部门管理（旧 `dept-manage`：新增、修改、删除、保存）、角色人员（旧角色管理页的"人员列表"：分配人员、解除）、投递记录、命令审查。路由 `/admin` 和 `/admin/<key>`（`ADMIN_SECTIONS`）。
  - 模拟验证：`pnpm exec vitest run tests/admin` 5 个文件 17 个通过（`.reports/modules/frontend-admin/vitest-admin.txt`）；`pnpm test` 18 个文件 431 个通过（`vitest.txt`）；`pnpm typecheck` 本模块 0 个错误，另有 8 个错误在别的模块正在改的文件里（config、request、route store 等，`typecheck.txt`）。
  - 验收标准：停用账号和撤销角色前先确认，确认框提示立即下线（`tests/admin/accounts.test.ts`、`role-members.test.ts`）；只有已放弃的投递记录能重新排队（`deliveries.test.ts`）；非管理员看不到入口：模块这边由 `canUseAdmin` 判断，AdminRoute 对非管理员只显示提示、不调用接口（`module.test.ts`），菜单项是否出现由 `/api/me` 和外壳决定。
  - 没有写测试的部分：命令审查（FM-04）、部门删除。这次点名的正向流程不含它们，只通过了 typecheck。
  - 界面没有在浏览器中运行过：模块还没有注册到外壳（T-AS-3）。
  - 契约缺口：`.reports/modules/frontend-admin/contract-gaps.md`（部门新建修改删除、账号列表 `roleCode` 不在 C09；`AccountUpdate` 没有 `username`；C11 没写 admin 菜单项的路径和确认框）。
  - 真实验证：本模块没有自己的存储，不适用。真实联调：T-AS-7。独立复核：未做。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"待联调"改为"完成"。
    - "界面没有在浏览器中运行过"：模块已注册到外壳，浏览器 `frontend/tests/e2e/admin.spec.ts:17`（人员管理、部门管理）、`basic-1029.spec.ts:200`"场景 2 部门和账号"（新增部门、新增账号）、`:328`"场景 3 角色权限"（角色分配给测试账号）通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。
    - 命令审查（FM-04）、部门删除没有写测试：功能已有，用户没有点名这两条流程，按用户规则（`.kiro/steering/测试范围.md`）不另写。
    - 契约缺口中的"已有账号不能改用户名"（甲核对第四节 B11）和人员、部门管理没有高级查询（B12）：未做，排在第 8 批。
    - "独立复核：未做"：`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。
