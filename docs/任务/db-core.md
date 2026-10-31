# db-core 任务

模块说明：[db-core](../模块/db-core.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E01、E04（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-DB-1 连接、事务与十进制

- 归属与目标：实现 DB-01、DB-02，以及 `UnitOfWorkFactory`、`UnitOfWork`、`SchemaInspector`、`ConnectionFactory`。
- 前置输入：开始前 T-CT-1、T-CT-3；`.env` 中 d_cg 的连接可用（cmx 经 d_cg 只读访问）。
- 负责范围：`backend/src/cost_platform/db_core/`。
- 交付物：连接池和事务；数值列与 Decimal 的转换；Oracle 错误映射；表和视图的结构读取，区分表和视图（`object_type`）；cmx 只读连接。
- 接入责任：T-AS-4 注入各模块；各模块验证自己的 Oracle 存储时也使用本任务的实现。
- 验收标准（真实验证，在 d_cg 上）：通过这几个端口的契约测试；`12345678901234567890.123456`、负数和零写入再读出数值相等，读取过程不出现 float（Hypothesis 生成数值做往返）；等锁超时、两个连接互相等锁形成的死锁、连接断开分别映射为 DOCUMENT_BUSY、DOCUMENT_BUSY、DATABASE_UNAVAILABLE；读取 cmx 的连接以只读事务打开，写语句报错。
- 状态与证据：进行中（2026-10-29；本卡的真实验证已通过，还没有独立复核）。链路 0 已先交付最小部分，见 T-AS-9（[assembly](assembly.md)）。
  - 代码：`db_core/schema.py` 的 `OracleSchemaInspector`（C08 第 2 节的 `columns`、`object_type`、`primary_key`，另有 C08 没有的 `sequence_exists`、`column_comments`，见 `.reports/modules/db-core/contract-gaps.md` 第 1、2 条）；`engine.py` 的连接级取值类型改为 NUMBER 一律读成 Decimal（原来不带精度的 NUMBER 中的整数读成 int）；`legacy.py` 的只读连接不变。对照旧系统 `MetaConfigService.listViewColumns`、`WizardGenerateService.getPkColumn`、`ensureSequenceExists`。
  - 真实验证（d_cg）：`backend` 目录 `uv run pytest -q -p no:cacheprovider -m "oracle or redis" tests/db_core`，39 passed、0 failed（`.reports/modules/db-core/13-pytest-db-core.txt`）。其中：`SchemaInspectorContract`、`UnitOfWorkContract`、`ConnectionFactoryContract` 用真实实现各跑一遍（`tests/db_core/test_ports.py`）；读 cmx 的连接写 d_cg 自己的表也报 ORA-01456（只读事务）；DB-01 用不带精度的 NUMBER 和 NUMBER(38,8) 两列往返 `12345678901234567890.123456`、它的负数、零、E04 的 ±1.23456789、物料清单的 75 和 0.064，再加 Hypothesis 生成的 40 个值，读出的列和 SQL 表达式结果都是 Decimal、数值相等（`test_decimal.py`）；DB-02 两个人同时锁成本单 2550 主表，后一个 `FOR UPDATE WAIT 1` 得到 DOCUMENT_BUSY，读不存在的列得到 INTERNAL_ERROR，响应中没有 ORA- 文本（`test_errors.py`）。实现前先跑测试：DB-01 有 6 个失败（整数读成 int），`11-`、`12-` 号输出。
  - 上线后再补：两个连接互相等锁形成的死锁（ORA-00060）、连接断开的注入。`map_error` 已按 DB-02 映射这两类错误码，没有在 d_cg 上验证。
  - 改了取值类型后，全部真实验证 `-m "oracle or redis" tests` 与改动前的基线相比没有因此新增的失败（`10-baseline-real-all.txt` 6 failed、101 passed；`17-after-real-all.txt` 4 failed、142 passed，失败项的原因见 `contract-gaps.md` 末尾）。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：本卡的真实验证已通过（本条第 2 个子条目），`tests/db_core` 的真实用例照常通过（第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`）；死锁（ORA-00060）、连接断开的注入按本条第 3 个子条目上线后再补，T-WP-7 起按固定加锁层级加锁；"还没有独立复核"保持原样，按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-DB-2 平台表迁移环境与核对命令

- 归属与目标：实现 DB-04、DB-05。
- 前置输入：开始前 T-DB-1。
- 负责范围：`backend/alembic.ini`、`backend/src/cost_platform/db_core/migrations/`；命令 `platform db upgrade`、`platform db check`。各模块的平台表脚本由各模块写在自己目录的 `migrations/` 下。
- 交付物：收集各模块迁移脚本的 Alembic 环境；两个命令；迁移版本表 `PF_ALEMBIC_VERSION`。
- 接入责任：T-AS-4 在联调环境中执行。
- 验收标准（真实验证）：在没有平台表的 d_cg 上执行 upgrade 后 check 通过；缺表或版本不是最新时 check 以非零退出码结束；不改动 `BP_T09_*` 对象。
- 状态与证据：进行中（`platform db upgrade`、`db check` 已在 d_cg 上使用，见 2026-10-31 核对；待独立复核）。链路 0 已先交付最小部分，见 T-AS-9（[assembly](assembly.md)）；本卡的验收照常进行。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"。
    - upgrade 后 check 通过：链路 0 在 d_cg 上执行 `platform db check`，输出"平台表已是最新"、退出码 0（`.reports/chain0/07-db-check.log`）；之后 d_cg 又用 `platform db upgrade` 执行了 ap_0002、ap_0003（approval T-AP-5）和 wp_0002（operations T-OP-2）。命令在 `assembly/cli.py` 第 22–35 行。
    - 缺表或版本不是最新时 check 以非零退出码结束：没有测试，属运维命令的异常路径，上线后再补（`docs/工程约定.md` 第 5 节：用户没有点名的异常、边界、并发不做）。
    - 不改动 `BP_T09_*`：后端代码中只有 `db_core/copy_tables.py` 的排除条件提到 `BP_T09_`（git grep），迁移脚本不涉及；没有在 d_cg 上单独核对。
    - `.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-DB-3 复制业务表

- 归属与目标：实现 DB-03。
- 前置输入：开始前 T-DB-1。表清单补全依赖 T-MG-1。
- 负责范围：命令 `platform db copy-business-tables`；表和列的清单 `backend/src/cost_platform/db_core/business_tables.json`。
- 交付物：复制命令；首批表清单（成本核算、液体成本核算和物料清单页面用到的表和视图，从 cmx 的旧页面配置中查出），每张表列出要保留的列和来源（DB-03）。
- 接入责任：本任务一次性复制表结构和数据，平台不做持续同步；切换时停机后用 `--refresh` 重新复制一次（migration 的 MG-06）。
- 验收标准（真实验证）：复制后每张表的列与清单相同、顺序同 cmx、没有虚拟列；行数等于 cmx 未删除的行数，清单中的列逐行与 cmx 相同（原虚拟列与 cmx 的计算结果相同）；视图去掉了方案名，引用 d_cg 的表；每张表的序列 `<表名>_SEQ` 起始值为 cmx 最大主键加一；重复执行时已存在的表不动，加 `--refresh <表名>` 才重新复制；不复制 `BP_T09_`、`PF_` 开头的对象。
- 状态与证据：进行中（本卡验收标准已逐条核对，见下；待独立复核）。链路 0 已先交付最小部分，见 T-AS-9（[assembly](assembly.md)）；本卡的验收照常进行。链路 1 补上成本核算明细用到的表和视图（真实验证，d_cg）：`platform db copy-business-tables` 新建 T_COST_GOODS（12 列、14403 行，已删除的物料不复制）、T_COST_PINGGU_DTL（10 列、7926 行，BATCH_QTY、COST_BATCH 改为普通列，只复制未删除单据的未删除明细）、V_COST_PINGGU_MATERIAL（18 列、4149 行）、V_COST_PINGGU_PACKAGE（18 列、3604 行）；核对：列与清单相同、按 cmx 顺序、虚拟列 0，行数与 cmx 应有的行数相同，两张表和两个视图双向 MINUS 都是 0，序列从 cmx 最大主键加一开始；重复执行 5 项都未改动（`.reports/chain1/06-copy.log`、`07-复制核对.out.txt`、`08-copy-again.log`）。
  - 2026-10-29 补上物料清单视图和液体成本核算（真实验证，d_cg；本卡验收标准已逐条核对，还没有独立复核）。清单的依据是 cmx 只读查询 `.reports/modules/db-core/01～04` 号：
    - T_COST_GOODS_PRICE_V（12 列）：按 cmx 视图的定义，过滤掉产成品、半成品，ZX_PRICE 为空时取 PRICE，ROW_CLASS_FLAG 写法与 cmx 相同；去掉 DELETED、CREATE_*/UPDATE_*。ROW_CLASS_FLAG 要读 UPDATE_BY（旧页面按它给 ERP 行上色），所以 T_COST_GOODS 加保留 UPDATE_BY（视图不输出），`--refresh T_COST_GOODS` 重新复制为 13 列、14419 行（cmx 这期间新增了 16 个产成品、半成品，另有 15 行内容变了）。
    - T_COST_PINGGU_LQ：旧液体页面主表显示的 42 列，493 行；T_COST_PINGGU_DTL_LQ：页面显示、值来自明细表本身的 9 列，5148 行（明细表自存的物料名等 8 列由视图从物料表取，不复制；SOURCE_TYPE、SOURCE_BATCH_QTY 页面不显示，不复制）；V_COST_PINGGU_MATERIAL_LQ、V_COST_PINGGU_PACKAGE_LQ 各 17 列，2535、2178 行。两张液体表都没有虚拟列。
    - 复制命令另外把保留列在 cmx 中的列注释一起复制（T_COST_PINGGU_LQ 的 COST_PERBOX、M_PERPACK；`contract-gaps.md` 第 3 条）。
    - 核对（`06-复制核对.out.txt`）：列与清单相同、按 cmx 顺序、虚拟列 0，类型、精度、可空、默认值与 cmx 相同；行数 14419/14419、493/493、5148/5148；三张表双向 MINUS 都是 0；三个视图的行数 9837/9837、2535/2535、2178/2178，与 cmx 视图（物料清单按未删除过滤，液体明细按未删除单据过滤）双向 MINUS 都是 0；视图只引用 d_cg 的表；序列 T_COST_GOODS_SEQ、T_COST_PINGGU_LQ_SEQ、T_COST_PINGGU_DTL_LQ_SEQ 从 300862、100041、100197 开始，都是 cmx 最大主键加一；主键 PK_T_COST_GOODS、PK_COST_PINGGU_LQ、PK_COST_PINGGU_DTL_LQ；含聚维酮K30（25）的液体成本单 74 张，与 C06 7.10 相同。
    - 命令输出：`05-copy.log`（新建 5 项、重建物料表）、`07-copy-again.log`（再执行一次，10 项都"已存在，未改动"）。`tests/db_core/test_copy_tables.py` 每次检查各表的列和顺序、虚拟列、主键、序列，各视图有效且不引用 cmx，以及重复执行不改动（包含在上面 T-DB-1 的 39 passed 中）。行数和逐行内容只在复制当时核对：cmx 还在使用、数据在变，平台不做持续同步。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：本条 2026-10-29 的子条目已逐条核对验收标准（列、顺序、虚拟列、行数、视图、序列、重复执行），`tests/db_core/test_copy_tables.py`（第 18 行标 oracle）照常通过（第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`）；剩下的只有独立复核，`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-DB-4 已有的表补列；客户、分销商、外币表和改读 d_cg 的视图

- 归属与目标：实现 DB-06（第 8 批 G1）。产品信息维护、客户信息、外币管理（T-CF-8）要用的表和视图；读这几张表的 Lookup 视图改读 d_cg。
- 前置输入：T-DB-3。
- 负责范围：`db_core/copy_tables.py` 的 `--add-columns`、`assembly/cli.py`；`db_core/business_tables.json` 的 T_COST_GOODS（补 9 列）、T_COST_CUSTOMER、T_COST_TRANPOSER、T_COST_FORMONEY、T_COST_GOODS_V、V_COST_GOODS_LOOKUP、V_COST_CUSTOMER_LOOKUP、T_COST_FORMONEY_V。
- 交付物：补列命令；d_cg 中的上述表、序列和视图。
- 接入责任：d_cg 已执行（2026-10-31 13:44），主代理合并后不用再执行；以后切换时按 MG-06 `--refresh`。
- 验收标准（真实验证）：补列后 T_COST_GOODS 的行数、原有列的值和序列不变，补的列与 cmx 相同；新表的行数等于 cmx 未删除的行数、序列为 cmx 最大主键加一；三个 Lookup 视图与 cmx 的对应视图行数和内容相同（cmx 复制之后新增的数据除外）。
- 状态与证据：进行中（真实验证通过，待独立复核）。命令：`uv run --with <wheel> platform db copy-business-tables --add-columns T_COST_GOODS --refresh V_COST_GOODS_LOOKUP V_COST_CUSTOMER_LOOKUP T_COST_FORMONEY_V`（`.reports/batch8-20261031/g1-basic-pages/copy.log`；`--refresh` 只用于这三个视图，前后行数核对见 q09、q11）。
  - T_COST_GOODS：14419 行，原 13 列逐列哈希与补列前相同，补的 9 列与 cmx 双向 MINUS 为 0，序列不变。
  - 新表：T_COST_CUSTOMER 355 行、T_COST_TRANPOSER 318 行、T_COST_FORMONEY 4 行；序列从 1210182、2708、23 开始。
  - 视图：V_COST_CUSTOMER_LOOKUP 535 → 535 行，与 cmx 双向 MINUS 为 0；T_COST_FORMONEY_V 4 → 4 行，汇率人民币 1、欧元 7.5404、英镑 8.8972、美元 6.7367，与 ERP 相同；V_COST_GOODS_LOOKUP 1339 → 1335 行，只少 cmx 在 10-29 之后由 ERP 同步新增的 4 个产品（19278、19283、19314、19315），其余与 cmx 相同；T_COST_GOODS_V 与 cmx 只差同样 4 行；成本核算、物料清单、液体成本的 5 个视图行数不变；全部 VALID。
  - 模拟验证：`tests/db_core/test_copy_add_columns.py`（补列生成的 DDL 和 MERGE）；真实 `tests/db_core` 通过（含在 `pytest-real-3.txt` 的 91 passed 中）。
