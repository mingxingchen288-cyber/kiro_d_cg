# authz 任务

模块说明：[authz](../模块/authz.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E07（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-AZ-1 权限判断与行权限条件

- 归属与目标：实现 AZ-01–AZ-06、`PermissionChecker` 和"操作权限"阶段。
- 前置输入：开始前 T-CT-1、T-CT-3；C06 第 8 节经用户确认。
- 负责范围：`backend/src/cost_platform/authz/`。
- 交付物：`PermissionChecker`；"操作权限"阶段。
- 接入责任：T-AS-5 接入 write-pipeline 和 queries-export。
- 验收标准（模拟验证）：通过 `PermissionChecker` 和"操作权限"阶段（`PipelineStage`）的契约测试（C08 第 14 节）；用旧系统"技术中心"角色在成本核算页的按钮权限转换后的样例：保存、复制可以，没有复制按钮的区域新增被拒；没有 `system:deleteRow` 时删除被拒；`["*"]` 全部通过；可视化和自定义 SQL 两种行权限都转成带绑定变量的 SQL 条件，`${userId}`、`${username}` 不拼进 SQL 文本；没有行权限时返回 None；来源为审批时不检查行权限和可写字段。条件在 d_cg 上的执行由 T-QE-1、T-WP-2 验证。
- 状态与证据：待联调（2026-10-29）。模拟验证：先写的测试在原有最小实现下 7 个失败、按钮权限的测试因阶段不存在无法收集（`.reports/modules/authz/pytest-0-先写的测试.txt`）；实现后 `uv run pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/authz` 31 个全部通过（`pytest-1.txt`），连同 `tests/contracts/test_permission_checker.py`、`test_pipeline_stage.py`、`tests/unit/test_packages.py` 共 58 个通过（`pytest-2.txt`）；`uv run lint-imports --no-cache` 3 条规则保持（`lint-imports-1.txt`）。覆盖：`PermissionChecker` 和"操作权限"阶段的契约测试；技术中心在成本核算页的真实按钮权限（cmx 只读查询 `01`～`09-*.sql`）：复制主表行连同明细并保存通过、直接提交的新增行因区域有 `copyRow` 通过、去掉包材明细 `copyRow` 后该区域新增被拒（cmx 中技术中心三个区域都有复制，没有现成反例）、没有 `system:deleteRow` 删除被拒、只用选定角色（001 的新增、同步采购价、导出、产品信息维护页都不起作用）、ADMIN `["*"]` 全部通过、按钮操作需要引用它的按钮键、审批处理和审批来源只确认已选角色；技术中心、001 的可视化行权限，C06 第 8 节写法的动态值和自定义 SQL 中 `${userId}`、`${username}` 换成绑定变量；没有行权限和明细实体返回 None；可写字段按页面视图和角色列权限、Lookup 回填目标（E31）、物料清单的 `erpRow`；来源为审批时不查行权限和可写字段。authz 没有 Oracle 或 Redis 存储，没有真实验证的测试。契约缺口见 `.reports/modules/authz/contract-gaps.md`。没有单独测试的规则：没有 `erpRow` 的实体不含 ERP 列（已实现；config 保存时已禁止把这种列设为可写，C06 第 10 节）。接入（T-AS-5）：assembly 把 `OperationPermissionStage(permission)` 注册为第 2 阶段；`RolePermissionChecker()` 构造参数不变。完成前的独立复核未做。
