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
