# operations 任务

模块说明：[operations](../模块/operations.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E10、E11（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-OP-1 通用动作与按钮操作

- 归属与目标：实现 OP-01–OP-03、OP-05、OP-07、OP-08，按钮操作的"确定涉及的单据"和"动作执行"中的展开。审批流通过后的操作由 approval 展开（2026-10-28 随 C06 v17 移出本卡）。
- 前置输入：开始前 T-CT-1、T-CT-3、T-CT-5；C06 第 4、6 节经用户确认。
- 负责范围：`backend/src/cost_platform/operations/`。
- 交付物：按钮的 `recalculate`、`updateTargets`、`updateRecords` 的展开；字段映射；传播边界。
- 接入责任：T-AS-5 注册按钮操作的阶段。
- 验收标准（模拟验证）：每种动作的展开结果正确；字段映射取来源计算后的值；同一目标行被写入不同的值时返回 VALIDATION_FAILED，同一目标被几行找到而各自写不同的明细行（`match`）时不冲突；映射到计算字段，或映射到 ERP 行的 ERP 列被拒绝；传播边界为 `end` 时目标不触发审批；按钮需要选中行而没有时返回 VALIDATION_FAILED；按钮命令带了 `documents` 时返回 INVALID_REQUEST；选中成本单 D 点按钮时，`updateRecords` 按 D 在数据库中的当前数据查找和写入；选中的行在点按钮前已被删除时，`rowNotFound` 为 `skip` 写入 `skipped`，为 `reject` 返回 ROW_NOT_FOUND；按钮的 `updateRecords` 的关联 SQL 绑定明细字段时，传入选中单据的全部行，并按行分别调用 `RelatedQuery`：按钮"同步单价"选中的成本单 D 中 115 单价 80、116 单价 12，由 116 那一行找到的其他成本单明细写 12，由 115 找到的写 80；`updateRecords` 的关联 SQL 查出的行中有一行主键为空时，跳过这一行，其余行照常更新；按钮操作的 `updateRecords` 找到的成本单被审批冻结时，整个命令返回 FROZEN_BY_APPROVAL（WP-18）；按钮操作的"确定涉及的单据"和"动作执行"中的展开通过 `PipelineStage` 的契约测试（C08 第 14 节）。
- 状态与证据：进行中（2026-10-29，联调通过，还没有独立复核）。代码：`backend/src/cost_platform/operations/`（`stages.py` 的 `ButtonInvolvedStage`、`ActionStage`，`actions.py` 三种动作的展开，`mapping.py` 字段映射、可写检查和冲突，`selection.py` 选中行）。模拟验证：`uv run pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/operations` 36 个通过、0 个失败（与 T-OP-2 合计，`.reports/modules/operations/pytest.txt`）；`uv run lint-imports --no-cache` 3 条规则保持（`lint-imports.txt`）。逐条：展开结果、来源计算后的值、冲突与 `match` 不冲突、计算字段和 ERP 行的 ERP 列被拒、选中行为空、带 `documents`、按 D 的当前数据逐行调用 `RelatedQuery`、"同步单价"80/12、主键为空的行跳过、选中行已删除的 skip 和 reject 见 `tests/operations/test_actions.py`、`test_involved.py`；两个阶段通过管道阶段契约测试（`test_contracts.py`）。传播边界 `end`（2026-10-29 核对）：触发审批只对页面保存执行，按钮命令的 `documents` 为空，按钮写到的目标不会触发审批；旧系统按钮写必须审批的字段时拒绝（`ActionWriteGuard` → `guardDirectMutation`），新系统由强制审批检查拒绝；旧系统没有 `continue` 的级联。原来的 `ActionStage.propagation_ended` 没有使用方，已删除。"找到的成本单被冻结返回 FROZEN_BY_APPROVAL"由 write-pipeline 对不在 `involved` 中的单据加锁、做冻结检查（WP-18），本模块的测试只核对 intents 指向这些单据，返回码在 T-AS-5 联调时验证。`updateTargets`、`recalculate: targets` 的目标按"本命令前面 `updateRecords` 找到的对象"实现，契约没有写明（缺口第 1 项）。上线后再补：配置写错（`fieldMapping` 引用了取不到的实体、`impact` 没有列出明细所属的主表实体、`selectedRows` 格式不对）的用例。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"待联调"改为"完成"：按钮操作在浏览器中经真实后端执行（`frontend/tests/e2e/g0-1030.spec.ts:376`"场景 5a"由BOM生成明细，第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）；FROZEN_BY_APPROVAL 经写入管道在 `tests/e2e/test_batch_c.py` 中验证（第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`）。配置写错的用例：上线后再补（`docs/工程约定.md` 第 5 节：用户没有点名的异常、边界、并发不做）。"还没有独立复核"保持原样，按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-OP-2 逃生舱机制

- 归属与目标：实现 OP-04。
- 前置输入：开始前 T-OP-1；用户同意在 d_cg 中建一个测试用存储过程（名称以 `PF_TEST_` 开头）。
- 负责范围：operations 中逃生舱的执行和调用审计。
- 交付物：逃生舱执行；只在测试配置中启用的测试存储过程。首版配置中不启用任何逃生舱。
- 接入责任：T-AS-6 联调。
- 验收标准（真实验证）：逃生舱在命令事务内执行，之后的动作失败时它的写入一起回滚；调用审计随命令记录写入。
- 状态与证据：进行中（2026-10-29；真实验证通过，首版配置不启用逃生舱；待独立复核）。代码：`backend/src/cost_platform/operations/escape_hatch.py`。登记表 `EscapeHatchRegistry` 默认为空，只登记用户点名启用的逃生舱，没登记的拒绝执行（422）；登记的调用有三种，对应旧系统的三种执行器：存储过程（proc，IN/OUT/INOUT，可核对 USER_SOURCE 源码指纹）、语句（sql，绑定变量）、处理函数（java）。在动作执行阶段排到这个动作时、在命令事务的连接上执行，自身不提交不回滚；每次调用生成 `EscapeHatchCall`（逃生舱、参数、执行人、时间和请求键）。模拟验证（内存 SQLite，存储过程用测试替身代替）：`tests/operations/test_escape_hatch.py` 6 个通过，包括之后的动作失败时写入一起回滚、没登记的被拒绝、语句和处理函数各一例（命令与 T-OP-1 合计 36 个通过，`.reports/modules/operations/pytest.txt`）。真实验证：`tests/operations/test_escape_hatch_oracle.py` 4 个（提交、之后的动作失败回滚、源码指纹、语句）2026-10-29 在 d_cg 上通过；用户 2026-10-29 同意这组测试每次在 d_cg 建测试用存储过程 `PF_TEST_ESCAPE_HATCH` 和表 `PF_TEST_ESCAPE_LOG`（fixture 建、结束时删），跑完后 `USER_OBJECTS` 中没有残留。生成的 PL/SQL 匿名块见 `.reports/modules/operations/probe_plsql.txt`（不连数据库）。调用审计随命令记录写入（2026-10-29）：调用记录写进 `CommandState.escape_hatch_calls`，由 `CommandRecorder.complete` 用完成命令记录的同一条 UPDATE 写入 PF_COMMAND 的 ESCAPE_HATCH_CALLS 列（迁移 wp_0002，d_cg 已升级）；只调用逃生舱的命令结果为 saved，照常提交。参数怎样绑定契约没有写，按服务端登记实现（`contract-gaps.md` 第 3 项）。首版配置中不启用任何逃生舱。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：验收标准的两项（在命令事务内执行、之后的动作失败时一起回滚；调用审计随命令记录写入 PF_COMMAND.ESCAPE_HATCH_CALLS，迁移 wp_0002）由 `tests/operations/test_escape_hatch_oracle.py` 4 个（第 35 行标 oracle）在 d_cg 上验证，第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`。接入责任中的 T-AS-6 联调：首版配置不启用任何逃生舱，没有页面用到，不另联调。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-OP-3 按 SQL 的动作：由BOM生成明细

- 归属与目标：实现 OP-09、OP-10（C06 v18 第 6 节的 `replaceDetails`、`updateRows`）。来源：用户 2026-10-29"那两个存储过程是有问题的，它内部又计算了一次，这是不应该的，后续都可以不用存储过程计算了"，以及旧系统成本核算主表的两个按钮（P_COST_BOM_INSERT、P_PINGGU_COMPUTE_ALL）。
- 前置输入：T-OP-1；write-pipeline 的 WP-08（按 Lookup 带出名称）、WP-16、WP-18。
- 负责范围：`backend/src/cost_platform/operations/sql_actions.py`；config 的保存校验（`validation.py` 的 `_replace_details`、`_update_rows`）；seed 的两条操作和成本核算主表的两个按钮；frontend-config 的操作编辑、frontend-page 按钮结果中新增明细行的显示。
- 交付物：两个动作的展开；`operation.COST_PINGGU.generateFromBom.json`；`page.COST_PINGGU.json` 主表按钮"由BOM生成明细"（`requiresSelection` 为 true）。
- 接入责任：主代理合并后把这两项配置写进 d_cg，在浏览器中点这个按钮。
- 验收标准：模拟验证：选中成本单 D 点"由BOM生成明细"，删掉 D 的原辅料，按 SQL 查出的行逐行新增，值取同名列；不选行的 `updateRows` 按钮，SQL 执行一次，涉及的单据由结果决定。真实验证（d_cg）：新建一张产品 392 的成本单点"由BOM生成明细"，明细行数与 BOM 相同，物料、每片含量、单价、分类与旧 P_COST_BOM_INSERT 的查询相同，每批数量、每批成本和主表合计等于计算规则的结果；测试里自己定义的 `updateRows` 操作（只查这张单据）把单价改成 T_COST_GOODS.PRICE 并重算；"由BOM生成明细"和这个测试操作在 d_cg 上通过 C06 第 10 节的校验。
- 状态与证据：进行中（2026-10-30，模拟验证和真实验证通过，浏览器中已验证；待独立复核）。代码：`operations/sql_actions.py`（`expand_replace_details`、`expand_update_rows`），`stages.py` 的 `ActionStage` 分派，`actions.py` 的 `planned_intents` 两处共用；config `validation.py`、`catalog.py`；前端 `config/views/OperationDialog.vue`、`operation-form.ts`，`page/page-runtime.ts` 的 `runOperation`。模拟验证：`tests/operations/test_sql_actions.py` 2 个；`tests/config/test_validation.py` 的 seed 整体校验和"SQL 多选了计算字段 BATCH_QTY 被拒"；前端 `tests/page/buttons-config.test.ts`（"同步采购价"不选行可点、selectedRows 为空；"由BOM生成明细"后明细区去掉删除的行、显示新增的行）、`tests/config/operation-actions.test.ts`。真实验证：`tests/operations/test_sql_actions_oracle.py` 3 个（`pytest -m oracle`，输出 `.reports/batch1-20261029/bom-price/pytest-oracle.txt`）：组装真实的 db-core、rules-core、authz、queries、write-pipeline、operations、approval 插件，配置快照由 seed 在内存中生成（不写 PF_CONFIG_ITEM）；复制成本单 200721（产品 392）为新单据，"由BOM生成明细"删掉原 12 行、新增 11 行（原辅料 5、包材 6），与旧查询一致，主表 TOTAL_YL、TOTAL_FL、TOTAL_BC、TOTAL_COST 与规则算出的相同；"同步采购价"把硬脂酸镁 63 → 75、对乙酰氨基酚 33 → 32 等改成参考价并重算，200721 不变；测试数据结束时删除（`.reports/batch1-20261029/bom-price/06-测试数据残留核对.sql`）。没有在 d_cg 上执行 seed 中覆盖全部成本单的"同步采购价"。
  - 2026-10-30：用户不要"同步采购价"这个按钮，已删除配置：seed 删掉 `operation.COST_PINGGU.syncPrice.json` 和成本核算主表的按钮；d_cg 经配置接口先保存去掉按钮的页面 COST_PINGGU（30 → 31），再删除操作 COST_PINGGU.syncPrice，删前、删后只读核对 PF_CONFIG_ITEM（删前只有页面、它的页面视图和这个操作引用它，没有角色、审批流引用；删后没有任何配置项含 syncPrice，`.reports/batch4-20261030/main/01-*`、`02-*`）。`updateRows` 能力保留（OP-10）：`test_sql_actions_oracle.py` 改为在测试的内存配置里自己定义一个只给测试用的操作和按钮（SQL 同原来，加 `D.DOCID = <测试单据>`），继续经真实写入管道验证；`tests/operations/test_sql_actions_oracle.py`、`tests/config` 的真实测试 38 passed，非真实库 167 passed。旧存储过程 P_PINGGU_COMPUTE_ALL 新平台没有用，d_cg 里也没有（只读核对 USER_OBJECTS），cmx 的不动。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"待联调"改为"完成"：浏览器 `frontend/tests/e2e/g0-1030.spec.ts:376`"场景 5a"（新建成本单点"由BOM生成明细"，生成 11 行、主表合计更新）、`:507`"场景 6"（工具栏没有"同步采购价"，不选行时"由BOM生成明细"不可用）通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。"同步采购价"和旧存储过程用户已答复去掉（本条第一个子条目）。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-OP-4 按钮找到别的单据时的加锁顺序

- 归属与目标：按用户 2026-10-30 同意的"固定加锁层级"改 OP-07（OP-10 同样，write-pipeline WP-03）：`updateRecords`、`updateRows` 找到的单据排在选中单据之前或同层时，查找挪到加锁之前普通执行一次，选中的和找到的单据一次锁完，锁住后以这一批为准；排在之后时由加锁读取往后追加。
- 前置输入：T-OP-1、T-OP-3；write-pipeline 的 `BusinessLocker`（T-WP-7）。
- 负责范围：`operations/stages.py` 的 `ButtonInvolvedStage`（预查）和 `ActionStage`，`actions.py` 的 `finds_other_documents`、`find_targets`（只认锁住的）、`search_targets`，`sql_actions.py` 的 `expand_update_rows`（只写锁住的）、`update_rows_documents`，`plugin.py`。`replaceDetails` 只写选中的单据，不用预查。
- 交付物：上述功能。
- 接入责任：assembly 不用改插件清单（operations 插件多要一个端口）。
- 验收标准：选中成本单 D 点"同步单价"（测试里的按钮），找到的同层成本单 A、B、E 和 D 在动作之前一次锁完；查找和加锁之间新冒出来的 F 不写；D 在加锁前读取之后被改时整个回滚。
- 状态与证据：进行中（2026-10-30，L 组，`batch4/lock-order`），模拟验证通过，待独立复核。`tests/operations/test_lock_order.py` 3 个，`tests/operations` 其余用例照常通过。真实验证：d_cg 的种子配置里已经没有找别的单据的按钮（"同步采购价"已删），按钮找到同层单据的并发没有在 d_cg 上重放；`tests/operations` 的 oracle 用例照常通过。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：验收标准用测试里的按钮"同步单价"，由 `tests/operations/test_lock_order.py` 3 个覆盖（第 7 批合并后模拟全量 1309 passed，`.reports/batch7-20261030/merge/pytest-1.txt`）；按钮找到同层单据的并发没有在 d_cg 上重放：seed 已没有找别的单据的按钮（"同步采购价"已去掉），前台没有这条路径，按用户规则（`.kiro/steering/测试范围.md`）不另做。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。
