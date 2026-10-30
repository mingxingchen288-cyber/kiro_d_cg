# approval 任务

模块说明：[approval](../模块/approval.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E10–E17、E20–E27、E31–E41（[业务例子](../业务例子.md)）。2026-10-28 随 C06 v17 重写验收标准：按用户"测试的目的是把正向流程跑通即可"（工程约定第 5 节），只验收业务例子和用户点名的场景，在 d_cg 上用成本单 2550、物料聚维酮K30 的真实数据跑通。

### T-AP-1 审批流转逻辑

- 归属与目标：实现 AP-04、AP-07、AP-09、AP-12、AP-16 中不访问数据库的判断逻辑，以及结果指纹。
- 前置输入：开始前 T-CT-1；C06 第 7 节经用户确认（v17，2026-10-28）。
- 负责范围：`backend/src/cost_platform/approval/` 的流转函数。
- 交付物：输入审批流定义、当前进度和一次处理，输出处理是否允许、新的进度和去向（留在本级、下一级、终点、结束）的函数；结果指纹的计算。
- 接入责任：T-AP-2、T-AP-3 使用。
- 验收标准：业务例子 E14、E15，以及 E37 中"管理员通过后进入第 2 级会签、采购和生产都通过才到终点；单价只改到 80 时管理员通过即结束"的流转。
- 状态与证据：进行中（模拟验证通过，待独立复核）。代码 `approval/routing.py`。先写 `tests/approval/test_routing.py`，实现前运行为收集失败（`ModuleNotFoundError: cost_platform.approval.routing`），实现后 14 个通过：E14 撤回（有人通过后 403、没人处理时成功）、E15 两个审批流合成一个审批（李四一次通过计入两个入口、F1 第 2 级终点、F2 第 3 级终点、同一人两级要分别通过、任一级驳回即结束）、E37 第 2 级会签和单价 80 一级结束、指纹。模拟验证：2026-10-29 `uv run pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/approval` 85 个通过、0 个失败（`.reports/modules/approval/pytest.txt`）。

### T-AP-2 触发审批与冻结

- 归属与目标：实现 AP-01–AP-03、AP-06、AP-13、AP-14、AP-17、AP-22，AP-21 中提交时的部分，"冻结检查""触发审批"两个阶段和 `FreezeReader`。
- 前置输入：开始前 T-AP-1。验收前 T-DB-1、T-DB-2。
- 负责范围：approval 的两个阶段和审批数据存储；审批实例、进度、处理记录、待审修改、触发行、受影响单据的行、冻结记录的表和迁移脚本；入口条件、冻结和展示的关联条件、取值的执行（C06 7.2）。
- 交付物：上述阶段和 `FreezeReader`；审批数据的读写。
- 接入责任：T-AS-6 注册阶段，并把 `FreezeReader` 接给 queries-export。
- 验收标准：在 d_cg 上跑通业务例子 E37 的提交部分（只有聚维酮K30 触发，2550 和物料清单 25 被冻结，13165、115 不冻结）、E38、E40、E41，以及 E20、E22、E35。
- 状态与证据：进行中（模拟验证通过；真实验证已写好、未运行）。代码 `approval/trigger.py`、`freeze.py`、`store.py`、`tables.py`、`sql.py`、`catalog.py`、`approvers.py`、`notify.py`、`patch.py`，迁移 `approval/migrations/ap_0001_pf_approval.py`（未执行）。模拟验证（contracts 的替代事务、`FakeSchemaInspector`、`FakeDirectory`，SQL 片段由 `tests/approval/support.py` 的 `WorldSql` 按同样的意思在内存数据上求值，命令执行由 `Pipeline` 替身代替 write-pipeline）：`test_freeze.py` 17 个（FreezeReader 契约 4 个、冻结检查阶段、E37 冻结 2550 和物料清单 25 而 13165、115 照常修改、E22 冻结单据不能新增删除明细、E35、E16 两种、E21、驳回后解冻），`test_submit.py` 14 个（E37 只有 K30 触发且三行都不写、E38、只改备注、E40 写成 80 和 82 时 422 及都改 80 时正常提交、E20、E22、E24 的预留主键、E41 三种、两个审批流合成一个审批、E39 列出的受影响行、E23 的通知标题）；冻结和"单据只属于一个审批"的测试写在实现代码之后、第一次运行之前，没有先看到失败。真实验证：`tests/approval/test_oracle.py` 12 个（标 `oracle`，没有运行），前提为合并后执行 ap_0001，以及 d_cg 补建 `T_COST_GOODS_PRICE_V`（`.reports/modules/approval/contract-gaps.md` 第 6 条）。上线后再补：两个命令同时冻结同一份数据的并发（唯一约束已在迁移中，只在 d_cg 上能验证）。

### T-AP-3 审批处理、详情与接口

- 归属与目标：实现 AP-05、AP-08（含 C06 7.6 的审批详情和 `preview`）、AP-10–AP-12、AP-21 中详情和批准时的部分，审批命令的"确定涉及的单据""审批处理"阶段，以及 C09 第 6 节的接口。
- 前置输入：开始前 T-AP-1、T-AP-2；计算已接入保存（rules-core 的 commit 求值），审批详情的"修改后"依赖它。
- 负责范围：approval 的处理阶段、详情计算和 HTTP 路由。
- 交付物：通过、驳回、撤回转成命令并经 `CommandExecutor` 执行；审批详情和预览；待办列表。
- 接入责任：T-AS-6 挂载路由并接入真实的 write-pipeline；frontend-approval 使用接口（T-AS-7）。
- 验收标准：在 d_cg 上跑通业务例子 E37（从保存到第 2 级会签通过）、E39（取消 2556 后详情重算，通过后其余明细写入）、E13（驳回后都不生效、冻结解除）。
- 状态与证据：进行中（模拟验证通过；在 d_cg 上从保存到通过要接上 write-pipeline、orchestration，属于 T-AS-6 联调）。代码 `approval/process.py`、`view.py`、`calc.py`、`service.py`、`router.py`、`module.py`。模拟验证：`test_process.py` 14 个（E37 管理员通过后进入会签、采购通过仍不写、生产通过后三行和物料清单 25 都写对且冻结解除，没注册的 T_COST_GOODS 经 TableWriter、注册过时经写入意图；单价 80 一级结束；通过后通知发起人；非审批人 403；指纹不一致 409；E17 同一请求键只执行一次；E39 取消 2556 后通过只写其余明细；E12 全部取消只写来源；E13 驳回原因必填、驳回后都不生效并解冻；E14 撤回；E15 合成审批的待办、逐级通过和驳回），`test_view.py` 8 个（E37 详情的"触发审批"列、物料清单 75→90、推算第 2 级会签、各人的操作按钮；E39 预览取消 2556 后单价 75、金额 23.25、每盒成本恢复且不保存勾选；下一级不能勾回；AP-21 记录已不存在排在最后、批准时跳过记入执行结果；E31/E33 合成审批的列并集和触发审批流），`test_router.py` 2 个（C09 第 6 节接口经 TestClient），`test_stage_contract.py` 6 个（PipelineStage 契约）。审批详情的计算用 `ToyRules` 替身代替 rules-core（金额 = 单价 × 每批数量等三条），不是真实规则。2026-10-30（丙组，`batch1/summary`）修两处显示：进度中按角色配置的审批人原来显示角色编码"ADMIN"（进入节点时成员名称记的是编码，`approvers.py`），改为显示时经 `ApprovalCatalog.role_name` 取角色名称（接线为 `ConfigSnapshotReader.read(角色).role().name`），已经发起的审批也显示名称；详情的小数原来按 `precision` 舍入后又去掉末尾的零（75.00 显示"75"），改为按小数位补足（"75.00"，同旧系统 `ApprovalPresentationGrid.vue` 的 `toFixed(precision)`），受影响单据的列没写 `precision` 时取读取这一块 `source` 的实体字段的 `scale`（C06 7.6"没写时取页面视图"）。模拟验证：`tests/approval` 90 个通过（E37 进度显示"系统管理员""采购""生产"；E37、E39、新增单据、接口测试的值按补零后的写法，例如物料清单 75.00 → 90.00、每盒成本 18.4250 → 18.9250）。前端 frontend-approval 照显示后端给的文字，没有改代码，e37、e39 的测试数据同步为补零后的值。
  - 2026-10-30（RA 组，`batch4/rules-approval`，输出在 `.reports/batch4-20261030/ra-rules-approval/`）：已撤回的审批 23、29 页面顶部"已撤回"，审批进度和审批人后面却写"待处理"（`steps[0].status`、成员 `status` 都是 pending），因为撤回只改了整个审批的状态。按旧系统改（`PKG_WF_APPROVAL` 的 `DO_CANCEL_APPROVAL`、`DO_REJECT_DETAIL` 把本轮 WAITING、PENDING 的审批记录改为 CANCELED，`ApprovalDetailDialog.vue` 显示"已撤回"）：`routing.py` 加 `close_unprocessed`，撤回时还没处理的节点和审批人记为 `withdrawn`；驳回时驳回的节点为 rejected，其中没处理的审批人和其余还没处理的节点为 `withdrawn`（核对时发现驳回也有同样问题：会签中另一人、几个审批流合并时另一审批流的本级节点原来都留着 pending）；已通过的节点不变。在这之前结束的（d_cg 的 23、29），`service.py` 的 `_steps` 在副本上同样换算，不改存下的进度。C09 v11 第 6 节、`contracts/types.py` 的 `StepMember`、`ApprovalStep` 加 `withdrawn`；AP-11 写明。模拟验证：`test_routing.py` 加撤回会签两人都已撤回、会签中驳回另一人已撤回、E15 驳回时另一审批流的节点已撤回；`test_view.py` 加撤回、驳回后的详情，和进度仍记着 pending 的旧记录换算为 withdrawn（存下的不变）。浏览器核对（后端 8088、前端 9535 → d_cg，`approval-steps.spec.cjs` 拦截全部非 GET 请求，没有拦到）：`/approval/23`、`/approval/29` 审批进度一行为"1 / 管理员审批 或签 / 角色：系统管理员（已撤回） / 成本明细改价审批 / 已撤回"，接口 `steps[0].status` 和成员 `status` 都是 withdrawn（`approval-23.png`、`approval-29.png`、`approval-*.api.json`、`approval-steps.out.json`）。旧系统或签通过后同节点其余审批人为"已跳过"（SKIPPED），新平台仍留 pending，不在这次范围。
  - 2026-10-30（RA 组，`batch4/rules-approval`）：审批通过时每次多 2 条 `user_tab_columns`（d_cg 上为 T_COST_GOODS，`.reports/batch3-20261030/h2-approval/findings.md` 的命令审查），来自 `view.py` 的 `_affected_table` 每次计算"修改内容"都调 `schema.columns(修改表)`，通过时算两次（核对指纹、最终批准）。新文件 `approval/columns.py` 的 `TableColumns` 按表名缓存列名，`Evaluator` 创建时建一个，每张表在进程内只读一次（同 write-pipeline 的 `ColumnScales`）；`Evaluator` 随审批命令阶段、详情服务和提交阶段在插件 setup 时各建一个，所以进程启动后详情页第一次、审批命令第一次各读一次，之后不再读。模拟验证：`test_view.py` 加一个（物料清单注册过，同 d_cg：两个审批从保存到通过共读 T_COST_GOODS 2 次，第二个审批 0 次；改前第一个审批就读 5 次，测试失败）。没有改的：最终批准写没注册的表时 `process.py` 的 `_table_write` 仍每次读一次列定义（d_cg 的物料清单已注册，不走这里）；`key_column`、`target_key_column` 每次计算都读一次主键（`user_constraints`，h2 的命令审查中每次通过 2 条），不在这次范围。没有在 d_cg 上做审批通过来数 SQL（会写业务数据）。
  - 2026-10-30（H5，T-AS-6、T-AS-7 的样例二）：C06 7.9、7.10 两个审批流在 d_cg 上从保存到最终批准真实跑通，没有改 approval 的代码：7.9 只冻结来源单据、没有受影响单据；7.10 的 E39 写法（审批人取消一张成本单，预览恢复为修改前，通过后只写勾选的明细和液体明细，没勾的不变），用新建的测试物料和成本单代替聚维酮K30 的 99 张成本单。液体成本没有注册实体，7.10 的液体两块改用视图自己的列。见 assembly 的 T-AS-6、T-AS-7。

### T-AP-4 强制审批、SQL 审批人与人工参数

- 归属与目标：实现 AP-18–AP-20，以及 AP-11。
- 前置输入：开始前 T-AP-2、T-AP-3。
- 负责范围：approval 的强制审批检查阶段、审批人 SQL 和各级人工参数的处理。
- 交付物：上述阶段和逻辑；C09 第 6 节通过请求中的 `params`。
- 接入责任：T-AS-6 注册阶段并联调。
- 验收标准：业务例子 E25、E26、E27。
- 状态与证据：进行中（模拟验证通过，待联调）。代码 `approval/required.py`（强制审批检查，阶段表中归在"触发审批"一行）、`approvers.py`（SQL 审批人）、`process.py`（各级人工参数、驳回和撤回）。模拟验证：`test_required.py` 5 个（E25：命中审批流进入审批、没有审批流命中时 409 APPROVAL_REQUIRED 且不写、本地物料行不命中、别的页面写这个字段 409、审批通过后写入不被拦），`test_params.py` 5 个（E26：查出的两个主管中只有启用的那个收到待办、一个都没有时 422；E27：第 1 级不填参数 422、填 2026-11-01 后业务表不变、第 2 级通过时修改和生效日期一起写入、第 2 级驳回都不写并解冻）。
  - 2026-10-30（H5，T-AS-6 的样例二）：E25 的正向流程在 d_cg 上真实跑通：物料清单实体 COST_GOODS_PRICE 的 `approvalRequired`（ZX_PRICE，ISERP=1，sourcePages GOODS_PRICE_MANAGE）随 seed 写入 d_cg；技术中心账号在物料清单页改 ERP 物料的单价，单据进入 GOODS_TO_COST，强制审批检查放行；通过后经写入管道写执行价（来源为审批，放行）。

### T-AP-5 已结束的审批显示结束时的值

- 归属与目标：实现 AP-23（C06 7.6"已结束的审批"、C09 第 6 节的 `viewUnsaved`）。来源：2026-10-30 浏览器核对发现已通过的审批 14（成本单 2550 的聚维酮K30 单价 90 → 75）打开后只显示"75.00"，没有箭头（`.reports/batch2-20261030/g0-verify/findings.md` 场景 7）：详情的修改前取的是打开详情时的当前数据。
- 前置输入：T-AP-3。
- 负责范围：`approval/process.py`（结束时存下）、`service.py`（已结束的读存下的）、`store.py`、`tables.py`、`model.py`、`restore.py`；迁移 `ap_0002_final_view.py`（PF_APPROVAL 加列 FINAL_VIEW）、`ap_0003_restore_final_view.py`（还原已结束、没存过的）；frontend-approval 的详情页写明没有保存。
- 交付物：结束时存下修改内容；已结束的审批详情读存下的；d_cg 上已结束的审批能还原的还原，还原不了的写明没有保存。
- 验收标准：成本单 2550 的聚维酮K30 单价 75 改成 90 通过、再改回 75 通过以后，两个审批分别显示 75.00 → 90.00、90.00 → 75.00；驳回、撤回的审批结束后数据再变，仍显示结束时的值；d_cg 的审批 14 显示 90.00 → 75.00。
- 状态与证据：进行中（2026-10-30，H2 组，`batch3/approval-snapshot`）。模拟验证：`tests/approval/test_final_view.py` 3 个（两次通过后两个审批分别为 75.00 → 80.00、80.00 → 75.00；驳回、撤回后改了数据仍是结束时的值；清掉存下的值后，已通过的按提交、通过两条命令的记录还原出的修改内容与结束时存下的相同，撤回的给出 `viewUnsaved`），`tests/approval` 共 93 个通过。真实验证：`test_oracle.py` 的 E37 提交测试加了 FINAL_VIEW 写入读出，`-m "oracle or redis" tests/approval` 12 个通过；d_cg 执行 `platform db upgrade`（ap_0002、ap_0003），审批 13、14 还原为 75.00 → 90.00、90.00 → 75.00（每盒成本 13.0065 → 13.0214、13.0214 → 13.0065），23、29（撤回）还原不了，见 `.reports/batch3-20261030/h2-approval/`。浏览器核对（后端 8088、前端 9535 → d_cg）：打开 13、14 分别显示 75.00 → 90.00、90.00 → 75.00，23、29 显示"这个审批结束时的修改前、修改后的值没有保存"；新做两次审批（chengben01 在成本核算把 2550 的 206323 单价 75 改成 90 保存，admin 在待办中通过，审批 72；再改回 75 通过，审批 73），结束后 72 显示 75.00 → 90.00、73 显示 90.00 → 75.00，物料清单 25 同样；2550 和物料清单 25 已恢复原值（只读查询核对）。

### T-AP-6 冻结和最终通过的加锁顺序

- 归属与目标：按用户 2026-10-30 同意的"固定加锁层级"改 AP-02、AP-03、AP-10（write-pipeline WP-03）：冻结前按统一顺序锁住要冻结的数据；往前、同层冻结时本单据推迟加锁、一次锁完；冻结只登记在已锁住的数据上，锁后单独查冻结；审批最终通过在"确定涉及的单据"锁全；审批记录的加锁经统一入口（`FOR UPDATE WAIT n`）。
- 前置输入：T-AP-2、T-AP-3；write-pipeline 的 `BusinessLocker`（T-WP-7）。
- 负责范围：`approval/trigger.py`（`TriggerScopeStage`、`TriggerStage` 的 `_freezes`、`_lock`、`_affected`、`_exclusive` 的先后）、`process.py`（`ResolveStage` 锁审批记录和 `write_targets`，`ProcessStage` 读审批记录不加锁）、`store.py`（`load` 不再自己加锁、`freeze`）、`freeze.py`（`check_documents`、`defer_lock` 时冻结检查由触发审批做）、`deps.py`、`module.py`、`plugin.py`。
- 交付物：上述功能。
- 接入责任：assembly 不用改插件清单（approval 插件多要一个端口，由 pipeline 插件提供）。
- 验收标准：成本单改价（COST_TO_GOODS）先锁成本单、冻结前再锁物料清单；物料清单改价（GOODS_TO_COST）把含这个物料的成本单和物料清单一次锁完；物料清单在加锁前读取和加锁之间被改时整个回滚、重来一次；最终通过时审批记录、来源单据、受影响行所属的单据和没注册表的行都在开头锁住，之后不再追加；d_cg 上并发时冻结生效后别人的修改提交不了。
- 状态与证据：进行中（2026-10-30，L 组，`batch4/lock-order`），模拟验证和真实验证通过，合并后没有联调。模拟验证：`tests/approval/test_lock_order.py` 7 个（审批流只在内存配置中），`tests/approval` 其余用例照常通过。真实验证：write-pipeline 的 `tests/pipeline/test_oracle_lock_order.py`（经 approval 的真实阶段和 PF_APPROVAL*，见 T-WP-7）；`tests/approval` 的 oracle 用例照常通过。中途某一级通过也先锁住最终可能要写的单据（不确定是不是最终通过），命令结束即释放。

### T-AP-7 复制出的行进入审批后按提交时的值写

- 归属与目标：AP-02、AP-10 中复制出的行（C02 `copyOf`，write-pipeline WP-21）。来源：`.reports/batch4-20261030/p-pipeline-fixes/findings.md` 最后一节：复制出的行提交审批后，最终通过按原来的 Patch 重放，不可写的复制字段按命令中的值写，还会补默认值；用户 2026-10-30 同意下一批直接做。旧系统送审时把待审数据存下、通过时按它写入（`ConfiguredApprovalRuntime.java` 第 108–113 行、第 674–688 行），写入不补默认值（`DynamicDataService.java` 第 272–327 行）。
- 前置输入：T-AP-2、T-AP-3；write-pipeline 的 T-WP-10。
- 负责范围：`approval/patch.py`（`resolved_patch`：提交时把复制行的值换成 `CommandState.changes` 中 write-pipeline 解出的、能写进表的字段；`patch_intents` 给复制行的意图带 `copy_of`）、`trigger.py`（存待审修改时调用）；contracts 的 `RowIntent.copy_of`（C08 v19）；write-pipeline 的 `IntentMerger._add`（带 `copy_of` 时不补默认值）。
- 交付物：上述功能。
- 验收标准：复制成本单 2550 带明细（含一行单价与执行价不同的明细，进入 COST_TO_GOODS），保存提交审批；审批详情中新单据的值是保存那一刻按源单据解出的值；admin 通过后，新单据复制的字段与源单据相同，没复制的字段为空（不补默认值），与不进审批直接保存的复制结果相同。
- 状态与证据：模拟验证和真实验证通过（2026-10-30，B2 组，`batch5/approval-copy-skip`），没有和 B1 组的 `IntentMerger._add` 改动合并验证。模拟验证：`tests/approval/test_new_document.py::test_copied_document_approved_with_values_resolved_at_submission`（复制 2550 后源单据的币种在保存前、审批中各被改一次，待审修改存保存那一刻的"美元"，不含物料名称、每批数量；通过后新单据币种"美元"；写入管道由 `support.Pipeline` 替身按 WP-21 代替）；`tests/pipeline/test_copy.py::test_approved_copied_rows_are_written_as_resolved_without_defaults`（带 `copy_of` 的意图只写给出的列，不是复制的新增明细照常补默认值）。真实验证（d_cg + Redis，`tests/e2e/test_copy_approval.py`，`.reports/batch5-20261030/b2-approval/`）：admin 复制 2550 的主表和单价等于执行价的 10 行明细，再复制 206325 硬脂酸镁一行、把物料换成测试物料（参考价 10、执行价空，单价 63），进入 COST_TO_GOODS，冻结新单据和测试物料；这一行命令中 13 个字段（含只在视图中的物料名称等），待审修改中 6 个；详情中复制的 11 行都是"新增"、物料名称按 Lookup 查出；admin 通过后，新单据与同样复制、直接保存的另一张逐列相同（计算字段、主键、默认 SYSDATE 的两列除外），币种与 2550 相同、项目号为空；两张单据经平台删除，测试物料、审批、命令记录删掉。触发审批的那一行没有用 2550 自己单价与执行价不同的四行：通过时会把真实物料清单的执行价、修改人改掉，经平台改不回。d_cg 上 chengben01 没有成本核算的新增行权限，复制由 admin 做。

### T-AP-8 或签一人通过后其余审批人显示已跳过

- 归属与目标：AP-04 中或签节点的进度（C09 v12 `members[].status` 的 `skipped`）。来源：`.reports/batch4-20261030/ra-rules-approval/findings.md`"没有处理的"：或签节点配了两个人，一人通过后另一人仍显示"（待处理）"；旧系统为 SKIPPED"已跳过"（`docs/approval-refactor-20261026-ordinary-install.sql` 第 911 行、第 1601–1607 行，`ApprovalDetailDialog.vue` 第 302–315 行）；用户 2026-10-30 同意下一批直接做。
- 前置输入：T-AP-1、T-AP-3；frontend-approval 的详情页、frontend-page 的审批进度弹窗（FP-16）。
- 负责范围：`approval/routing.py`（`skip_unprocessed`，通过时调用）、`service.py`（`_steps` 显示时换算之前的记录）；contracts 的 `StepMember.status`（后端 `types.py`、前端 `contracts/http.ts`）；前端 `modules/approval/view-model.ts` 的 `MEMBER_STATUS`、`modules/page/approval-progress.ts`（审批进度弹窗的文字，从 `ApprovalProgressDialog.vue` 移出以便测试）。
- 交付物：上述功能。
- 验收标准：或签节点配了两个人，一人通过后，审批详情和页面上的审批进度弹窗中另一人显示"已跳过"，不能再处理；会签节点一人通过后另一人仍待处理；之前通过的或签节点显示时同样换算。
- 状态与证据：模拟验证和真实验证通过，浏览器没有核对（2026-10-30，B2 组，`batch5/approval-copy-skip`）。模拟验证：`tests/approval/test_routing.py` 2 个（或签李四通过后张三已跳过、不能再处理；会签不跳过），`test_view.py` 2 个（系统管理员通过后采购员已跳过、审批进入第 2 级；进度中还记着 pending 的显示为 skipped，存下的不变）；前端 `tests/approval/e37.test.ts`（详情的审批人"第二审批人（已跳过）"）、`tests/page/approval-progress.test.ts`（弹窗的审批人文字）。真实验证（d_cg）：`tests/approval/test_oracle_or_sign.py`，进程内接真实的权限、写入管道、审批阶段和服务，配置为 seed 加测试审批流 PF_TEST_OR_SIGN（只在内存中，d_cg 的 PF_CONFIG_ITEM 不动）：第 1 级"两人或签"配 admin 和 chengben01，admin 新建测试成本单、改原辅料备注提交审批，admin 通过后详情为"系统管理员 passed、成本会计一 skipped"，PF_APPROVAL.PROGRESS 中存的也是 skipped，chengben01 不能再通过；驳回后第 1 级不变；成本单、审批、命令记录都删掉。浏览器核对要在 d_cg 的共用配置里建一个或签配两个人的审批流（会发 config.changed，别组同时在跑前端端到端用例），这次没有做。
