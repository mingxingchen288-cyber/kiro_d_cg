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
- 状态与证据：进行中（2026-10-29），模拟验证和真实验证通过，待独立复核。`CommandExecutor` 的阶段调度随 C08 v14 归 orchestration，不在本模块。
  - 模拟验证：`uv run pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/pipeline`，98 passed（含本卡的 `test_command_log.py`：同一请求键相同内容返回原结果、内容不同 IDEMPOTENCY_KEY_REUSED、按用户区分、失败后命令记录不保留且可重新提交；`test_flow.py` 的 E06）。输出 `.reports/modules/write-pipeline/pytest-pipeline.txt`。
  - 真实验证（待运行，标 oracle）：`tests/pipeline/test_oracle_command_log.py` 3 个：两个连接同一请求键并发只执行一次、处理中等待超时返回 REQUEST_IN_PROGRESS、先提交的回滚后照常执行。
  - 上线后再补：无。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：`tests/pipeline/test_oracle_command_log.py`（第 23 行标 oracle，两个连接同一请求键并发只执行一次等）在 d_cg 上通过，第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-WP-2 加锁、合并与写入

- 归属与目标：实现 WP-03–WP-09、WP-14、WP-15、WP-18。
- 前置输入：开始前 T-WP-1。验收前 T-DB-1、T-DB-3。
- 负责范围：pipeline 的加锁读取、合并、变更计划和业务表写入（Oracle 实现）。
- 交付物：上述功能；写入语句的生成（主表 0 或 1 条，明细按写入的列分组批量执行，用 `RETURNING` 取新主键）。
- 接入责任：T-AS-5 接入真实的 rules-core、authz 和 operations。
- 验收标准：模拟验证：改一格只写该列和计算带出的列；提交相同的值不写业务表；计算字段、主键出现在 Patch 中被拒绝；物料表 ISERP 为 1 的行改 PRICE 被拒，ISERP 为 0 的行可以改；新增行的 ISERP 写为 0；计算值 `1.234567885` 保存为 `1.23456789`，`-1.234567885` 保存为 `-1.23456789`，命令结果与数据库中的值相同；行已被删除时默认跳过，配置为拒绝时返回 ROW_NOT_FOUND；删除主表行时先删明细；必填检查新增、修改的行和计算带出变化的行（T-WP-8）；动作执行中 `updateRecords` 找到第 3 步范围外的成本单 E 时，E 先加锁读取、再做冻结检查：E 被别的审批冻结时整个命令返回 FROZEN_BY_APPROVAL、什么都不写，被本审批冻结时放行（WP-18）；基于属性的测试：任意 Patch 的变更计划只含值有变化的列；真实验证：以上在 d_cg 上通过，等锁 5 秒后返回 DOCUMENT_BUSY；两个命令在第 7 步交叉加锁形成死锁时，其中一个返回 DOCUMENT_BUSY 并整体回滚。
- 状态与证据：进行中（2026-10-29），模拟验证和真实验证通过，待独立复核。链路 0、链路 1 的最小部分见 T-AS-9（[assembly](assembly.md)），现有 `SaveFlow` 用法保持兼容（`tests/pipeline/test_compat_saveflow.py`）。
  - 已实现：WP-03（按实体、主键排序，一个实体一条 `FOR UPDATE WAIT n`，行权限判断列在同一条 SQL 中）、WP-04、WP-05、WP-06（每张明细表按关联字段一条 DELETE，再删主表）、WP-07、WP-08（commit 阶段求值，计算带出的变化并入变更计划）、WP-09（按写入的列分组批量执行，新增用序列和 RETURNING）、WP-14、WP-15（列的小数位取 SchemaInspector）、WP-18（范围外单据加锁、只对它们做冻结检查后合并）。明细读取多个明细实体合成一条 UNION ALL 语句。
  - 模拟验证：同一条命令 98 passed，其中 `test_merge.py`（改一格只写该列、相同值不写、计算字段/主键/关联字段被拒、ISERP 为 1 改 PRICE 被拒而为 0 可以、新增行 ISERP 为 0、1.234567885→1.23456789、行已删除跳过或 ROW_NOT_FOUND、删除主表连明细、基于属性的测试：变更计划只含值有变化的列）、`test_values.py`、`test_flow.py`（E04、E05、规则拒绝、必填检查的行、WP-18 范围外单据被别的审批冻结时整个命令 FROZEN_BY_APPROVAL 且什么都不写）、`test_document_store_sql.py`（语句文本）。
  - 真实验证（待运行，标 oracle）：`tests/pipeline/test_oracle_store.py` 11 个（视图读取、E05、E04、新增删除明细和 idMap、新单据、删除主表级联和审计、E08、E28、行权限、TableWriter、相同值回滚）。测试自己建 T_WP_* 表并在结束时删除。
  - 上线后再补（用户没有点名的异常情况，工程约定第 5 节）：等锁 5 秒后返回 DOCUMENT_BUSY；两个命令在第 7 步交叉加锁形成死锁时其中一个返回 DOCUMENT_BUSY。行为由 `FOR UPDATE WAIT n` 和 db-core 的错误映射提供，没有写测试。
  - 缺口和待决定事项见 `.reports/modules/write-pipeline/contract-gaps.md`（主从页改主表字段的 SQL 条数、小数位取数据库列、部门名称、规则数据、端口签名）。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：`tests/pipeline/test_oracle_store.py` 11 个（第 42 行标 oracle）在 d_cg 上通过，第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`。等锁 5 秒 DOCUMENT_BUSY、交叉加锁死锁：本条已标上线后再补；死锁一项已被 T-WP-7 的固定加锁层级取代，等锁 DOCUMENT_BUSY 另在 `tests/e2e/test_batch_c.py::test_final_approval_step_fails_and_rolls_back` 中真实出现（同一次）。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-WP-3 审计与命令结果

- 归属与目标：实现 WP-11、WP-12。
- 前置输入：开始前 T-WP-2。
- 负责范围：pipeline 的审计差异和命令结果组装。
- 交付物：审计差异（随完成命令记录一起写入）；命令结果（受影响行、`idMap`、提示、`skipped`、审批信息）。
- 接入责任：前端按命令结果局部刷新，T-AS-7 联调。
- 验收标准（模拟验证）：开启审计的页面记录修改、新增、删除（含级联删除的明细）的旧值和新值，关闭审计时不记录；受影响行与提交后数据库中的值相同；`idMap` 覆盖每条新增行。
- 状态与证据：进行中（2026-10-29），模拟验证和真实验证通过，待独立复核。`result.build_result`（受影响行取自候选数据、含实体全部字段，提交审批的单据给正式值并标冻结，`idMap`、提示、`skipped`、审批信息）、`result.audit_changes` 和 `command_log.audit_rows`（修改记旧值新值、新增记写入的值、删除记删除前的值，含级联删除的明细；TableWriter 的改动不看页面 audit）。
  - 模拟验证：`test_flow.py` 的审计开启/关闭、E04 结果与数据库相同、新增明细 idMap、提交审批的单据不写；`test_command_log.py` 的审计差异格式。
  - 真实验证（待运行，标 oracle）：`test_oracle_store.py` 的删除主表级联审计、E04、idMap。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：本条"真实验证（待运行）"的 `tests/pipeline/test_oracle_store.py`（删除主表级联审计、E04、idMap）在 d_cg 上通过，第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-WP-4 SQL 条数与并发验证

- 归属与目标：验证 WP-10 和并发行为。
- 前置输入：开始前 T-WP-2、T-WP-3、T-DB-3。
- 负责范围：`backend/tests/pipeline/` 的 SQL 追踪和并发测试；rules-core、approval 等用替代实现。
- 交付物：SQL 追踪工具（按语句计数，`executemany` 计 1 条，提交和回滚不计）；测试和结果记录。
- 接入责任：结果供 T-AS-5 复核；可冻结业务多出的 1 条冻结查询在 T-AS-6 验证。
- 验收标准（真实验证）：改主表一个字段 4 条；提交相同的值 2 条；改一条明细并重算汇总 6 条；两人同时改同一单据的不同明细行，两人的修改都保留；先后改同一字段时以后取得锁的为准。达不到时停下来问用户。
- 状态与证据：进行中（2026-10-29），真实验证通过；待用户决定的一项用户已选乙并已实现；待独立复核。
  - SQL 追踪：`pipeline/tracing.py` 的 `SqlTracer`（SQLAlchemy 游标事件，一次 execute 或 executemany 计 1 条，提交、回滚、连接池探活不计），模拟验证 `test_tracing.py`。
  - 真实验证（待运行，标 oracle）：`test_oracle_sql_count.py` 5 个、`test_oracle_concurrency.py` 2 个。
  - 用户 2026-10-29 选乙：只在改到规则读取的字段时才读明细并求值（WP-08、C08 v17 `rule_fields`；`calc.patch_needs_details`、`calc.needs_recalculation`）。真实验证（d_cg）：`uv run --with <wheel> pytest -q -p no:cacheprovider -m "oracle or redis"` 全部 146 passed（`.reports/modules/yi-real-2.txt`），其中 `test_oracle_sql_count.py` 5 个：主从页改主表 MEMO 4 条、提交相同的值 2 条、单表页 4 条和 2 条、改一条明细并重算汇总 6 条。模拟验证：`test_flow.py` 的 `test_e01_master_field_not_used_by_rules_writes_only_it`（不读明细、不求值、其余列不变）和 `test_master_field_used_by_rules_recalculates_whole_document`。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：`tests/pipeline/test_oracle_sql_count.py` 5 个、`test_oracle_concurrency.py` 2 个在 d_cg 上通过，第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`；"待用户决定"的一项用户 2026-10-29 选乙并已实现（本条最后一个子条目）。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-WP-5 默认值与命令审查

- 归属与目标：实现 WP-16、WP-17 和 C09 第 7a 节的接口。
- 前置输入：开始前 T-WP-2。验收前 Redis 可用。
- 负责范围：pipeline 的默认值补齐、命令审查记录和接口。
- 交付物：上述功能。
- 接入责任：T-AS-5 挂载接口；frontend-admin 使用（T-AS-7）。
- 验收标准：业务例子 E28；模拟验证：不可编辑字段的 builtin 默认值不采用前端传来的值；关闭命令审查时不记录，Redis 中没有记录；真实验证：开启后一条失败的命令也有记录，SQL 条数与 T-WP-4 的追踪一致；关闭后 `{ns}:cmdlog` 被删除。
- 状态与证据：进行中（2026-10-29），模拟验证和真实验证通过，待独立复核。
  - 已实现：WP-16（`entity_rules`：static、options 取第一个、builtin 按执行上下文；没有配置时数值 0、其他为空；不可编辑字段的 builtin 不用前端的值）；WP-17（`review.RedisCommandMonitor`，即端口 `CommandMonitor`，2026-10-29 起由 orchestration 包住整个命令事务；`RedisCommandReview`：`{ns}:cmdlog` 最多 10000 条、开关 `{ns}:cmdlog:enabled`、关闭时删除两者、写入失败只记日志）；C09 第 7a 节的 GET、PUT 接口（`review.command_review_router`，只给管理员）。
  - 模拟验证：`test_merge.py`、`test_flow.py` 的 E28；`test_review.py`（关闭时 Redis 中没有记录、开启后成功和失败的命令都有记录且含每条 SQL、关闭时删除、接口）。
  - 真实验证（待运行，标 redis 和 oracle）：`test_redis_review.py` 1 个。
  - 缺口：builtin `currentDeptName` 取不到（C04 没有部门名称），见 contract-gaps.md 第 3 条。第 8 批已在 identity 的 T-ID-4 做了（C04 v2、C09 v15）。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"。
    - 真实验证：`tests/pipeline/test_redis_review.py`（第 27 行标 redis、第 45 行标 oracle）在 d_cg + Redis 上通过，第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`。
    - 缺口 builtin `currentDeptName` 取不到（甲核对第四节 B10），以及命令审查里查询语句没有返回行数（B16，write-pipeline 缺口第 7 节）：未做，排在第 8 批。验收标准的 E28 不用部门名称。
    - `.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-WP-6 启动时预读列定义

- 归属与目标：WP-15 的列定义在平台启动时和配置变更后预读，第一次保存的 SQL 条数与 WP-10 相同。来源：2026-10-30 联调核对 WP-10 时发现，后端进程启动后第一次写某张表的命令多 1 条 `user_tab_columns` 查询（SchemaInspector 取列的小数位），同一进程之后不再读（`.reports/batch2-20261030/g5-acceptance/findings.md`）。
- 前置输入：T-WP-2；config 的 `EntityDirectory`（C08 第 4 节加 `tables`）。
- 负责范围：`pipeline/values.py` 的 `ColumnScales.preload`、`pipeline/warmup.py` 的 `SchemaWarmup`、`pipeline/plugin.py` 的 start、stop；`config/entities.py` 的 `tables`；contracts 的端口、替代实现和契约测试。缓存在本模块（db-core 的 `SchemaInspector` 不缓存，config 的校验、新建页面向导要读到最新的表结构），所以预读在本模块做。
- 交付物：插件 start 时预读已发布实体写入的表，读完才返回；后台每 5 秒检查一次，新的表读进来；stop 停掉后台检查。WP-10 中"审批入口条件每行一条"不在本卡（等用户决定）。
- 验收标准：后端启动后第一次保存不再有 `user_tab_columns` 查询；配置变更新增实体后，后台读进新的表。
- 状态与证据：进行中（2026-10-30，H2 组，`batch3/approval-snapshot`；待独立复核）。模拟验证：`tests/pipeline/test_warmup.py` 2 个（start 读完已发布实体的表才返回，之后新增实体的表由后台读进来，保存时取小数位不再读；插件 start、stop），`test_values.py` 的预读不重复读，`EntityDirectoryContract.test_tables`（替代实现、`PublishedEntities`），`tests/pipeline tests/config tests/contracts tests/assembly` 705 passed。真实验证：`tests/config/test_oracle.py` 的 `TestOraclePublishedEntities` 4 passed（d_cg 已有这四个实体，没有保存配置）；后端 8088 启动日志"已预读列定义：T_COST_GOODS、T_COST_PINGGU、T_COST_PINGGU_DTL"在"开始接受请求"之前；打开命令审查后，后端启动后的第一次保存（成本单 2550 改单价、提交审批）21 条 SQL，没有 `user_tab_columns`（`.reports/batch3-20261030/h2-approval/h2.out.json`）。同一次核对中第一次审批通过有 2 条 `user_tab_columns`（T_COST_GOODS），来自 approval 计算受影响单据时每次读修改表的列（`approval/view.py` 的 `_affected_table`），不是本卡的 ColumnScales，没有改。`tests/e2e/test_batch_b.py` 中允许多 1 条列定义查询的断言（`sum(map(is_schema_query, sql)) <= 1`）没有改、没有运行（别组在用 8086、8087）。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：本条末尾没有运行的 `tests/e2e/test_batch_b.py` 通过（第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`）；其中允许多 1 条列定义查询的断言（`<= 1`）没有收紧，只是测试写法，不影响验收的两项（启动后第一次保存没有 `user_tab_columns`、新增实体后后台读进新表，本条已验证）。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-WP-7 固定加锁层级

- 归属与目标：按用户 2026-10-30 同意的"固定加锁层级"改 WP-03、WP-13、WP-18、WP-19：等锁可以，不能死锁；每条命令只执行一遍。依据和穷举检查见 `.reports/concurrency-c04-20261030/`（`model_check_v3.py`）。取代 T-WP-2 验收标准中"两个命令交叉加锁形成死锁时其中一个返回 DOCUMENT_BUSY"一项：按新规则不再出现死锁。
- 前置输入：T-WP-2；contracts 加端口 `BusinessLocker`（C08 v18 第 5b 节）。
- 负责范围：`pipeline/locks.py`（统一入口：`LockBook` 顺序检查、`PipelineLocks`、全部 `FOR UPDATE` 文本）、`document_store.py` 的 `lock_load`、`read_masters`、`lock_key`、`read_documents`，`loader.py` 的 `DocumentLoader`（统一顺序、`defer_lock`），`table_writer.py` 的 `lock_row`，`merge.py` 的 `IntentMerger`（去掉中途加锁），`plugin.py`；orchestration `runner.py`（`LockScopeChanged` 时整个回滚、重来）；`backend/tests/architecture/test_lock_entry.py`。
- 交付物：上述功能；端口 `BusinessLocker` 交给 approval、operations。
- 接入责任：approval（T-AP-6）、operations（T-OP-4）经端口加锁；assembly 不用改插件清单（pipeline 插件多提供一个端口）。
- 验收标准：一张单据的保存 SQL 条数不变（WP-10）；一次锁多行时按顺序每行一条；后加的锁排在已持有的锁之前时 500；业务模块里除入口外没有 `FOR UPDATE`、`with_for_update`（三处例外）；d_cg 上并发重放冻结别的单据时有人同时保存、成本单改价和物料清单改价同时进审批、三方交叉，不出现 ORA-00060，冻结生效后别人的修改提交不了，每条命令只执行一遍（规则 4 的例外除外）。
- 状态与证据：进行中（2026-10-30，L 组，`batch4/lock-order`），模拟验证和真实验证通过，合并后联调通过，待独立复核。
  - 模拟验证：`tests/contracts/test_business_locker.py`（契约，替代实现和 `PipelineLocks` 都跑）、`tests/pipeline/test_locks.py`（统一顺序、往后追加、已持有再锁、`defer_lock` 只读、`TableWriter` 共用顺序）、`test_document_store_sql.py`（一张单据一条、多张每行一条）、`tests/orchestration/test_runner.py` 的规则 4 重来；`backend` 下 `pytest -m "not oracle and not redis"` 全部通过（条数见 `.reports/batch4-20261030/l-lock-order/progress.md`）。
  - 真实验证（d_cg）：`tests/pipeline/test_oracle_lock_order.py` 8 个场景（建删 PF_TEST_LK_* 表，审批流只在内存配置中）全部通过，没有 ORA-00060、没有等锁超时，只有规则 4 的场景执行两次；输出和残留核对见 `.reports/batch4-20261030/l-lock-order/`。WP-10 条数测试 `test_oracle_sql_count.py` 照常通过。
  - 穷举：`model_check_v3.py` 重跑结果与原结果相同（`.reports/batch4-20261030/l-lock-order/model-check/`）。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中……合并后没有联调"改为"完成……合并后联调通过"：main 上 `tests/pipeline/test_oracle_lock_order.py` 和 `tests/e2e` 的联调用例通过（第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`），浏览器端到端也通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-WP-8 计算带出变化的行也检查必填

- 归属与目标：WP-07 改为按旧系统：页面保存时，必填检查的行 = 本次新增、修改的行 ∪ 计算后有计算字段变化的行，删除的行不查。来源：旧系统 `useWorkingSetStore.ts` 第 886–934 行（保存时对有修改的行检查，含 `useCalcBroadcast.ts` 记成 `calc` 的计算带出变化）、`validator.ts` 第 52–85、116 行（列的 required）；上一组的核对见 `.reports/batch3-20261030/h1-rules-dirty/findings.md`；用户 2026-10-30 同意按旧系统做。rules-core 的校验规则已经这样做（C07 v7）。
- 前置输入：T-WP-2。
- 负责范围：`pipeline/stages.py` 的 `calc_changed_rows`、`required_rows`，`pipeline/calc.py` 的 `check_required`。
- 交付物：计算带出变化的行由变更计划推出：修改的行中含计算字段的（Patch 和动作都不能写计算字段，计划中的计算字段只来自计算）。按钮操作、审批处理不带 Patch，不检查必填（旧系统按钮由后端执行，不经前端保存的校验），与原来相同。
- 验收标准（业务例子）：d_cg 单据 2555（4mg马来酸氯苯那敏片）原料"马来酸氯苯那敏"（102126）每片含量 4、单价为空，页面配了原辅料单价必填；只改批量 3500000 → 4000000，它的每批数量 14 → 16，保存返回 422 VALIDATION_FAILED，只指出这一行的"单价 不能为空"，不写库。单据 2757 改批量能保存：每批数量变了的原辅料单价、每片含量都有，单价为空的 207577（每片含量 0）每批数量仍是 0，不检查。
- 状态与证据：模拟验证和浏览器拒绝的一半通过（2026-10-30，P 组，`batch4/pipeline-fixes`）。浏览器（后端 8084 + d_cg，`.reports/batch4-20261030/p-pipeline-fixes/e2e/p1.out.json`、`p1-rejected.png`）：2555 批量改 4000000 保存，422 VALIDATION_FAILED，提示"有必填字段没有填写：单价 不能为空（原料/辅料 马来酸氯苯那敏）"，刷新后批量仍是 3500000；能保存的一半只有后端测试（真实单据保存批量会让每批数量变化的原辅料逐行判断 COST_TO_GOODS，可能提交审批，没有在浏览器做）。`tests/pipeline/test_validate_changed_rows.py` 的 `test_2555_change_batch_price_required_rejected`（数据 `tests/pipeline/data/doc-2555.json`，取自 d_cg 只读查询 `.reports/batch4-20261030/p-pipeline-fixes/q02-单据2555.sql`，真实 rules-core 和 seed 规则）、`test_2757_change_batch_saves`、`test_2757_change_batch_checks_changed_rows_required`；`test_flow.py` 的 `test_required_checked_on_rows_changed_by_calculation`（原 `test_required_not_checked_on_rows_changed_only_by_calculation` 按新规则改写）。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）："能保存的一半"（2757 改批量能保存）只有后端测试：`tests/pipeline/test_validate_changed_rows.py::test_2757_change_batch_saves`（真实 rules-core、seed 的规则、从 d_cg 只读取来的单据数据）通过（第 7 批合并后模拟全量 1309 passed，`.reports/batch7-20261030/merge/pytest-1.txt`）；浏览器只核对了拒绝的一半，开头不改。

### T-WP-9 写入修改人

- 归属与目标：实现 WP-20：实体配置 `updatedByColumn`（C06 v19 第 2 节）后，新增、修改这个实体的行时写当前用户的登录名，审批通过时写审批人。来源：旧系统 `DynamicDataService.java` 第 290–293、392–393 行（UPDATE_BY = `SecurityUtils.getCurrentUsername()`，取 JWT 的 username，即登录名，`JwtAuthenticationFilter.java` 第 38–49 行）；审批通过在审批人的请求中执行（`ConfiguredApprovalRuntime.java` 的 `applyPending`）；用户 2026-10-30 同意按旧系统做。
- 前置输入：T-WP-2；contracts 的 `EntityConfig.updated_by_column`；config 的保存校验（列在表中、不是实体字段的列）。
- 负责范围：`pipeline/writer.py` 的 `_stamped`、`_write_stamped`（写入时在实体和变更计划的副本上加修改人字段，不改 `document_store.py`）；seed 的 `entity.COST_GOODS_PRICE.json` 配 `"updatedByColumn": "UPDATE_BY"`。成本核算的表在 d_cg 没有 UPDATE_BY 列（DB-03），不配。
- 验收标准：模拟验证：改本地物料、新增物料时同一条语句写修改人，命令结果中没有它，没配的实体不写，来源为审批时写审批人的登录名。真实验证（业务例子）：测试自己建一个 ERP 物料（ISERP = 1、UPDATE_BY = `ERP_SYNC`），admin 在物料清单页改它的单价，提交审批 GOODS_TO_COST，admin 通过后 T_COST_GOODS 的 UPDATE_BY 为 admin、单价写入，视图 T_COST_GOODS_PRICE_V 的 ROW_CLASS_FLAG 为 `erp-updated`（黄底）；测试结束删掉这个物料、审批和命令记录。
- 状态与证据：模拟验证和真实验证通过（2026-10-30，P 组，`batch4/pipeline-fixes`）。模拟验证 `tests/pipeline/test_updated_by.py` 4 个；真实验证 `tests/pipeline/test_oracle_updated_by.py` 1 个（d_cg，进程内接真实的权限、写入管道、审批阶段和审批服务，测试的内存配置取 seed）：ERP 物料改单价 12 提交 GOODS_TO_COST，admin 通过后 UPDATE_BY = admin、ZX_PRICE = 12、ROW_CLASS_FLAG = erp-updated；物料、审批、命令记录已删（`.reports/batch4-20261030/p-pipeline-fixes/q03-修改人测试清理核对.out.txt`）。`tests/config/test_oracle.py::test_seed_config_validates_against_d_cg` 通过（只校验不写）。浏览器部分（物料清单页黄底）要等 d_cg 写入新配置后由主代理做。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：浏览器部分（物料清单页黄底）已做：`frontend/tests/e2e/sample-two.spec.ts:94`（7.10）第 167 行断言审批通过后整行底色为 rgb(255, 242, 168)，第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`。

### T-WP-10 复制出的行写入复制的全部字段

- 归属与目标：实现 WP-21（C02 v8 的 `copyOf`）：复制出的行保存时，复制对话框里勾选的字段都写进新行，不论能不能编辑；后端按源行核对，不信前端给的不可写字段的值。来源：旧系统 `copy-row-fields.ts` 第 23–29 行、`useWorkingSetStore.ts` 第 834–876 行、`DynamicDataService.java` 第 274–327 行；现象见 `.reports/batch3-20261030/h3-new-doc/findings.md`、`v3-verify/findings.md` 观察 2-1（复制 200721 后币种、项目号为空）；用户 2026-10-30 同意按旧系统做。
- 前置输入：T-WP-2；contracts 的 `MasterAdd.copy_of`、`DetailAdd.copy_of`。
- 负责范围：`pipeline/copies.py`（`OracleCopySources`：按主键读源行，每个实体一条，不加锁，带行权限）；`pipeline/merge.py` 中 `_Rows.new_values` 的 `source`、`_copied_values` 和 `DocumentMerger` 的接线（小改动，IntentMerger 没动）；`pipeline/stages.py` 的 `MergePatchesStage`、`plugin.py`。
- 验收标准：模拟验证：复制成本单时不可写的产品名称、创建人取源行的值（命令中的伪造值不用），计算字段不写，没复制的字段不补默认值；没有 `copyOf` 的新增行照旧拒绝不可写字段；源行超出行权限时 409 ROW_NOT_FOUND；明细复制只在视图中的物料名称、计算字段不写。业务例子（浏览器）：复制 200721 只复制主表，保存后新单据的币种为"人民币"、项目号与源单据相同（源为空则为空），产品等字段照旧；之后删掉这张单据。
- 状态与证据：模拟验证和浏览器业务例子通过（2026-10-30，P 组，`batch4/pipeline-fixes`）：`tests/pipeline/test_copy.py` 4 个；前端 `tests/page/copy-lookup.test.ts`、`product-lookup.test.ts` 的命令带 `copyOf` 和不可编辑的复制字段。浏览器（后端 8084 + d_cg，`.reports/batch4-20261030/p-pipeline-fixes/e2e/p2.out.json`）：复制 200721 只复制主表，命令带 `copyOf: 200721` 和币种"人民币"，保存后新单据 200834 的币种"人民币"、项目号为空（与源相同）、产品ID 392，随后删掉。
  - 复制出的行提交审批后最终通过时的写法（原来按 Patch 重放，不可写的复制字段按命令中的值写、补默认值）：2026-10-30 B2 组改为按提交时解出的值写、不补默认值，本模块只改 `IntentMerger._add`（意图带 `copy_of` 时 `_Rows.new_values(defaults=False)`），见 approval 的 T-AP-7。

### T-WP-11 按钮新增的明细不补默认值

- 归属与目标：WP-16 加例外：按钮 `replaceDetails` 新增的行（OP-09）只写 SQL 给出的字段、关联字段、主键和计算规则算出的字段，其余列不进 INSERT，取数据库的列默认值。来源：旧 P_COST_BOM_INSERT（`my-project/sql20260523/03_program_units.sql` 第 699–760 行）的 INSERT 列中没有 EXADD_MATER、CUSTOMER_SPECIFIED；现象见 `.reports/batch4-20261030/p-pipeline-fixes/findings.md`"和旧系统不同、这次没改的"（由BOM生成明细写 EXADD_MATER = 0）；用户 2026-10-30 同意直接做。
- 前置输入：T-WP-5（WP-16）、T-OP-3（`replaceDetails`）；contracts 的 `RowIntent.fill_defaults`（C08 v19）。
- 负责范围：`contracts/types.py` 的 `RowIntent.fill_defaults`（默认 True）；`pipeline/merge.py` 的 `_Rows.new_values(defaults=)`、`IntentMerger._add`；`operations/sql_actions.py` 的 `expand_replace_details`（新增意图设为 False）。审批通过时写入的待审新增行（`approval/patch.py`、`process.py` 生成的意图）不改，照旧补默认值。
- 验收标准（业务例子）：新建一张产品 392 的成本单点"由BOM生成明细"，新增的 11 行明细额外投料量为空、客户指定为 T_COST_PINGGU_DTL 的列默认值 0（d_cg `USER_TAB_COLUMNS`：EXADD_MATER 没有默认值、可空；CUSTOMER_SPECIFIED NOT NULL、DATA_DEFAULT 0），每批数量、每批成本、主表合计照常算出（空值按 0 参与计算，rules-core 第 8 节；旧 P_PINGGU_DTL_COMPUTE 也是 `nvl(exadd_mater, 0)`）；页面显示与重新打开一致。
- 状态与证据：模拟验证、真实验证和浏览器业务例子通过（2026-10-30，B1 组，`batch5/pipeline-defaults`，`.reports/batch5-20261030/b1-pipeline/`）。模拟：`tests/pipeline/test_flow.py` 的 `test_button_added_detail_writes_only_given_linked_and_calculated_fields`（INSERT 只有 DOCID、GOODSID、PRICE、COST_BATCH），E24 补"审批通过照旧补 0"；`tests/operations/test_sql_actions.py` 新增意图 `fill_defaults` 为 False。真实（d_cg）：`tests/operations/test_sql_actions_oracle.py` 的由BOM生成明细断言 11 行 EXADD_MATER 为空、CUSTOMER_SPECIFIED 为 0，`check_recalculated` 照常通过。浏览器：`frontend/tests/e2e/g0-1030.spec.ts` 场景 5a 断言接口读到的明细额外投料量为 null、客户指定为 false、每批数量有值，页面上额外投料量格子为空、客户指定不勾，重新打开（`openDoc`）后一样。契约测试 `test_samples.py` 的默认值检查改为允许文档写明的默认值。

### T-WP-12 往前冻结的页面保存少一条 SQL

- 归属与目标：T-WP-7 留下的代价（`.reports/batch4-20261030/l-lock-order/findings.md`"已知的代价"）：配了往前冻结审批流的页面（物料清单页，GOODS_TO_COST）每次保存推迟加锁，多 1 条加锁前普通读取、1 条锁住后核对重读。把"锁 + 核对重读"合成一条带数据的加锁语句，只多加锁前的 1 条。用户 2026-10-30 同意直接做；规则 1–9 不变。
- 前置输入：T-WP-7。
- 负责范围：`pipeline/locks.py` 的 `PipelineLocks.lock`（`expected` 中的单据按顺序轮到时用"锁一行并读出数据"的语句，锁住后用它核对；其余对象照旧只锁；本事务已持有锁的单据仍普通重读）、`KeyLocker.lock_document`；`pipeline/document_store.py` 的 `lock_document`（与普通保存的 `lock_load` 一个主键时同一条语句，有明细时另一条普通查询读明细）。
- 验收标准：一次锁多行仍按统一顺序每行一条（规则 7）；本命令单据在加锁前读取之后被改时仍整个回滚重来（规则 4）；`tests/pipeline/test_oracle_lock_order.py` 原有 8 个场景照样通过；物料清单页保存的 SQL 条数比原来少 1 条。
- 状态与证据：模拟验证和真实验证通过（2026-10-30，B1 组，`batch5/pipeline-defaults`，`.reports/batch5-20261030/b1-pipeline/`）。模拟：`tests/pipeline/test_locks.py` 的 `test_lock_with_expected_reads_own_documents_in_the_lock_statements`（先锁成本单 1001、再锁住并读出物料 115，`read_documents` 只有加锁前的一次）、`test_lock_with_expected_changed_meanwhile_raises`；`test_document_store_sql.py` 的 `test_deferred_lock_reads_the_own_document_in_the_lock_statement`（SQL 文本）；`tests/contracts/test_business_locker.py` 照常通过。真实（d_cg）：`test_oracle_lock_order.py` 8 个场景通过（规则 4 的场景 d 仍执行两次），新加 e1（PF_TEST 物料清单页改名称 8 → 7 条）、e2（改执行价进审批、冻结成本单 16 → 15 条，加锁语句只有成本单、物料两条）；`tests/pipeline/test_oracle_goods_save_sql_count.py`（seed 配置的物料清单页 GOODS_PRICE_MANAGE，测试自建本地物料、改规格不触发审批）8 → 7 条。

### T-WP-13 审计追踪视图

- 归属与目标：实现 WP-22，给审计追踪页（config 的 T-CF-11）一个按字段展开的视图。来源：盘点 `.reports/inventory-20261030/乙-旧系统功能对照.md` 第 1、4 节（审计追踪 auditLog）；用户 2026-10-30 对第 4 节回复"要"、2026-10-31 回复"开始"。
- 前置输入：T-WP-3（审计差异 WP-11）；identity 的 `PF_USER`（id_0001）、config 的 `PF_CONFIG_ITEM`（cf_0001）。
- 负责范围：`pipeline/migrations/wp_0003_audit_log_view.py`（`CREATE OR REPLACE VIEW PF_AUDIT_LOG_V`，依赖 id_0001、cf_0001）。审计差异中字段是对象的键，Oracle 19c 的 JSON_TABLE 取不到键名，先用正则改写成数组再展开（写法见迁移文件开头）。
- 交付物：视图 `PF_AUDIT_LOG_V`。
- 验收标准：真实验证（d_cg）：admin 在成本核算改了单据 200680 主表的备注（空 → PF_TEST审计）、原辅料一行的客户指定（否 → 是），又删了一行原辅料：视图给出每个字段一行，操作类型为 UPDATE、DELETE，字段标题、表名称取实体配置，用户为登录名 admin，时间为命令的开始、完成时间。
- 状态与证据：完成（真实验证通过；视图已在 d_cg（G3 起本分支后端时启动迁移建的；合并后 `platform db upgrade` 报已是最新）；独立复核通过，`.reports/review/T-WP-13.md`）。2026-10-31 第 8 批 G3，分支 `batch8/audit-export`，报告 `.reports/batch8-20261031/g3-audit-export/报告.md`。
  - 真实验证：`tests/pipeline/test_oracle_audit_log_view.py`（测试自己插一条命令记录，审计差异按 `command_log.audit_rows` 生成，直接执行迁移中的查询，结束时删掉这条记录）1 passed，`.reports/batch8-20261031/g3-audit-export/pytest-wp22-oracle.txt`；本组相关真实测试合计 30 passed（`pytest-real-g3.txt`）。
  - G3 分支后端启动时的迁移已建视图、登记 wp_0003（14:38）；合并后 `platform db upgrade` 报已是最新（`.reports/batch8-20261031/merge/db-upgrade.log`）。

### T-WP-14 命令审查里查询语句的行数

- 归属与目标：实现 WP-23（盘点 `.reports/inventory-20261030/甲-任务卡核对.md` 第四节 B16）：命令审查中 SELECT 语句也有行数，不多发 SQL。用户 2026-10-31 回复"开始"。
- 前置输入：T-WP-4（`SqlTracer`）、T-WP-5（命令审查）。
- 负责范围：`pipeline/tracing.py`（`_Counted`：包住执行上下文的 `cursor_fetch_strategy`，委托给原来的方式，`fetchone`、`fetchmany`、`fetchall` 时累加；要分批取的语句先换成分批的方式再包上，`yield_per` 换掉方式后再包一层）。
- 交付物：命令审查（C09 第 7a 节 `CommandLog.sql[].rows`）中查询语句的行数。
- 验收标准：模拟验证：一次取完、按批取（`yield_per`，导出用）都记取出的行数，没有结果的查询为 0，SQL 条数不变；真实验证（d_cg）：物料清单页保存（seed 的 GOODS_PRICE_MANAGE，测试自建本地物料）中加锁前的普通读取、加锁读取各为 1 行，改物料影响 1 行，SQL 条数仍是 7 条。
- 状态与证据：完成（模拟验证和真实验证通过；独立复核通过，`.reports/review/T-WP-14.md`）。2026-10-31 第 8 批 G3，分支 `batch8/audit-export`。模拟：`tests/pipeline/test_tracing.py` 的 `test_query_rows_are_rows_fetched`、原用例的查询行数改为 1。真实：`tests/pipeline/test_oracle_goods_save_sql_count.py` 加行数断言，连同 `test_oracle_sql_count.py`、`test_oracle_lock_order.py` 16 passed（`.reports/batch8-20261031/g3-audit-export/pytest-wp23-oracle.txt`）。前端命令审查面板照旧显示 `rows`，没有改。

### T-WP-15 只对关联了别的表的读取视图先锁表、再读视图

- 归属与目标：第 8 批合并时（2026-10-31）修正 G1 的 WP-03 例外。G1 让有 `readView` 的实体只锁一行时也先锁表、再普通读视图，物料清单页保存由 7 条变为 8 条，不满足 WP-10。物料清单的读取视图 T_COST_GOODS_PRICE_V 只读 T_COST_GOODS（d_cg 的 USER_DEPENDENCIES，`.reports/batch8-20261031/merge/q02-物料清单视图定义.out.txt`），对它 FOR UPDATE 不会锁到别的行，所以只对关联了别的表、视图或数据库链接的读取视图（产品信息维护的 T_COST_GOODS_V、外币管理的 T_COST_FORMONEY_V）先锁表、再读视图。纯技术实现，SQL 条数回到用户定的目标，不用再问用户。
- 前置输入：T-CF-9（G1 的例外）、T-WP-6（预读）；db-core 的 `SchemaInspector.view_sources`（DB-08）、config 的 `EntityDirectory.read_views`（C08 v22）。
- 负责范围：`pipeline/locks.py` 的 `ReadViews`、`pipeline/document_store.py` 的 `lock_load`、`pipeline/warmup.py`（预读已发布实体的读取视图）、`pipeline/plugin.py`；`db_core/schema.py` 的 `view_sources`；`config/entities.py` 的 `read_views`；`contracts/ports.py`、`contracts/fakes/db.py`、`contracts/fakes/config.py`。
- 交付物：上述功能。
- 验收标准：模拟验证：读取视图只读本表时只锁一行一条加锁读出，关联了别的表、经数据库链接或不知道读哪些表时先锁表、再读视图（`tests/pipeline/test_document_store_sql.py`）；插件 start 时预读已发布实体的读取视图（`tests/pipeline/test_warmup.py`）；`view_sources` 的契约测试（替代实现和 d_cg 共用）。真实验证（d_cg）：三个读取视图读取的表（`tests/db_core/test_ports.py::test_view_sources_on_d_cg`）；物料清单页保存 7 条（`tests/pipeline/test_oracle_goods_save_sql_count.py`）；外币管理"同步ERP汇率"仍只锁 T_COST_FORMONEY（`tests/operations/test_basic_pages_oracle.py`）。
- 状态与证据：进行中（模拟验证和真实验证通过；独立复核通过，`.reports/review/T-WP-15.md`；产品信息维护保存实测 6 条 SQL（`tests/pipeline/test_oracle_goods_manage_save_sql_count.py`，`.reports/batch9-20261031/pytest-goods-manage-sql.txt`），比 WP-10 的基准多 1 条，待用户确认）。后端模拟 1338 passed；真实 `tests/db_core/test_ports.py`、`tests/pipeline`、`tests/operations/test_basic_pages_oracle.py`、`test_sql_actions_oracle.py`、`tests/approval/test_oracle_or_sign.py` 67 passed；`lint-imports` 5 kept。两个真实测试的组装（`test_oracle_updated_by.py`、`approval/test_oracle_or_sign.py`）和 `lock_order_support.py` 改成与插件相同，带上 `ReadViews`。

### T-WP-16 复制出的行不取"不复制"的列的源行值

- 归属与目标：实现 WP-24（C05 v11 字段的 `copy`）。依据用户 2026-10-31："复制主表要把明细表一起复制过来，这个是通用方法，但是也可以配置哪些列可以不复制，这个在元数据中配置即可"，前后台一致。旧系统没有这项配置。
- 前置输入：T-WP-10（WP-21）、T-CF-15。
- 负责范围：`pipeline/merge.py`（`DocumentMerger._copy_fields`、`_Rows.new_values`、`_Rows._copied_values`）。
- 交付物：复制出的行中，页面视图 `copy` 为 false 的不可写字段不取源行的值、不写；可写的照常取命令中的值；都不补默认值。
- 验收标准：模拟验证：成本核算页把创建人（不可写）、批量（可写）配成不复制，复制 1001 时命令带了源行的创建人"王五"（页面在改配置之前打开）、批量为 null：新单据创建人、批量为空，INSERT 不含创建人，产品名称照旧取源行的值、备注取命令中的值。
- 状态与证据：完成（模拟验证通过；独立复核通过，`.reports/review/T-WP-16.md`）。合并后（2026-10-31）主代理在 main 上运行：后端真实测试 217 passed（`.reports/batch9-20261031/pytest-real-1.txt`），浏览器用例全部运行（`.reports/batch9-20261031/e2e-1.txt` 61 passed；失败的 E45 修正后单独通过，`e2e-3.txt`）。2026-10-31 第 9 批 B 组，分支 `batch9/copy-config`。模拟验证：`tests/pipeline/test_copy.py::test_not_copied_fields_are_left_empty`；`pytest -m "not oracle and not redis"` 1340 passed（`.reports/batch9-20261031/b-copy-config/pytest-1.txt`）。真实验证（d_cg + Redis，不写配置）：复制相关的 `tests/e2e/test_copy_approval.py`、`tests/pipeline/test_oracle_updated_by.py` 2 passed（`real-1.txt`），说明没有配 `copy` 时复制照旧；配了 `copy: false` 的真实保存在 T-FP-19 用例 2（合并后运行）。
### T-WP-17 按单据提交；主从单据连明细一起锁
- 归属与目标：实现 C02 v10 第 1 节的按单据提交（orchestration 的 `CommandExecutor`，C08 v23 第 5 节）和 WP-02、WP-03 中主从单据连明细一起锁；随之 approval 的 AP-06 只拒绝冲突的那一张单据。依据用户 2026-10-31："我也是要求一单一单的提交啊，没问题啊，比如我一共操作了100个不同的单据 我也是按照单据级别成功或者失败 不可能说100个单据 失败了1个，就全部失败"；"一张单据的操作顺带要改、要锁的其他单据 那么都应该在一个事务里"；"如果是单表保存，那么锁住产生变化的这一行，如果是主从保存，那么主从都要锁"。旧系统一张单据一个请求、一个事务（`useWorkingSetStore.ts` 第 960–1080 行，`DynamicDataService.save`），锁主表行和明细（`ApprovalFreezeService.guardSave`、`guardDerivedWrites`），核对见 `.reports/doc-commit-20261031/findings.md`。答卷 `.reports/button-design-20261031/按钮与保存的配置方案-答卷.md` 第九节第 1–6 项。
- 前置输入：T-WP-1、T-WP-7。
- 负责范围：`contracts/types.py`（`DocumentFailure`、`CommandResult.failed`）、`contracts/ports.py`（`CommandExecutor` 的说明）；`orchestration/split.py`（拆单据、子请求键、合并结果）、`orchestration/runner.py`；`pipeline/locks.py`（`lock_children_sql`、规则 5）、`pipeline/document_store.py`（`lock_details`、`lock_document`）、`pipeline/loader.py`（`DocumentLoader.lock`）。
- 交付物：页面保存带 2 张及以上单据、按钮选中 2 行及以上主表行时每张单据一个事务，没成功的记入 `failed`；同一请求重发时已提交的单据返回原结果、失败的重新执行；只涉及一张单据的命令照旧。主从单据锁住主表行后每张明细表一条锁明细。不选行的按钮（外币管理"同步ERP汇率"）还不拆，要先找出单据，留到流程的"找单据"。
- 验收标准：模拟验证：`tests/orchestration/test_split.py`（成本单 2550、2551 一起保存，一张冻结时另一张提交；重发不重复执行已提交的；新增单据按 clientRowId；意外错误记为 INTERNAL_ERROR；主表选中两行的按钮按单据拆、明细选中行不拆；只有一张单据时照旧抛错）；`tests/pipeline/test_locks.py`、`test_document_store_sql.py`（锁明细一张明细表一条，推迟加锁时不锁、锁住核对时锁）。真实验证（d_cg + Redis）：`tests/e2e/test_doc_commit.py`（200680 与 2550 一起保存，2550 被规则拒绝或在审批中时 200680 照常保存、2550 不变；重发不重复写）；WP-10 条数：`tests/pipeline/test_oracle_sql_count.py`（主从页 5、3、7 条）、`tests/e2e/test_batch_b.py::test_one_cell_saves_and_sql_counts`、`tests/e2e/test_batch_c.py` 冻结期间的保存。
- 状态与证据：进行中（模拟验证、真实验证通过；独立复核 `.reports/review/T-WP-17-T-FP-20.md` 结论"需要修改"，唯一的必改项是新建单据没成功的场景没有用例，已补 `test_new_document_failure_carries_client_row_id`（新建的成本单被拒、2550 保存）和 `test_new_document_saved_gets_its_key_in_id_map`；建议中按钮拆分时的内部错误文字改为"处理这张单据时出现内部错误"，其余建议（服务端记原请求键、投递次数和按钮的真实联调用例）没有做）。2026-10-31，分支 `batch10/doc-commit`（worktree `.worktrees/approval`），进度 `.reports/doc-commit-20261031/progress.md`。合并进 main（739742c）后在 main 上运行：后端模拟 1368 passed（`main-pytest-mock.txt`），`lint-imports` 5 kept；真实 220 项 219 passed、1 failed（`main-pytest-real.txt`）：`tests/e2e/test_sample_two.py` 7.10 的受影响行先后与预期相反。原因是审批的受影响行按关联条件查询返回的先后排列（`SELECT * … WHERE` 没有排序），这个用例一次保存两张新成本单，按单据提交后两张各一个事务，行落在不同的数据块，Oracle 返回的先后就变了；单独重跑两次一次通过、一次失败。旧系统受影响行按主键 `ORDER BY`（`ApprovalObjectService.java` 第 419、666 行），approval 的 `trigger._affected` 改为按主键排列（AP-02），`tests/approval/test_submit.py::test_e39_cost_documents_listed_and_checked` 的预期改为按主键；审批相关真实测试 21 passed（`main-approval-real.txt`，含 test_sample_two、test_copy_approval、test_batch_c），之后单独再跑 test_sample_two 通过（`main-sample-two-5.txt`）。后端模拟 `pytest -m "not oracle and not redis"` 1366 passed（`.reports/doc-commit-20261031/pytest-mock-2.txt`）；真实 `-m "oracle or redis"` 220 项：第一次 218 passed、2 failed（`pytest-real-1.txt`，都是批次 B、C 的 SQL 条数，主从单据多了 1 条锁明细，改断言后单独重跑 2 passed）；`lint-imports` 5 kept。WP-10 的条数因用户要求主从都锁各多 1 条，见模块说明 WP-10。
