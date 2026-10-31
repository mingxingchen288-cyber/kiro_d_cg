# db-core

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：Oracle 连接池和 `UnitOfWork`（SQLAlchemy Core 加 python-oracledb）；数值列与 `Decimal` 互转；Oracle 错误映射；`SchemaInspector`；只读连接 cmx 的 `ConnectionFactory`；Alembic 迁移环境；命令 `platform db`（建平台表、从 cmx 复制业务表、核对表结构）。
- 不负责：各模块的平台表结构，由各模块在自己的目录中写迁移脚本；业务表的读写逻辑（write-pipeline、queries-export）。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `backend/src/cost_platform/db_core/`、`backend/alembic.ini` |
| 数据 | d_cg 中从 cmx 复制来的业务表和序列的结构 |
| 配置 | `.env` 中的 `PLATFORM_DB_*`；读取 cmx 也用 d_cg 账号，在只读事务中以 `CMX.表名` 访问，不另设账号 |

## 3. 对外契约

提供 `UnitOfWorkFactory`、`UnitOfWork`、`SchemaInspector`、`ConnectionFactory`（[C08](../契约/C08-后端端口.md) 第 2 节）。

- DB-01：数值列读出为 `Decimal`，写入时也用 `Decimal`，全程不经过浮点；超出浮点精确范围的值（例如 `12345678901234567890.123456`）读写往返后数值相等。
- DB-02：等锁超时和死锁（ORA-00060）映射为 DOCUMENT_BUSY，连接断开或数据库不可用映射为 DATABASE_UNAVAILABLE，其余为 INTERNAL_ERROR（[C03](../契约/C03-错误.md)）；错误响应中不出现 `ORA-` 文本。
- DB-03：`platform db copy-business-tables` 从 cmx 一次性复制业务表和页面用到的视图到 d_cg，平台不做持续同步，不原样照搬（用户 2026-10-28："页面不显示的列不要，虚拟列要改成实体列"）：
  - 每张表只复制 `db_core/business_tables.json` 列出的列，按 cmx 的列顺序：旧页面显示的列，加上用户点名保留的列；清单写明来源。
  - 虚拟列复制为普通列，值为复制时 cmx 算出的当前值；之后由平台的计算规则维护。
  - 页面不显示的软删除标记 `DELETED` 不复制，已删除（`DELETED=1`）的行也不复制：旧页面只显示未删除的行，新平台的删除是物理删除（WP-06）。
  - 明细表在清单中写 `parent`（主表名和关联列），只复制主表中未删除的行的明细：已删除单据的明细不复制。
  - 去掉方案名；补上保留列的默认值和主键（cmx 中主键约束是系统生成的 `SYS_` 名称时改名为 `PK_<表名>`）；为每张表建序列 `<表名>_SEQ`，起始值为 cmx 中最大主键加一（含已删除的行，不重用旧主键）；不复制名称以 `BP_T09_` 或 `PF_` 开头的对象；可以重复执行，已存在的表和视图不动，`--refresh <名称>` 才重建。
  - 视图：清单中登记为 `"kind": "view"` 的项，写明来源视图和 d_cg 版本的 SQL（去掉方案名、引用 d_cg 的表、去掉不复制的列和 `DELETED` 条件），写在它引用的表之后，按这条 SQL 建视图。例如成本核算的两个明细视图 V_COST_PINGGU_MATERIAL、V_COST_PINGGU_PACKAGE 从 d_cg 的 T_COST_PINGGU_DTL 和 T_COST_GOODS 取数。核对：d_cg 视图查出的行与 cmx 视图（按未删除单据过滤）逐行相同。
  - 例外：清单中标 `"readsCmx": true` 的视图读 cmx 的视图，`reason` 写明 d_cg 的表为什么做不出来（2026-10-30 起）：人员 Lookup 的 V_COST_USER（只留工号、姓名）；T_COST_FORMONEY_V 的 ERP 部分（外币和汇率只能经 cmx 的 ERP 数据库链接读，d_cg 没有数据库链接；本地部分读 d_cg 的外币表，DB-06）。与"由BOM生成明细"的 SQL 直接读 `CMX.T_COST_BOM_GOODS_TREE_V` 相同，数据随 cmx 变化，只读，不经链接写入。产品 Lookup V_COST_GOODS_LOOKUP、客户 Lookup V_COST_CUSTOMER_LOOKUP 原来也直接读 cmx，2026-10-31 起改读 d_cg（DB-06）。
- DB-04：`platform db upgrade` 用 Alembic 执行各模块的平台表迁移脚本；`platform db check` 核对平台表是否齐全、迁移是否为最新版本，不一致时以非零退出码结束。
- DB-05：不修改 d_cg 中已有的 `BP_T09_*` 对象；cmx 只读。
- DB-06：已在 d_cg 维护、不能删表重建的表，要多用几列时用 `platform db copy-business-tables --add-columns <表名>`（第 8 批 G1，2026-10-31）：清单里有、表中没有的列，按 cmx 的类型、长度、精度和默认值补上（`ALTER TABLE … ADD`），再按主键从 cmx 取这些列的值（`MERGE`，只更新 d_cg 和 cmx 都有的行，d_cg 自己新增的行为列默认值或空），补上的列复制 cmx 的列注释；已有的列、行和序列不动，补上的列排在原有列之后。同一张表不能同时 `--refresh`。例如 T_COST_GOODS：物料清单在 d_cg 改过单价，产品信息维护和产品 Lookup 要用 GOODSNO、ZX_PL、ZX_MINIMUM、APPROVEDOCNO、BASEUNITQTY、ZX_CUSTOMERID、HOLDERSNAME、TRANPOSID、CREATE_BY，补这 9 列后原 13 列逐列哈希与补列前相同，补的 9 列与 cmx 双向 MINUS 为 0（`.reports/batch8-20261031/g1-basic-pages/q09`、`q11`）。同批的清单改动：
  - 新表 T_COST_CUSTOMER（客户，355 行）、T_COST_TRANPOSER（分销商，318 行，不按客户过滤：产品视图按 TRANPOSID 关联分销商表，cmx 也一样）、T_COST_FORMONEY（外币，4 行，加上"同步ERP汇率"选行用的 CREATE_BY）；新视图 T_COST_GOODS_V（产品信息维护的读取视图，写法同 cmx，去掉不复制的列和 DELETED 条件）。cmx 的 T_COST_CUSTOMER_V、T_COST_TRANPOSER_V 只过滤 DELETED，不建，实体直接读表。
  - V_COST_CUSTOMER_LOOKUP 改为客户表外连接分销商表；V_COST_GOODS_LOOKUP 改读 T_COST_GOODS_V。BOM 状态 MEMO 不再读 ERP：cmx 的写法中 ERP BOM 表的连接条件含 `ISERP = 1`，ISERP 为 0 时一定没连上，结果只取决于 ISERP（0 为"ERP未搭建BOM"，其余为"ERP已搭建BOM"）。T_COST_FORMONEY_V 以 d_cg 的外币表为主，外连接 `CMX.ERP_FORMONEY_V`，各列本地值为空时取 ERP 的值，写法同 cmx 的 T_COST_FORMONEY_V。
  - 核对（`q11`）：V_COST_CUSTOMER_LOOKUP 535 行，与 cmx 双向 MINUS 为 0；T_COST_FORMONEY_V 4 行，汇率与 ERP 相同；V_COST_GOODS_LOOKUP 1335 行，比 cmx 少 4 个产品（cmx 在 10-29 复制之后由 ERP 同步新增的 19278、19283、19314、19315，d_cg 的物料表没有），其余与 cmx 相同；全部表和视图 VALID。

## 4. 依赖

只依赖契约 C03、C08。

## 5. 内部流程

`UnitOfWork`：从连接池取连接 → 开启事务 → 各模块的存储实现共用这个连接 → 提交或回滚 → 归还连接。

## 6. 接入方式

- assembly 创建连接池、`UnitOfWorkFactory`、`SchemaInspector` 和 `ConnectionFactory`，注入各模块；命令行 `platform db` 由 assembly 转给本模块。
- 真实联调：批次 A。

## 7. 验收边界

- 开始开发的前置条件：contracts 完成；`.env` 中的 d_cg 连接可用。
- 本模块完成：在 d_cg 上验证 DB-01 的往返、DB-02 的错误映射、复制业务表并能重复执行、迁移和核对命令。本模块没有替代实现，直接用真实数据库验证。
- 联调后才能确认：各模块的存储实现共用同一事务时，提交和回滚的范围正确（批次 A、B）。
