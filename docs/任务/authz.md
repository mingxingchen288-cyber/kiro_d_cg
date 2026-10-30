# authz 任务

模块说明：[authz](../模块/authz.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E07、E42（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-AZ-1 权限判断与行权限条件

- 归属与目标：实现 AZ-01–AZ-06、`PermissionChecker` 和"操作权限"阶段。
- 前置输入：开始前 T-CT-1、T-CT-3；C06 第 8 节经用户确认。
- 负责范围：`backend/src/cost_platform/authz/`。
- 交付物：`PermissionChecker`；"操作权限"阶段。
- 接入责任：T-AS-5 接入 write-pipeline 和 queries-export。
- 验收标准（模拟验证）：通过 `PermissionChecker` 和"操作权限"阶段（`PipelineStage`）的契约测试（C08 第 14 节）；用旧系统"技术中心"角色在成本核算页的按钮权限转换后的样例：保存、复制可以，没有复制按钮的区域新增被拒；没有 `system:deleteRow` 时删除被拒（2026-10-30 起新增、删除、修改按区域，见 T-AZ-2）；`["*"]` 全部通过；可视化和自定义 SQL 两种行权限都转成带绑定变量的 SQL 条件，`${userId}`、`${username}` 不拼进 SQL 文本；没有行权限时返回 None；来源为审批时不检查行权限和可写字段。条件在 d_cg 上的执行由 T-QE-1、T-WP-2 验证。
- 状态与证据：待联调（2026-10-29）。模拟验证：先写的测试在原有最小实现下 7 个失败、按钮权限的测试因阶段不存在无法收集（`.reports/modules/authz/pytest-0-先写的测试.txt`）；实现后 `uv run pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/authz` 31 个全部通过（`pytest-1.txt`），连同 `tests/contracts/test_permission_checker.py`、`test_pipeline_stage.py`、`tests/unit/test_packages.py` 共 58 个通过（`pytest-2.txt`）；`uv run lint-imports --no-cache` 3 条规则保持（`lint-imports-1.txt`）。覆盖：`PermissionChecker` 和"操作权限"阶段的契约测试；技术中心在成本核算页的真实按钮权限（cmx 只读查询 `01`～`09-*.sql`）：复制主表行连同明细并保存通过、直接提交的新增行因区域有 `copyRow` 通过、去掉包材明细 `copyRow` 后该区域新增被拒（cmx 中技术中心三个区域都有复制，没有现成反例）、没有 `system:deleteRow` 删除被拒、只用选定角色（001 的新增、同步采购价、导出、产品信息维护页都不起作用）、ADMIN `["*"]` 全部通过、按钮操作需要引用它的按钮键、审批处理和审批来源只确认已选角色；技术中心、001 的可视化行权限，C06 第 8 节写法的动态值和自定义 SQL 中 `${userId}`、`${username}` 换成绑定变量；没有行权限和明细实体返回 None；可写字段按页面视图和角色列权限、Lookup 回填目标（E31）、物料清单的 `erpRow`；来源为审批时不查行权限和可写字段。authz 没有 Oracle 或 Redis 存储，没有真实验证的测试。契约缺口见 `.reports/modules/authz/contract-gaps.md`。没有单独测试的规则：没有 `erpRow` 的实体不含 ERP 列（已实现；config 保存时已禁止把这种列设为可写，C06 第 10 节）。接入（T-AS-5）：assembly 把 `OperationPermissionStage(permission)` 注册为第 2 阶段；`RolePermissionChecker()` 构造参数不变。完成前的独立复核未做。

### T-AZ-2 区域的新增、删除、修改

- 归属与目标：AZ-01 的新增、删除、修改改为按区域（主表和每个明细）检查，保存仍按页面（C06 v24 第 8 节、C05 v8）。依据用户 2026-10-30 原话："权限可以按照新增 删除 修改 保存 这样给吗？控制到明细级别"（附另一个系统的角色权限勾选框图，用户只点名新增、删除、修改、保存）。T-AZ-1 中 `system:addRow`、`system:deleteRow` 的判断由本卡取代。
- 前置输入：T-AZ-1；C06 v24、C05 v8 待用户审核。
- 负责范围：authz（`patch_denials`）；config 生成页面视图的按钮过滤和 `canModify`（CF-03）；frontend-page 的可编辑和区域按钮（FP-14）；frontend-config 的按钮权限对话框（FC-12）；seed 的 `role.技术中心.json`。
- 交付物：
  - 权限键 `<区域>:addRow`、`<区域>:deleteRow`、`<区域>:modify`（区域为 `master` 或明细实体编码），`system:save`、`system:advancedSearch`、其余区域按钮、`export:<编码>`、`*` 照旧。
  - 后端（`authz/checker.py` 的 `patch_denials`，"操作权限"阶段）：新增行要 `addRow` 或 `copyRow`，已有行有变化的修改要 `modify`，删除要 `deleteRow`，删除主表行只看 `master:deleteRow`；不满足时 403，明细逐行写明缺的权限键。按钮动作、审批通过时的写入不受这三项限制。
  - 页面视图（`config/views.py`）：区域按钮一律按 `<区域>:<动作>` 过滤，`systemButtons` 只有 `save`、`advancedSearch`；区域加 `canModify`（为 true 时省略）。`SystemButton` 仍接受 `addRow`、`deleteRow`，为的是读还没重新生成的旧页面视图。
  - 前端页面（`page/fields.ts` 的 `writableOnRow`）：`canModify` 为 false 时已保存的行整行不能编辑、不写进命令，新增、复制出的行不受影响；`regionButtons` 只按区域 `buttons`。
  - 配置页（`config/role/role-model.ts`、`RoleButtonDialog.vue`）：页面（保存、高级查询）、"新增、删除、修改"表（一行一个区域）、其余区域按钮、导出。
  - seed：技术中心按旧系统迁移（旧后端保存只检查 save，`DynamicDataService.java` 第 1095 行）：成本核算主表"修改"，原料/辅料、包材"新增""删除""修改"；物料清单 `system:addRow` → `master:addRow`，加 `master:modify`。
- 接入责任：assembly 不变（`RolePermissionChecker()`、`OperationPermissionStage` 的构造参数不变）。d_cg 的 COST_ACCOUNTANT、技术中心由主代理合并后执行 `.reports/batch7-20261030/az-region-permissions/save_role_permissions.py` 改成新键（先读现有内容，是预期的旧内容才保存；COST_ACCOUNTANT 给主表、原料/辅料、包材的"修改"和保存，保持现在能改的范围）。
- 验收标准：E42、E07（[业务例子](../业务例子.md)）；端到端场景 3 按新规则（保存加原料/辅料的修改、额外投料量不可编辑）。只测正向流程。
- 状态与证据：待合并（2026-10-30，分支 batch7/region-permissions，证据 `.reports/batch7-20261030/az-region-permissions/`）。
  - 模拟验证：新测试在旧 `checker.py` 上 4 个失败（`pytest-0-旧实现跑新测试.txt`）；后端全部模拟测试 1297 个通过（`pytest-2-全部模拟.txt`），`lint-imports` 5 条规则保持（`lint-imports.txt`）；前端 `pnpm typecheck`、`pnpm lint:deps` 通过，`pnpm test` 38 个文件 549 个通过（`fe-test-final.txt`），其中 `tests/page/region-permissions.test.ts`（E42、没有修改有新增）和 `tests/config/rules-role-layout.test.ts` 的按钮权限两个用例是新加的。
  - 真实验证：`-m "oracle or redis" tests/authz tests/config` 35 个通过（`pytest-3-真实-authz-config.txt`）；浏览器（`pnpm build:test`，后端 8091，d_cg）场景 3 和 `tests/e2e/region-permissions-1030.spec.ts`（E42）2 个通过（`e2e-1.txt`），测试角色、账号、成本单已删除（`03-用例后.out.txt`）。
  - 兼容：旧代码（`Wire` 不认多出的字段）读不了带 `canModify: false` 的页面视图。新代码在 d_cg 上保存配置后，用户的 8080（旧代码）读 COST_ACCOUNTANT、技术中心的页面视图返回 500；本卡每次在 d_cg 上跑完，都在 8080 建、删一个 PF_TEST 角色让旧代码重新生成，读回 200（`check_8080_views-1.txt`、`-2.txt`）。合并并重启后，新代码能读旧格式的视图（区域按能修改），下次保存配置时重新生成。
  - 没有做：迁移生成器（`migration/access.py`）和只给迁移冒烟用的 `config/page_view.py`、`files.py` 仍按页面级 `system:addRow`、`system:deleteRow`（migration 暂停）。完成前的独立复核未做。
