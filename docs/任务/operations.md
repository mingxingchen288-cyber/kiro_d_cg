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
- 状态与证据：待联调（2026-10-29，还没有独立复核）。代码：`backend/src/cost_platform/operations/`（`stages.py` 的 `ButtonInvolvedStage`、`ActionStage`，`actions.py` 三种动作的展开，`mapping.py` 字段映射、可写检查和冲突，`selection.py` 选中行）。模拟验证：`uv run pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/operations` 36 个通过、0 个失败（与 T-OP-2 合计，`.reports/modules/operations/pytest.txt`）；`uv run lint-imports --no-cache` 3 条规则保持（`lint-imports.txt`）。逐条：展开结果、来源计算后的值、冲突与 `match` 不冲突、计算字段和 ERP 行的 ERP 列被拒、选中行为空、带 `documents`、按 D 的当前数据逐行调用 `RelatedQuery`、"同步单价"80/12、主键为空的行跳过、选中行已删除的 skip 和 reject 见 `tests/operations/test_actions.py`、`test_involved.py`；两个阶段通过管道阶段契约测试（`test_contracts.py`）。传播边界 `end`（2026-10-29 核对）：触发审批只对页面保存执行，按钮命令的 `documents` 为空，按钮写到的目标不会触发审批；旧系统按钮写必须审批的字段时拒绝（`ActionWriteGuard` → `guardDirectMutation`），新系统由强制审批检查拒绝；旧系统没有 `continue` 的级联。原来的 `ActionStage.propagation_ended` 没有使用方，已删除。"找到的成本单被冻结返回 FROZEN_BY_APPROVAL"由 write-pipeline 对不在 `involved` 中的单据加锁、做冻结检查（WP-18），本模块的测试只核对 intents 指向这些单据，返回码在 T-AS-5 联调时验证。`updateTargets`、`recalculate: targets` 的目标按"本命令前面 `updateRecords` 找到的对象"实现，契约没有写明（缺口第 1 项）。上线后再补：配置写错（`fieldMapping` 引用了取不到的实体、`impact` 没有列出明细所属的主表实体、`selectedRows` 格式不对）的用例。

### T-OP-2 逃生舱机制

- 归属与目标：实现 OP-04。
- 前置输入：开始前 T-OP-1；用户同意在 d_cg 中建一个测试用存储过程（名称以 `PF_TEST_` 开头）。
- 负责范围：operations 中逃生舱的执行和调用审计。
- 交付物：逃生舱执行；只在测试配置中启用的测试存储过程。首版配置中不启用任何逃生舱。
- 接入责任：T-AS-6 联调。
- 验收标准（真实验证）：逃生舱在命令事务内执行，之后的动作失败时它的写入一起回滚；调用审计随命令记录写入。
- 状态与证据：进行中（2026-10-29）。代码：`backend/src/cost_platform/operations/escape_hatch.py`。登记表 `EscapeHatchRegistry` 默认为空，只登记用户点名启用的逃生舱，没登记的拒绝执行（422）；登记的调用有三种，对应旧系统的三种执行器：存储过程（proc，IN/OUT/INOUT，可核对 USER_SOURCE 源码指纹）、语句（sql，绑定变量）、处理函数（java）。在动作执行阶段排到这个动作时、在命令事务的连接上执行，自身不提交不回滚；每次调用生成 `EscapeHatchCall`（逃生舱、参数、执行人、时间和请求键）。模拟验证（内存 SQLite，存储过程用测试替身代替）：`tests/operations/test_escape_hatch.py` 6 个通过，包括之后的动作失败时写入一起回滚、没登记的被拒绝、语句和处理函数各一例（命令与 T-OP-1 合计 36 个通过，`.reports/modules/operations/pytest.txt`）。真实验证：`tests/operations/test_escape_hatch_oracle.py` 4 个（提交、之后的动作失败回滚、源码指纹、语句）2026-10-29 在 d_cg 上通过；用户 2026-10-29 同意这组测试每次在 d_cg 建测试用存储过程 `PF_TEST_ESCAPE_HATCH` 和表 `PF_TEST_ESCAPE_LOG`（fixture 建、结束时删），跑完后 `USER_OBJECTS` 中没有残留。生成的 PL/SQL 匿名块见 `.reports/modules/operations/probe_plsql.txt`（不连数据库）。调用审计随命令记录写入（2026-10-29）：调用记录写进 `CommandState.escape_hatch_calls`，由 `CommandRecorder.complete` 用完成命令记录的同一条 UPDATE 写入 PF_COMMAND 的 ESCAPE_HATCH_CALLS 列（迁移 wp_0002，d_cg 已升级）；只调用逃生舱的命令结果为 saved，照常提交。参数怎样绑定契约没有写，按服务端登记实现（`contract-gaps.md` 第 3 项）。首版配置中不启用任何逃生舱。
