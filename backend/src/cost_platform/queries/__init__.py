"""查询、导出和个人配置（docs/模块/queries-export.md）。

- `lists.PageQueries`：列表、按主键取行、单据加载（QE-01–QE-05、QE-10、QE-12）
- `lookups.LookupQueries`、`lookups.DictQueries`：Lookup（QE-09、QE-11）和字典
- `personal.PersonalConfigStore`、`personal.PersonalConfigs`：个人列配置（QE-07，表 PF_PERSONAL_CONFIG）
- `exports.Exports`：导出 xlsx（QE-06）
- `related.OracleRelatedQuery`：`RelatedQuery`（C08 第 9 节、QE-08）
- `documents.OracleDocumentReader`：`DocumentReader`（C08 第 9 节）
- `router.build_router`：C09 第 4 节的接口
- `catalog`：Lookup、字典、导出配置和汇总字段的读取（QueryCatalog；`snapshot_catalog` 按配置快照实现）
- `plugin`：插件 `queries.readers`（RelatedQuery、DocumentReader）和 `queries`（HTTP 接口）
"""
