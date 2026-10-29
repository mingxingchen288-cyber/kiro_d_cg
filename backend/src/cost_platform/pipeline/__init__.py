"""唯一的业务数据写入口（docs/模块/write-pipeline.md）。

插件 `plugin.PipelinePlugin`（name `pipeline`）创建下面的对象并注册端口；orchestration 按 `STAGE_ORDER` 执行管道阶段：

| 位置 / 端口 | 能力 | 规则 |
|---|---|---|
| 判重、命令结果、写命令记录 | `command_log.OracleCommandRecorder`（端口 CommandRecorder：begin、finish、complete） | WP-01、WP-02、WP-11–WP-13 |
| 确定涉及的单据（页面保存） | `loader.PageSaveInvolved`（PipelineStage） | C08 第 6 节 |
| 加锁读取 | `stages.LockStage` → `loader.DocumentLoader` + `document_store.OracleDocumentStore`（本模块的 `RowStore`） | WP-03、WP-05、WP-18 |
| 合并修改 | `stages.MergePatchesStage` → `merge.DocumentMerger` | WP-04–WP-06、WP-14–WP-16 |
| 合并意图 | `stages.MergeIntentsStage` → `merge.IntentMerger` | WP-18 |
| 计算与规则 | `stages.RecalculateStage` → `calc.Recalculator`、`calc.check_required` | WP-07、WP-08、WP-15 |
| 写入变更 | `stages.WriteChangesStage` → `writer.ChangeWriter` | WP-06、WP-09 |
| 审计、命令结果 | `result.audit_changes`、`result.build_result`（由 `complete` 调用） | WP-11、WP-12 |
| 审批通过后写没注册的表 | `table_writer.OracleTableWriter`（端口 TableWriter） | WP-19 |
| 命令审查（这次没有接入插件） | `review.ReviewedCommandExecutor`、`review.RedisCommandReview`、`review.command_review_router`、`tracing.SqlTracer` | WP-17、C09 第 7a 节 |
| 小数位 | `values.ColumnScales`（列的小数位取 SchemaInspector） | WP-15 |

`merge.PatchMerger` 是原端口 `ChangeMerger` 的按实体合并（2026-10-29 起不是端口），管道阶段不用它。
"""
