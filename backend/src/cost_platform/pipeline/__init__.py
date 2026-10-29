"""唯一的业务数据写入口（docs/模块/write-pipeline.md）。

提供的能力（由 orchestration 按架构第 7 节的顺序调用，由 assembly 组装）：

| 步骤 | 能力 | 规则 |
|---|---|---|
| 1 判重 / 12 写命令记录 | `command_log.OracleCommandRecorder`（端口 CommandRecorder） | WP-01、WP-02、WP-11、WP-13 |
| 3 确定涉及的单据（页面保存） | `loader.PageSaveInvolved`（PipelineStage） | C08 第 6 节 |
| 4 加锁读取 | `loader.DocumentLoader` + `document_store.OracleDocumentStore`（端口 DocumentStore） | WP-03、WP-05 |
| 7 合并 Patch | `merge.DocumentMerger`（端口 ChangeMerger 的按实体用法为 `merge.PatchMerger`） | WP-04–WP-06、WP-14–WP-16 |
| 7 合并 intents | `merge.IntentMerger` | WP-18 |
| 7 计算与规则、必填 | `calc.Recalculator`、`calc.check_required` | WP-07、WP-08、WP-15 |
| 9 写入变更 | `writer.ChangeWriter` | WP-06、WP-09 |
| 10 审计、命令结果 | `result.audit_changes`、`result.build_result` | WP-11、WP-12 |
| 审批通过后写没注册的表 | `table_writer.OracleTableWriter`（端口 TableWriter） | WP-19 |
| 命令审查 | `review.ReviewedCommandExecutor`、`review.RedisCommandReview`、`review.command_review_router`、`tracing.SqlTracer` | WP-17、C09 第 7a 节 |
| 小数位 | `values.ColumnScales`（列的小数位取 SchemaInspector） | WP-15 |
"""
