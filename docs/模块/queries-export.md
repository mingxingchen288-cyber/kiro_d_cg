# queries-export

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：列表（服务端行模型的分页、排序、筛选、高级查询、汇总、总数）、按主键取行、单据加载、Lookup、字典、个人列配置、导出 xlsx；实现 `RelatedQuery`（按钮的 `updateRecords` 用）、`DocumentReader`、`PersonalConfigImporter`；[C09 第 4 节](../契约/C09-HTTP接口.md)的接口。
- 不负责：写业务表（write-pipeline）；行权限条件的生成（authz）；冻结记录（approval）。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `backend/src/cost_platform/queries/` |
| 数据 | 表 `PF_PERSONAL_CONFIG`（用户、页面、表格、列配置、明细显示方式）；业务表只读 |

## 3. 对外契约

提供 `RelatedQuery`、`DocumentReader`、`PersonalConfigImporter`（[C08](../契约/C08-后端端口.md)），以及 C09 第 4 节的接口。

- QE-01：查询前调用 authz 的 `row_condition`，与筛选条件用 AND 组合；行权限范围外的行按不存在处理。
- QE-02：返回的行包含实体的全部字段，不按可见性过滤；筛选、排序和高级查询引用不可见或不存在的字段时，返回 422 VALIDATION_FAILED。
- QE-03：实体设置了 `readView` 时从视图读取（[C06](../契约/C06-配置模型.md) 第 2 节）。
- QE-04：没有排序时按主键排序；排序值相同时再按主键排序，保证分页稳定。汇总对全部满足条件的行计算：汇总的字段是页面视图主表区中 `aggregate` 为 `sum` 的可见字段（C06 第 3 节，对应旧系统列配置的 `aggFunc: "sum"`），与总数在同一条 `SELECT COUNT(*), SUM(…)` 中查出；`endRow` 等于 `startRow` 时只返回总数和汇总（前端保存后用它重新取汇总，frontend-page 的 FP-17）。
- QE-05：返回的行标明是否被冻结、被哪个审批冻结；冻结记录经 approval 的 `FreezeReader` 读取。
- QE-06：导出写成 xlsx。单元格的值与旧系统 `CustomExportService.normalizeCellValue` 相同：数值写成数值单元格（Excel 里能直接求和），日期时间写成文本（`yyyy-MM-dd HH:mm:ss`，日期 `yyyy-MM-dd`），是非为是非单元格，其余为文本（用户 2026-10-30 同意）。数值单元格中写的是数据库原样的十进制文本，不经过浮点、不用科学计数法；Excel 打开时按双精度读，只保留 15 位有效数字，与旧系统相同（旧系统经 EasyExcel 写成 double）。例如 d_cg 成本单 2566 的每批辅料成本 `1292.385444247787610619469026548672566372` 在 Excel 中显示为 1292.38544424779。列宽和链接列的推断按单元格的文本（数值为十进制文本）。
  - 默认导出当前页面：能打开页面就能导出；按请求中的查询条件和排序导出主表的查询结果，列为用户当前显示的列，且必须对当前角色可见；行和顺序与列表一致。
  - 按导出配置导出（C06 第 9 节）：authz 的 `can_export` 为 true 才能使用，否则返回 403；`scope` 为 `current` 时按当前查询条件和行权限限定，为 `all` 时只按行权限限定；列由导出配置决定。
- QE-07：个人列配置按（用户、页面、表格）保存列宽、顺序、固定、显隐，以及明细显示方式；保存时只替换请求中给出的部分。
- QE-08：`RelatedQuery` 执行关联 SQL 时只读、使用绑定变量，结果缺少 `recordKeyColumn` 或 `rowKeyColumns` 中的列时整个查找失败（500 INTERNAL_ERROR），不返回部分结果；某一行的这些列的值为空时，这一行返回为 `missing` 的对象，其余行照常返回（C08 第 9 节）；按关联键查找时，用传入单据中 `sourceKey` 所指实体的全部行的键值查目标；关联 SQL 的绑定变量引用明细字段时，按传入单据中这个明细的行的顺序逐行各执行一次，只引用主表字段时执行一次；结果按这个顺序合并、每次按 SQL 返回的顺序，同一对象只保留第一次出现的那一个，同一次执行查出的重复行也只算一个（C08 第 9 节）。`rows` 为 `changed` 时只传入有变化的行，由调用方按 C08 第 9 节准备。
- QE-09：Lookup 的关键字先去掉首尾空白。为空时返回全部候选；不为空时在 `keywordColumns` 中按包含匹配。`keywordColumns` 为空表示该 Lookup 不支持关键字搜索，这时关键字不为空返回 400 INVALID_REQUEST，不忽略关键字照常返回。两种情况都照常执行 `filter` 过滤（QE-11）和分页，返回总数，访问要求与其他查询接口相同（C09 第 1 节），Lookup 不另设权限；响应的 `keywordSearch` 给出是否支持关键字搜索（C09 第 4 节）。
- QE-10：对比（C06 第 2 节 `compare`）：列表、按主键取行和单据加载查出数据后，`field` 模式直接取同一行的字段；`query` 模式按数据源分组，每个数据源追加一条查询（关联键用 IN 和绑定变量，每批最多 1000 个键）。每行的 `compare` 给出对比值、差值和百分比，用十进制计算；百分比四舍五入到 2 位小数，对比值为 0 或为空时不给百分比。对比只用于显示，不导出，不参与保存。
- QE-11：Lookup 的 `filter`：`column` 必须是该 Lookup 的列，值用绑定变量传入；值为空时不过滤。
- QE-12：高级查询中写了明细实体的条件，同一明细实体的合成一个 `EXISTS`，由同一条明细行满足；不同明细实体之间为且（C09 第 4 节）。

## 4. 依赖

| 契约 | 提供方 | 用途 |
|---|---|---|
| `UnitOfWork` | db-core | 只读查询；个人配置的写入 |
| `PermissionChecker` | authz | 行权限条件 |
| `FreezeReader` | approval | QE-05 |

## 5. 内部流程

列表：页面视图 → 校验筛选和排序字段 → 生成 SQL（行权限 AND 筛选，排序加主键，分页）→ 一条查行、一条查总数和汇总 → 标记冻结 → 返回。

## 6. 接入方式

- assembly 挂载本模块的路由；approval 调用 `DocumentReader`；operations 调用 `RelatedQuery`；migration 调用 `PersonalConfigImporter`。
- 真实联调：批次 B。

## 7. 验收边界

- 开始开发的前置条件：contracts 完成。
- 本模块完成（模拟验证）：分页边界、排序稳定、行权限、不可见字段的筛选被拒、导出与列表一致、个人配置部分替换。
- 联调后才能确认：在 Oracle 上分页和汇总的结果正确，导出大数据量时分批读取（批次 B）。

