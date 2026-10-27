# operations 任务

模块说明：[operations](../模块/operations.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E10、E11（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-OP-1 通用动作与按钮操作

- 归属与目标：实现 OP-01–OP-03、OP-05、OP-07、OP-08，按钮操作的"确定涉及的单据"和"动作执行"中的展开。
- 前置输入：开始前 T-CT-1、T-CT-3；C06 第 4、6 节经用户确认。
- 负责范围：`backend/src/cost_platform/operations/`。
- 交付物：`applyPendingChanges`、`recalculate`、`updateTargets`、`updateRecords` 的展开；字段映射；传播边界。
- 接入责任：T-AS-5 注册按钮操作的阶段；T-AS-6 接入批准后动作。
- 验收标准（模拟验证）：每种动作的展开结果正确；字段映射取来源计算后的值；同一目标被多行来源找到且值不同时返回 VALIDATION_FAILED；映射到计算字段，或映射到 ERP 行的 ERP 列被拒绝；传播边界为 `end` 时目标不触发审批；按钮需要选中行而没有时返回 VALIDATION_FAILED；按钮命令带了 `documents` 时返回 INVALID_REQUEST；选中成本单 D 点按钮时，`updateRecords` 按 D 在数据库中的当前数据查找和写入；选中的行在点按钮前已被删除时，`rowNotFound` 为 `skip` 写入 `skipped`，为 `reject` 返回 ROW_NOT_FOUND；审批流 `afterApproval` 中的 `updateRecords` 为 `rows: changed` 时按 C08 第 9 节准备来源单据：一张有 10 条明细的单据只改了第 3 条，`RelatedQuery` 收到的来源单据中这个明细只有第 3 条，整单计算和保存仍用 10 条；`sourceKey` 指向主表而主表没有变化时不查找；修改了关联键的行只按新值查找；审批流监听删除时，删除的行用删除前的值查找；`updateRecords` 的关联 SQL 查出的行中有一行主键为空时，跳过这一行，其余行照常更新；按钮操作的 `updateRecords` 找到的成本单被审批冻结时，整个命令返回 FROZEN_BY_APPROVAL（WP-18）；`selection` 为 `all` 时 `updateTargets` 不更新记录已不存在的候选对象；按钮操作的"确定涉及的单据"和"动作执行"中的展开通过 `PipelineStage` 的契约测试（C08 第 14 节）。
- 状态与证据：未开始。

### T-OP-2 逃生舱机制

- 归属与目标：实现 OP-04。
- 前置输入：开始前 T-OP-1；用户同意在 d_cg 中建一个测试用存储过程（名称以 `PF_TEST_` 开头）。
- 负责范围：operations 中逃生舱的执行和调用审计。
- 交付物：逃生舱执行；只在测试配置中启用的测试存储过程。首版配置中不启用任何逃生舱。
- 接入责任：T-AS-6 联调。
- 验收标准（真实验证）：逃生舱在命令事务内执行，之后的动作失败时它的写入一起回滚；调用审计随命令记录写入。
- 状态与证据：未开始。
