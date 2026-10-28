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
- DB-03：`platform db copy-business-tables` 从 cmx 一次性复制业务表到 d_cg，平台不做持续同步，不原样照搬（用户 2026-10-28："页面不显示的列不要，虚拟列要改成实体列"）：
  - 每张表只复制 `db_core/business_tables.json` 列出的列，按 cmx 的列顺序：旧页面显示的列，加上用户点名保留的列；清单写明来源。
  - 虚拟列复制为普通列，值为复制时 cmx 算出的当前值；之后由平台的计算规则维护。
  - 页面不显示的软删除标记 `DELETED` 不复制，已删除（`DELETED=1`）的行也不复制：旧页面只显示未删除的行，新平台的删除是物理删除（WP-06）。
  - 去掉方案名；补上保留列的默认值和主键；为每张表建序列 `<表名>_SEQ`，起始值为 cmx 中最大主键加一（含已删除的行，不重用旧主键）；不复制名称以 `BP_T09_` 或 `PF_` 开头的对象；可以重复执行。
- DB-04：`platform db upgrade` 用 Alembic 执行各模块的平台表迁移脚本；`platform db check` 核对平台表是否齐全、迁移是否为最新版本，不一致时以非零退出码结束。
- DB-05：不修改 d_cg 中已有的 `BP_T09_*` 对象；cmx 只读。

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
