# db-core 任务

模块说明：[db-core](../模块/db-core.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E01、E04（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-DB-1 连接、事务与十进制

- 归属与目标：实现 DB-01、DB-02，以及 `UnitOfWorkFactory`、`UnitOfWork`、`SchemaInspector`、`ConnectionFactory`。
- 前置输入：开始前 T-CT-1、T-CT-3；`.env` 中 d_cg 的连接可用（cmx 经 d_cg 只读访问）。
- 负责范围：`backend/src/cost_platform/db_core/`。
- 交付物：连接池和事务；数值列与 Decimal 的转换；Oracle 错误映射；表结构读取；cmx 只读连接。
- 接入责任：T-AS-4 注入各模块；各模块验证自己的 Oracle 存储时也使用本任务的实现。
- 验收标准（真实验证，在 d_cg 上）：通过这几个端口的契约测试；`12345678901234567890.123456`、负数和零写入再读出数值相等，读取过程不出现 float（Hypothesis 生成数值做往返）；等锁超时、连接断开分别映射为 DOCUMENT_BUSY、DATABASE_UNAVAILABLE；读取 cmx 的连接以只读事务打开，写语句报错。
- 状态与证据：未开始。

### T-DB-2 平台表迁移环境与核对命令

- 归属与目标：实现 DB-04、DB-05。
- 前置输入：开始前 T-DB-1。
- 负责范围：`backend/alembic.ini`、`backend/src/cost_platform/db_core/migrations/`；命令 `platform db upgrade`、`platform db check`。各模块的平台表脚本由各模块写在自己目录的 `migrations/` 下。
- 交付物：收集各模块迁移脚本的 Alembic 环境；两个命令；迁移版本表 `PF_ALEMBIC_VERSION`。
- 接入责任：T-AS-4 在联调环境中执行。
- 验收标准（真实验证）：在没有平台表的 d_cg 上执行 upgrade 后 check 通过；缺表或版本不是最新时 check 以非零退出码结束；不改动 `BP_T09_*` 对象。
- 状态与证据：未开始。

### T-DB-3 复制业务表

- 归属与目标：实现 DB-03。
- 前置输入：开始前 T-DB-1。表清单补全依赖 T-MG-1。
- 负责范围：命令 `platform db copy-business-tables`；表清单 `backend/src/cost_platform/db_core/business_tables.txt`。
- 交付物：复制命令；首批表清单（成本核算、液体成本核算和物料清单页面用到的表和视图，从 cmx 的旧页面配置中查出）。
- 接入责任：本任务一次性复制表结构和数据；之后的数据同步由用户的 CDC 负责，不属于平台。
- 验收标准（真实验证）：复制后表结构、行数与 cmx 相同，抽查数据相同；视图去掉了方案名，引用 d_cg 的表；每张表的序列 `<表名>_SEQ` 起始值为最大主键加一；重复执行时已存在的表不动，加 `--refresh <表名>` 才重新复制；不复制 `BP_T09_`、`PF_` 开头的对象。
- 状态与证据：未开始。
