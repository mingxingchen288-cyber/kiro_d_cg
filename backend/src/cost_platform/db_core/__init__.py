"""Oracle 连接、事务和十进制读写（docs/模块/db-core.md）

- `engine`：连接池、`OracleUnitOfWorkFactory`（UnitOfWorkFactory）、数值读成 Decimal（DB-01）、错误映射（DB-02）；
- `schema`：`OracleSchemaInspector`（SchemaInspector）；
- `legacy`：`OracleLegacyConnectionFactory`（ConnectionFactory，只读读取 cmx）；
- `copy_tables` 与 `business_tables.json`：复制业务表（DB-03）；`migrate`：平台表迁移（DB-04）。
"""
