# write-pipeline 任务

模块说明：[write-pipeline](../模块/write-pipeline.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E01、E04、E05、E06、E08、E28（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-WP-1 命令执行与判重

- 归属与目标：实现 WP-01、WP-02、WP-13 和 `CommandExecutor` 的阶段调度。
- 前置输入：开始前 T-CT-1、T-CT-3。验收前 T-DB-1、T-DB-2。
- 负责范围：`backend/src/cost_platform/pipeline/` 的执行器、阶段注册接口和命令记录存储；表 `PF_COMMAND` 的迁移脚本。
- 交付物：`CommandExecutor`；按架构第 7 节的顺序调用已注册的阶段；判重；失败回滚。
- 接入责任：T-AS-2 注册阶段，T-AS-5 挂载 `POST /api/commands` 并接入真实阶段；approval 调用 `CommandExecutor`。
- 验收标准：模拟验证：同一请求键、相同内容返回原结果，业务流程只执行一次；内容不同返回 IDEMPOTENCY_KEY_REUSED；处理中等待 5 秒后返回 REQUEST_IN_PROGRESS；任一阶段抛错时命令记录和全部写入都不保留；通过 `CommandExecutor` 的契约测试（C08 第 14 节）；真实验证：两个连接用同一请求键并发提交，只执行一次。
- 状态与证据：进行中（2026-10-29），模拟验证通过，真实验证的测试已写好、还没有运行。`CommandExecutor` 的阶段调度随 C08 v14 归 orchestration，不在本模块。
  - 模拟验证：`uv run pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/pipeline`，98 passed（含本卡的 `test_command_log.py`：同一请求键相同内容返回原结果、内容不同 IDEMPOTENCY_KEY_REUSED、按用户区分、失败后命令记录不保留且可重新提交；`test_flow.py` 的 E06）。输出 `.reports/modules/write-pipeline/pytest-pipeline.txt`。
  - 真实验证（待运行，标 oracle）：`tests/pipeline/test_oracle_command_log.py` 3 个：两个连接同一请求键并发只执行一次、处理中等待超时返回 REQUEST_IN_PROGRESS、先提交的回滚后照常执行。
  - 上线后再补：无。

### T-WP-2 加锁、合并与写入

- 归属与目标：实现 WP-03–WP-09、WP-14、WP-15、WP-18。
- 前置输入：开始前 T-WP-1。验收前 T-DB-1、T-DB-3。
- 负责范围：pipeline 的加锁读取、合并、变更计划和业务表写入（Oracle 实现）。
- 交付物：上述功能；写入语句的生成（主表 0 或 1 条，明细按写入的列分组批量执行，用 `RETURNING` 取新主键）。
- 接入责任：T-AS-5 接入真实的 rules-core、authz 和 operations。
- 验收标准：模拟验证：改一格只写该列和计算带出的列；提交相同的值不写业务表；计算字段、主键出现在 Patch 中被拒绝；物料表 ISERP 为 1 的行改 PRICE 被拒，ISERP 为 0 的行可以改；新增行的 ISERP 写为 0；计算值 `1.234567885` 保存为 `1.23456789`，`-1.234567885` 保存为 `-1.23456789`，命令结果与数据库中的值相同；行已被删除时默认跳过，配置为拒绝时返回 ROW_NOT_FOUND；删除主表行时先删明细；必填只检查新增和修改的行；动作执行中 `updateRecords` 找到第 3 步范围外的成本单 E 时，E 先加锁读取、再做冻结检查：E 被别的审批冻结时整个命令返回 FROZEN_BY_APPROVAL、什么都不写，被本审批冻结时放行（WP-18）；基于属性的测试：任意 Patch 的变更计划只含值有变化的列；真实验证：以上在 d_cg 上通过，等锁 5 秒后返回 DOCUMENT_BUSY；两个命令在第 7 步交叉加锁形成死锁时，其中一个返回 DOCUMENT_BUSY 并整体回滚。
- 状态与证据：进行中（2026-10-29），模拟验证通过，真实验证的测试已写好、还没有运行。链路 0、链路 1 的最小部分见 T-AS-9（[assembly](assembly.md)），现有 `SaveFlow` 用法保持兼容（`tests/pipeline/test_compat_saveflow.py`）。
  - 已实现：WP-03（按实体、主键排序，一个实体一条 `FOR UPDATE WAIT n`，行权限判断列在同一条 SQL 中）、WP-04、WP-05、WP-06（每张明细表按关联字段一条 DELETE，再删主表）、WP-07、WP-08（commit 阶段求值，计算带出的变化并入变更计划）、WP-09（按写入的列分组批量执行，新增用序列和 RETURNING）、WP-14、WP-15（列的小数位取 SchemaInspector）、WP-18（范围外单据加锁、只对它们做冻结检查后合并）。明细读取多个明细实体合成一条 UNION ALL 语句。
  - 模拟验证：同一条命令 98 passed，其中 `test_merge.py`（改一格只写该列、相同值不写、计算字段/主键/关联字段被拒、ISERP 为 1 改 PRICE 被拒而为 0 可以、新增行 ISERP 为 0、1.234567885→1.23456789、行已删除跳过或 ROW_NOT_FOUND、删除主表连明细、基于属性的测试：变更计划只含值有变化的列）、`test_values.py`、`test_flow.py`（E04、E05、规则拒绝、必填只查新增和修改的行、WP-18 范围外单据被别的审批冻结时整个命令 FROZEN_BY_APPROVAL 且什么都不写）、`test_document_store_sql.py`（语句文本）。
  - 真实验证（待运行，标 oracle）：`tests/pipeline/test_oracle_store.py` 11 个（视图读取、E05、E04、新增删除明细和 idMap、新单据、删除主表级联和审计、E08、E28、行权限、TableWriter、相同值回滚）。测试自己建 T_WP_* 表并在结束时删除。
  - 上线后再补（用户没有点名的异常情况，工程约定第 5 节）：等锁 5 秒后返回 DOCUMENT_BUSY；两个命令在第 7 步交叉加锁形成死锁时其中一个返回 DOCUMENT_BUSY。行为由 `FOR UPDATE WAIT n` 和 db-core 的错误映射提供，没有写测试。
  - 缺口和待决定事项见 `.reports/modules/write-pipeline/contract-gaps.md`（主从页改主表字段的 SQL 条数、小数位取数据库列、部门名称、规则数据、端口签名）。

### T-WP-3 审计与命令结果

- 归属与目标：实现 WP-11、WP-12。
- 前置输入：开始前 T-WP-2。
- 负责范围：pipeline 的审计差异和命令结果组装。
- 交付物：审计差异（随完成命令记录一起写入）；命令结果（受影响行、`idMap`、提示、`skipped`、审批信息）。
- 接入责任：前端按命令结果局部刷新，T-AS-7 联调。
- 验收标准（模拟验证）：开启审计的页面记录修改、新增、删除（含级联删除的明细）的旧值和新值，关闭审计时不记录；受影响行与提交后数据库中的值相同；`idMap` 覆盖每条新增行。
- 状态与证据：进行中（2026-10-29），模拟验证通过。`result.build_result`（受影响行取自候选数据、含实体全部字段，提交审批的单据给正式值并标冻结，`idMap`、提示、`skipped`、审批信息）、`result.audit_changes` 和 `command_log.audit_rows`（修改记旧值新值、新增记写入的值、删除记删除前的值，含级联删除的明细；TableWriter 的改动不看页面 audit）。
  - 模拟验证：`test_flow.py` 的审计开启/关闭、E04 结果与数据库相同、新增明细 idMap、提交审批的单据不写；`test_command_log.py` 的审计差异格式。
  - 真实验证（待运行，标 oracle）：`test_oracle_store.py` 的删除主表级联审计、E04、idMap。

### T-WP-4 SQL 条数与并发验证

- 归属与目标：验证 WP-10 和并发行为。
- 前置输入：开始前 T-WP-2、T-WP-3、T-DB-3。
- 负责范围：`backend/tests/pipeline/` 的 SQL 追踪和并发测试；rules-core、approval 等用替代实现。
- 交付物：SQL 追踪工具（按语句计数，`executemany` 计 1 条，提交和回滚不计）；测试和结果记录。
- 接入责任：结果供 T-AS-5 复核；可冻结业务多出的 1 条冻结查询在 T-AS-6 验证。
- 验收标准（真实验证）：改主表一个字段 4 条；提交相同的值 2 条；改一条明细并重算汇总 6 条；两人同时改同一单据的不同明细行，两人的修改都保留；先后改同一字段时以后取得锁的为准。达不到时停下来问用户。
- 状态与证据：进行中（2026-10-29），测试已写好、还没有运行；有一项待用户决定。
  - SQL 追踪：`pipeline/tracing.py` 的 `SqlTracer`（SQLAlchemy 游标事件，一次 execute 或 executemany 计 1 条，提交、回滚、连接池探活不计），模拟验证 `test_tracing.py`。
  - 真实验证（待运行，标 oracle）：`test_oracle_sql_count.py` 5 个、`test_oracle_concurrency.py` 2 个。
  - 用户 2026-10-29 选乙：只在改到规则读取的字段时才读明细并求值（WP-08、C08 v17 `rule_fields`；`calc.patch_needs_details`、`calc.needs_recalculation`）。真实验证（d_cg）：`uv run --with <wheel> pytest -q -p no:cacheprovider -m "oracle or redis"` 全部 146 passed（`.reports/modules/yi-real-2.txt`），其中 `test_oracle_sql_count.py` 5 个：主从页改主表 MEMO 4 条、提交相同的值 2 条、单表页 4 条和 2 条、改一条明细并重算汇总 6 条。模拟验证：`test_flow.py` 的 `test_e01_master_field_not_used_by_rules_writes_only_it`（不读明细、不求值、其余列不变）和 `test_master_field_used_by_rules_recalculates_whole_document`。

### T-WP-5 默认值与命令审查

- 归属与目标：实现 WP-16、WP-17 和 C09 第 7a 节的接口。
- 前置输入：开始前 T-WP-2。验收前 Redis 可用。
- 负责范围：pipeline 的默认值补齐、命令审查记录和接口。
- 交付物：上述功能。
- 接入责任：T-AS-5 挂载接口；frontend-admin 使用（T-AS-7）。
- 验收标准：业务例子 E28；模拟验证：不可编辑字段的 builtin 默认值不采用前端传来的值；关闭命令审查时不记录，Redis 中没有记录；真实验证：开启后一条失败的命令也有记录，SQL 条数与 T-WP-4 的追踪一致；关闭后 `{ns}:cmdlog` 被删除。
- 状态与证据：进行中（2026-10-29），模拟验证通过，真实验证的测试已写好、还没有运行（本机 6379 没有 Redis）。
  - 已实现：WP-16（`entity_rules`：static、options 取第一个、builtin 按执行上下文；没有配置时数值 0、其他为空；不可编辑字段的 builtin 不用前端的值）；WP-17（`review.RedisCommandMonitor`，即端口 `CommandMonitor`，2026-10-29 起由 orchestration 包住整个命令事务；`RedisCommandReview`：`{ns}:cmdlog` 最多 10000 条、开关 `{ns}:cmdlog:enabled`、关闭时删除两者、写入失败只记日志）；C09 第 7a 节的 GET、PUT 接口（`review.command_review_router`，只给管理员）。
  - 模拟验证：`test_merge.py`、`test_flow.py` 的 E28；`test_review.py`（关闭时 Redis 中没有记录、开启后成功和失败的命令都有记录且含每条 SQL、关闭时删除、接口）。
  - 真实验证（待运行，标 redis 和 oracle）：`test_redis_review.py` 1 个。
  - 缺口：builtin `currentDeptName` 取不到（C04 没有部门名称），见 contract-gaps.md 第 3 条。
