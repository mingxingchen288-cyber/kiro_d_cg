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
- 状态与证据：进行中（模拟验证通过，真实验证已写好、待合并后运行）。2026-10-29 按模块一次做完 QE-01–QE-05：`PageQueries` 的列表（AG Grid 文本、数值、日期、集合筛选和组合筛选，高级查询，行权限，排序加主键，分页，一条查总数和汇总，冻结标记）、`by_keys`、单据加载，以及 `router.build_router` 的前三个接口；`PageQueries(uow, permission)` 的构造方式不变，冻结读取和汇总字段是可选的关键字参数（汇总字段的配置是契约缺口，见 `.reports/modules/queries-export/contract-gaps.md` 第 2 项）。对照旧系统 `DynamicDataService.query/buildQueryWhereClause/buildConditionClause/buildOrderClause/getById` 和前端 `grid-filter-conditions.ts`。模拟验证：在 contracts 的 SQLite 替代事务上真实执行 SQL，`uv run pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/queries`，本卡相关的 `test_lists.py` 22 个、`test_router.py` 中 4 个通过（全模块 76 个通过、0 个失败，输出 `.reports/modules/queries-export/pytest.txt`）。真实验证（`tests/queries/test_oracle.py`，标 oracle，未运行）：`test_paging_total_and_sum`、`test_equal_sort_values_page_stably`、`test_record_2550_details_through_views`；生成的 SQL 形状已在 d_cg 只读核对通过（`04-生成SQL语法核对.out.txt`）。"物料清单经视图读取"：d_cg 中还没有 T_COST_GOODS_PRICE_V，改为验证原辅料、包材明细经 V_COST_PINGGU_MATERIAL、V_COST_PINGGU_PACKAGE 读取。真实联调见 T-AS-9（[assembly](assembly.md)）。2026-10-30（丙组，`batch1/summary`）：汇总字段的契约缺口已补（C06 v18 页面字段的 `aggregate`，由旧系统 SUMMARY_CONFIG 功能推出；C05 v4、C09 v10），`SnapshotCatalog.sum_fields` 取页面视图中 `aggregate` 为 `sum` 的可见字段，插件接上后列表的 `aggregates` 不再为空。模拟验证：`tests/queries/test_plugin.py` 的列表汇总取自配置快照（总成本 46.25）。真实验证：`tests/queries/test_oracle_summary.py` 1 个在 d_cg 上通过（seed 配置生成的系统管理员页面视图，筛选产品名称含"片"、第一页 20 行，14 个求和字段与直接 `SUM` 全部满足条件的行相同）。

### T-QE-2 Lookup、字典、个人配置与读取端口

- 归属与目标：实现 QE-07–QE-09，以及 `RelatedQuery`、`DocumentReader`、`PersonalConfigImporter`。
- 前置输入：开始前 T-QE-1。
- 负责范围：queries 的 Lookup、字典、个人配置和三个端口；表 `PF_PERSONAL_CONFIG` 的迁移脚本。
- 交付物：C09 第 4 节的 Lookup、字典和个人配置接口；三个端口。
- 接入责任：operations 使用 `RelatedQuery`，approval 使用 `DocumentReader`（T-AS-6）；migration 使用 `PersonalConfigImporter`（T-AS-8）。
- 验收标准：模拟验证：个人配置只替换请求中给出的部分；Lookup 的 `keywordColumns` 为空时，只有空白的关键字照常分页返回全部候选，非空关键字返回 400 INVALID_REQUEST，响应的 `keywordSearch` 为 false；关联 SQL 缺少 `recordKeyColumn` 或 `rowKeyColumns` 中的列时返回 500 INTERNAL_ERROR，不返回部分结果；关联 SQL 查出 3 行、其中一行的 `recordKeyColumn` 为空时，返回 3 个对象，这一个 `missing` 为 True、`record_key` 为空，另外两个照常；按关联键查找时用传入单据中 `sourceKey` 所指实体的全部行；关联 SQL 绑定原辅料的物料编号、传入单据有物料 115、116 两行时，按两行各执行一次，含两种物料的成本单只返回一次；通过 `RelatedQuery`、`DocumentReader`、`PersonalConfigImporter` 的契约测试；真实验证：C06 6.1 的关联 SQL 在 d_cg 上查出成本单。
- 状态与证据：进行中（模拟验证通过，真实验证已写好、待合并后运行）。2026-10-29 实现 Lookup 和字典（`lookups.py`，对照旧系统 `DynamicDataService.queryLookupData`、`MetadataService.getDictItems`）、个人列配置（`personal.py`，表 PF_PERSONAL_CONFIG，迁移脚本 `queries/migrations/qe_0001_pf_personal_config.py`，没有在 d_cg 上执行；对照旧系统 `grid/UserGridConfigService`）、`OracleRelatedQuery`（`related.py`）、`OracleDocumentReader`（`documents.py`），以及 C09 第 4 节的 Lookup、字典、个人配置接口。`PersonalConfigImporter` 只为迁移服务，按 2026-10-29 的规则随 migration 暂停，没有实现，它的契约测试没有运行。两个端口读实体配置要在构造时注入（契约缺口第 3 项）。模拟验证：`test_lookups.py` 7 个、`test_personal.py` 5 个（迁移脚本在 SQLite 上建表）、`test_related_query.py` 16 个（含 contracts 的 `RelatedQueryContract` 13 个，用真实实现在 SQLite 上执行关联 SQL）、`test_document_reader.py` 6 个（含 `DocumentReaderContract` 5 个）、`test_router.py` 中 2 个通过。真实验证（未运行）：`test_c06_relation_sql_finds_cost_details`、`test_detail_bind_runs_per_row_and_each_document_once`、`test_document_reader_loads_2550`、`test_lookup_on_t_cost_goods`、`test_personal_config_on_d_cg`（需先建 PF_PERSONAL_CONFIG）。

### T-QE-3 导出

- 归属与目标：实现 QE-06 和 C06 第 9 节的导出版式。
- 前置输入：开始前 T-QE-1。
- 负责范围：queries 的导出。
- 交付物：`GET /api/pages/{pageCode}/exports`、`POST /api/pages/{pageCode}/export`；默认导出当前页面和按导出配置导出两种方式。
- 接入责任：T-AS-5 挂载路由。
- 验收标准：模拟验证：默认导出只含用户当前显示且可见的列，行和顺序与列表相同；角色没有该导出配置时返回 PERMISSION_DENIED；数值为数值单元格（用户 2026-10-30 同意，同旧系统），单元格中是数据库原样的十进制文本，`12345678.12345678`、d_cg 成本单 2566 的每批辅料成本 `1292.385444247787610619469026548672566372` 原样写出，不用科学计数法（Excel 打开后只保留 15 位有效数字，后者显示为 1292.38544424779，与旧系统相同）；真实验证：按旧系统的 cost-pinggu-export 写一份导出配置，在 d_cg 上以管理员导出，主表和两张明细工作表的行、列与旧系统相同；数据量大时分批读取，导出期间其他提交不造成重复或遗漏；用同一批数据从旧系统和新平台各导出 cost-pinggu-export，工作表名、明细块、主从链接、多级表头、字体和列宽一致。
- 状态与证据：进行中（模拟验证通过；2026-10-30 `tests/queries` 的真实验证在 d_cg 上通过；与旧系统的行顺序差别待定，导出期间并发提交未验证）。2026-10-29 实现两种导出（`exports.py`）和 xlsx 写入（`xlsx.py`，标准库 zipfile，没有新依赖），以及 `GET …/exports`、`POST …/export`。版式对照旧系统 `CustomExportService`：perMaster 每张主单一张"明细_<主键>"，块为"【明细】"标题行、表头行、数据行，块之间空一行；主表的链接列链接到明细工作表、明细的标题行和链接列链接回主表的行，链接列按旧系统 resolveLinkColumnIndex 推断（cost-pinggu-export 推断到 "Summary ID"）；列宽按 UTF-8 字节数；表头一行、`/` 原样保留、不加粗（与 C06 第 9 节的"多级表头""加粗"冲突，按旧系统做，见契约缺口第 4 项）。读取在只读事务中（Oracle `SET TRANSACTION READ ONLY`）按批（`yield_per`）进行。模拟验证：`test_exports.py` 9 个、`test_router.py` 中 1 个通过。真实验证（未运行）：`test_cost_pinggu_export_on_d_cg`（配置 `tests/queries/data/cost-pinggu-export.json`，旧配置的 SQL 去掉 d_cg 没有的 `DELETED = 0`）、`test_number_text_cell_on_d_cg`、`test_default_export_matches_list_on_d_cg`。没做：导出期间并发提交的验证（上线后再补）；用 Excel 打开文件、与旧系统同一批数据的导出逐项对比（需要旧系统和 Excel，由联调或人工完成）。
  - 2026-10-30（QE 组，`batch6/export-numbers`，输出在 `.reports/batch6-20261030/qe-export-numbers/`）：按用户同意的"平台导出把数值写成数值单元格（旧系统是数值，Excel 里能直接求和；现在是文本）"改两种导出（QE-06，C06 v21 第 9 节，C09 v13 第 4 节）。依据旧系统 `CustomExportService.normalizeCellValue`（第 1264 行起）：日期时间、CLOB 转成文本，其余原样交给 EasyExcel。`xlsx.py` 的单元格值增加 Decimal，写成 `<c r="O2"><v>1292.385444247787610619469026548672566372</v></c>`（不带 `t`，`<v>` 为 `format_decimal` 的十进制文本）；`exports.py` 中导出 SQL 的数值（含整数）和默认导出中数值字段的值原样交给 xlsx，日期时间、是非、文本不变；列宽、链接列推断仍按单元格的文本，结果不变。真实验证的导出配置改为读 seed `export.cost-pinggu-export.json` 的 `content`，删除与它相同的 `tests/queries/data/cost-pinggu-export.json`；`test_number_text_cell_on_d_cg` 改名 `test_number_cell_on_d_cg`。模拟验证：`uv run --with <rules-core wheel> pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/queries`，78 个通过、0 个失败（`test_exports.py` 中数值单元格的 XML 原文、列宽、主表和明细的单元格类型）。真实验证：同一命令改用 `-m "oracle or redis"`，13 个在 d_cg 上通过、0 个失败（`test_cost_pinggu_export_on_d_cg` 核对 2566 的每批辅料成本 `<v>` 与数据库相同）。与旧系统期望逐格比较：后端 8092（worktree 代码，d_cg）以 admin 按 cost-pinggu-export 导出 2550、2551、2566（scope current，集合筛选 DOCID）。工作表名、行列、单元格类型、值、链接、样式、列宽，在行顺序相同时与按旧代码推出的期望全部一致；417 个数值单元格中有 8 个双精度末位不同，原因是期望文件由 openpyxl 写出，只有 16 位有效数字，Excel 显示相同（`比较-期望(平台行序)vs平台8092按配置.txt`）。行顺序与旧系统不同：配置 SQL 没有 ORDER BY，请求的排序字段 DOCID 不是导出列，旧系统和平台都不加排序。旧系统把 `WHERE EXISTS` 直接拼进 SQL，在 d_cg 上按 2550、2551、2566 返回（`q06-旧系统SQL的行顺序.out.txt`）；平台把 SQL 包成带 ROWNUM 的子查询，按表的扫描顺序返回 2566、2550、2551，包材块内的行序也不同（`比较-期望vs平台8092按配置.txt`）。这个差别没有改，待定。默认导出（`8092-page-export-3docs.xlsx`）中单据号、每批物料成本、每批辅料成本为数值单元格，产品名称为文本。没有用 Excel 打开文件核对显示。

### T-QE-4 对比、Lookup 过滤与明细条件

- 归属与目标：实现 QE-10–QE-12。
- 前置输入：开始前 T-QE-1、T-QE-2。
- 负责范围：queries 的对比、Lookup 过滤和高级查询中的明细条件。
- 交付物：上述功能。
- 接入责任：T-AS-5 联调。
- 验收标准：业务例子 E29、E30；模拟验证：对比值为 0 时不给百分比；Lookup 的 `filter.column` 不是 Lookup 的列时返回 422；`keywordColumns` 为空的 Lookup 用只有空白的关键字和 `filter` 查询时，照常按 `filter` 过滤并分页（QE-09）；真实验证：在 d_cg 上 E30 查出的成本单与旧系统同样条件查出的相同。
- 状态与证据：进行中（模拟验证通过，真实验证已写好、待合并后运行）。2026-10-29 实现对比（`compare.py`，对照旧系统 `DynamicDataService.mergeHistoryData/processDynamicQueryCompare/calculateAndSetDiff`，改为十进制计算）、Lookup 过滤和高级查询的明细 EXISTS（`sql.advanced_sql`，对照旧系统 `buildQueryWhereClause`）。模拟验证：E29（`test_compare.py` 4 个）、E30 和明细条件（`test_lists.py` 中 2 个）、Lookup 过滤（`test_lookups.py` 中 3 个）通过。真实验证（未运行）：`test_e30_on_d_cg`，与旧系统同样写法的 EXISTS 查询比较（d_cg 中物料 115 且单价大于 3 的成本单 291 张，`02-d_cg业务表.out.txt`）。
