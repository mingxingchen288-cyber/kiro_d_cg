# queries-export 任务

模块说明：[queries-export](../模块/queries-export.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E01、E29、E30（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-QE-1 列表、按主键取行与单据加载

- 归属与目标：实现 QE-01–QE-05 和 C09 第 4 节的前三个接口。
- 前置输入：开始前 T-CT-1、T-CT-3。验收前 T-DB-1、T-DB-3。
- 负责范围：`backend/src/cost_platform/queries/` 的查询生成和路由。
- 交付物：AG Grid 排序、筛选模型和高级查询到 SQL 的转换（全部用绑定变量）；分页、总数和汇总；冻结标记。
- 接入责任：T-AS-5 挂载路由并接入真实 authz；T-AS-6 接入 `FreezeReader`。
- 验收标准：模拟验证：startRow 等于总数时返回 0 行；排序值相同时按主键稳定排序；用不可见或不存在的字段筛选、排序返回 VALIDATION_FAILED；行权限范围外的单据返回 NOT_FOUND；真实验证：在 d_cg 上分页和汇总正确，物料清单经视图读取。
- 状态与证据：未开始。

### T-QE-2 Lookup、字典、个人配置与读取端口

- 归属与目标：实现 QE-07–QE-09，以及 `RelatedQuery`、`DocumentReader`、`PersonalConfigImporter`。
- 前置输入：开始前 T-QE-1。
- 负责范围：queries 的 Lookup、字典、个人配置和三个端口；表 `PF_PERSONAL_CONFIG` 的迁移脚本。
- 交付物：C09 第 4 节的 Lookup、字典和个人配置接口；三个端口。
- 接入责任：approval、operations 使用 `RelatedQuery`、`DocumentReader`（T-AS-6）；migration 使用 `PersonalConfigImporter`（T-AS-8）。
- 验收标准：模拟验证：个人配置只替换请求中给出的部分；Lookup 的 `keywordColumns` 为空时，只有空白的关键字照常分页返回全部候选，非空关键字返回 400 INVALID_REQUEST，响应的 `keywordSearch` 为 false；关联 SQL 缺少 `recordKeyColumn` 或 `rowKeyColumns` 中的列时返回 500 INTERNAL_ERROR，不返回部分结果；关联 SQL 查出 3 行、其中一行的 `recordKeyColumn` 为空时，返回 3 个对象，这一个 `missing` 为 True、`record_key` 为空，另外两个照常；按关联键查找时用传入单据中 `sourceKey` 所指实体的全部行；关联 SQL 绑定原辅料的物料编号、传入单据有物料 115、116 两行时，按两行各执行一次，含两种物料的成本单只返回一次；通过 `RelatedQuery`、`DocumentReader`、`PersonalConfigImporter` 的契约测试；真实验证：C06 7.5 的两条关联 SQL 在 d_cg 上查出成本单。
- 状态与证据：未开始。

### T-QE-3 导出

- 归属与目标：实现 QE-06 和 C06 第 9 节的导出版式。
- 前置输入：开始前 T-QE-1。
- 负责范围：queries 的导出。
- 交付物：`GET /api/pages/{pageCode}/exports`、`POST /api/pages/{pageCode}/export`；默认导出当前页面和按导出配置导出两种方式。
- 接入责任：T-AS-5 挂载路由。
- 验收标准：模拟验证：默认导出只含用户当前显示且可见的列，行和顺序与列表相同；角色没有该导出配置时返回 PERMISSION_DENIED；数值为文本单元格，`12345678.12345678` 在 Excel 中打开后显示不变；真实验证：按旧系统的 cost-pinggu-export 写一份导出配置，在 d_cg 上以管理员导出，主表和两张明细工作表的行、列与旧系统相同；数据量大时分批读取，导出期间其他提交不造成重复或遗漏；用同一批数据从旧系统和新平台各导出 cost-pinggu-export，工作表名、明细块、主从链接、多级表头、字体和列宽一致。
- 状态与证据：未开始。

### T-QE-4 对比、Lookup 过滤与明细条件

- 归属与目标：实现 QE-10–QE-12。
- 前置输入：开始前 T-QE-1、T-QE-2。
- 负责范围：queries 的对比、Lookup 过滤和高级查询中的明细条件。
- 交付物：上述功能。
- 接入责任：T-AS-5 联调。
- 验收标准：业务例子 E29、E30；模拟验证：对比值为 0 时不给百分比；Lookup 的 `filter.column` 不是 Lookup 的列时返回 422；`keywordColumns` 为空的 Lookup 用只有空白的关键字和 `filter` 查询时，照常按 `filter` 过滤并分页（QE-09）；真实验证：在 d_cg 上 E30 查出的成本单与旧系统同样条件查出的相同。
- 状态与证据：未开始。
