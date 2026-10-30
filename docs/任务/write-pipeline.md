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
- 验收标准：模拟验证：改一格只写该列和计算带出的列；提交相同的值不写业务表；计算字段、主键出现在 Patch 中被拒绝；物料表 ISERP 为 1 的行改 PRICE 被拒，ISERP 为 0 的行可以改；新增行的 ISERP 写为 0；计算值 `1.234567885` 保存为 `1.23456789`，`-1.234567885` 保存为 `-1.23456789`，命令结果与数据库中的值相同；行已被删除时默认跳过，配置为拒绝时返回 ROW_NOT_FOUND；删除主表行时先删明细；必填检查新增、修改的行和计算带出变化的行（T-WP-7）；动作执行中 `updateRecords` 找到第 3 步范围外的成本单 E 时，E 先加锁读取、再做冻结检查：E 被别的审批冻结时整个命令返回 FROZEN_BY_APPROVAL、什么都不写，被本审批冻结时放行（WP-18）；基于属性的测试：任意 Patch 的变更计划只含值有变化的列；真实验证：以上在 d_cg 上通过，等锁 5 秒后返回 DOCUMENT_BUSY；两个命令在第 7 步交叉加锁形成死锁时，其中一个返回 DOCUMENT_BUSY 并整体回滚。
- 状态与证据：进行中（2026-10-29），模拟验证通过，真实验证的测试已写好、还没有运行。链路 0、链路 1 的最小部分见 T-AS-9（[assembly](assembly.md)），现有 `SaveFlow` 用法保持兼容（`tests/pipeline/test_compat_saveflow.py`）。
  - 已实现：WP-03（按实体、主键排序，一个实体一条 `FOR UPDATE WAIT n`，行权限判断列在同一条 SQL 中）、WP-04、WP-05、WP-06（每张明细表按关联字段一条 DELETE，再删主表）、WP-07、WP-08（commit 阶段求值，计算带出的变化并入变更计划）、WP-09（按写入的列分组批量执行，新增用序列和 RETURNING）、WP-14、WP-15（列的小数位取 SchemaInspector）、WP-18（范围外单据加锁、只对它们做冻结检查后合并）。明细读取多个明细实体合成一条 UNION ALL 语句。
  - 模拟验证：同一条命令 98 passed，其中 `test_merge.py`（改一格只写该列、相同值不写、计算字段/主键/关联字段被拒、ISERP 为 1 改 PRICE 被拒而为 0 可以、新增行 ISERP 为 0、1.234567885→1.23456789、行已删除跳过或 ROW_NOT_FOUND、删除主表连明细、基于属性的测试：变更计划只含值有变化的列）、`test_values.py`、`test_flow.py`（E04、E05、规则拒绝、必填检查的行、WP-18 范围外单据被别的审批冻结时整个命令 FROZEN_BY_APPROVAL 且什么都不写）、`test_document_store_sql.py`（语句文本）。
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

### T-WP-6 启动时预读列定义

- 归属与目标：WP-15 的列定义在平台启动时和配置变更后预读，第一次保存的 SQL 条数与 WP-10 相同。来源：2026-10-30 联调核对 WP-10 时发现，后端进程启动后第一次写某张表的命令多 1 条 `user_tab_columns` 查询（SchemaInspector 取列的小数位），同一进程之后不再读（`.reports/batch2-20261030/g5-acceptance/findings.md`）。
- 前置输入：T-WP-2；config 的 `EntityDirectory`（C08 第 4 节加 `tables`）。
- 负责范围：`pipeline/values.py` 的 `ColumnScales.preload`、`pipeline/warmup.py` 的 `SchemaWarmup`、`pipeline/plugin.py` 的 start、stop；`config/entities.py` 的 `tables`；contracts 的端口、替代实现和契约测试。缓存在本模块（db-core 的 `SchemaInspector` 不缓存，config 的校验、新建页面向导要读到最新的表结构），所以预读在本模块做。
- 交付物：插件 start 时预读已发布实体写入的表，读完才返回；后台每 5 秒检查一次，新的表读进来；stop 停掉后台检查。WP-10 中"审批入口条件每行一条"不在本卡（等用户决定）。
- 验收标准：后端启动后第一次保存不再有 `user_tab_columns` 查询；配置变更新增实体后，后台读进新的表。
- 状态与证据：进行中（2026-10-30，H2 组，`batch3/approval-snapshot`）。模拟验证：`tests/pipeline/test_warmup.py` 2 个（start 读完已发布实体的表才返回，之后新增实体的表由后台读进来，保存时取小数位不再读；插件 start、stop），`test_values.py` 的预读不重复读，`EntityDirectoryContract.test_tables`（替代实现、`PublishedEntities`），`tests/pipeline tests/config tests/contracts tests/assembly` 705 passed。真实验证：`tests/config/test_oracle.py` 的 `TestOraclePublishedEntities` 4 passed（d_cg 已有这四个实体，没有保存配置）；后端 8088 启动日志"已预读列定义：T_COST_GOODS、T_COST_PINGGU、T_COST_PINGGU_DTL"在"开始接受请求"之前；打开命令审查后，后端启动后的第一次保存（成本单 2550 改单价、提交审批）21 条 SQL，没有 `user_tab_columns`（`.reports/batch3-20261030/h2-approval/h2.out.json`）。同一次核对中第一次审批通过有 2 条 `user_tab_columns`（T_COST_GOODS），来自 approval 计算受影响单据时每次读修改表的列（`approval/view.py` 的 `_affected_table`），不是本卡的 ColumnScales，没有改。`tests/e2e/test_batch_b.py` 中允许多 1 条列定义查询的断言（`sum(map(is_schema_query, sql)) <= 1`）没有改、没有运行（别组在用 8086、8087）。

### T-WP-7 计算带出变化的行也检查必填

- 归属与目标：WP-07 改为按旧系统：页面保存时，必填检查的行 = 本次新增、修改的行 ∪ 计算后有计算字段变化的行，删除的行不查。来源：旧系统 `useWorkingSetStore.ts` 第 886–934 行（保存时对有修改的行检查，含 `useCalcBroadcast.ts` 记成 `calc` 的计算带出变化）、`validator.ts` 第 52–85、116 行（列的 required）；上一组的核对见 `.reports/batch3-20261030/h1-rules-dirty/findings.md`；用户 2026-10-30 同意按旧系统做。rules-core 的校验规则已经这样做（C07 v7）。
- 前置输入：T-WP-2。
- 负责范围：`pipeline/stages.py` 的 `calc_changed_rows`、`required_rows`，`pipeline/calc.py` 的 `check_required`。
- 交付物：计算带出变化的行由变更计划推出：修改的行中含计算字段的（Patch 和动作都不能写计算字段，计划中的计算字段只来自计算）。按钮操作、审批处理不带 Patch，不检查必填（旧系统按钮由后端执行，不经前端保存的校验），与原来相同。
- 验收标准（业务例子）：d_cg 单据 2555（4mg马来酸氯苯那敏片）原料"马来酸氯苯那敏"（102126）每片含量 4、单价为空，页面配了原辅料单价必填；只改批量 3500000 → 4000000，它的每批数量 14 → 16，保存返回 422 VALIDATION_FAILED，只指出这一行的"单价 不能为空"，不写库。单据 2757 改批量能保存：每批数量变了的原辅料单价、每片含量都有，单价为空的 207577（每片含量 0）每批数量仍是 0，不检查。
- 状态与证据：模拟验证通过（2026-10-30，P 组，`batch4/pipeline-fixes`）。`tests/pipeline/test_validate_changed_rows.py` 的 `test_2555_change_batch_price_required_rejected`（数据 `tests/pipeline/data/doc-2555.json`，取自 d_cg 只读查询 `.reports/batch4-20261030/p-pipeline-fixes/q02-单据2555.sql`，真实 rules-core 和 seed 规则）、`test_2757_change_batch_saves`、`test_2757_change_batch_checks_changed_rows_required`；`test_flow.py` 的 `test_required_checked_on_rows_changed_by_calculation`（原 `test_required_not_checked_on_rows_changed_only_by_calculation` 按新规则改写）。

### T-WP-8 写入修改人

- 归属与目标：实现 WP-20：实体配置 `updatedByColumn`（C06 v19 第 2 节）后，新增、修改这个实体的行时写当前用户的登录名，审批通过时写审批人。来源：旧系统 `DynamicDataService.java` 第 290–293、392–393 行（UPDATE_BY = `SecurityUtils.getCurrentUsername()`，取 JWT 的 username，即登录名，`JwtAuthenticationFilter.java` 第 38–49 行）；审批通过在审批人的请求中执行（`ConfiguredApprovalRuntime.java` 的 `applyPending`）；用户 2026-10-30 同意按旧系统做。
- 前置输入：T-WP-2；contracts 的 `EntityConfig.updated_by_column`；config 的保存校验（列在表中、不是实体字段的列）。
- 负责范围：`pipeline/writer.py` 的 `_stamped`、`_write_stamped`（写入时在实体和变更计划的副本上加修改人字段，不改 `document_store.py`）；seed 的 `entity.COST_GOODS_PRICE.json` 配 `"updatedByColumn": "UPDATE_BY"`。成本核算的表在 d_cg 没有 UPDATE_BY 列（DB-03），不配。
- 验收标准：模拟验证：改本地物料、新增物料时同一条语句写修改人，命令结果中没有它，没配的实体不写，来源为审批时写审批人的登录名。真实验证（业务例子）：测试自己建一个 ERP 物料（ISERP = 1、UPDATE_BY = `ERP_SYNC`），admin 在物料清单页改它的单价，提交审批 GOODS_TO_COST，admin 通过后 T_COST_GOODS 的 UPDATE_BY 为 admin、单价写入，视图 T_COST_GOODS_PRICE_V 的 ROW_CLASS_FLAG 为 `erp-updated`（黄底）；测试结束删掉这个物料、审批和命令记录。
- 状态与证据：见 `.reports/batch4-20261030/p-pipeline-fixes/`（2026-10-30，P 组，`batch4/pipeline-fixes`）。模拟验证 `tests/pipeline/test_updated_by.py`；真实验证 `tests/pipeline/test_oracle_updated_by.py`（标 oracle，测试的内存配置取 seed）。d_cg 的配置在合并后由主代理经配置接口写入。
