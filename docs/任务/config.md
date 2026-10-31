# config 任务

模块说明：[config](../模块/config.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E18、E43、E44（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-CF-1 配置模型与保存校验

- 归属与目标：实现 CF-01、CF-07–CF-09 和 `ConfigImporter`。
- 前置输入：开始前 T-CT-1、T-CT-3；C06 经用户确认。验收前 T-DB-1、T-DB-2。
- 负责范围：`backend/src/cost_platform/config/` 的配置校验和存储；表 `PF_CONFIG_ITEM` 的迁移脚本。
- 交付物：C06 第 10 节的全部校验（配置的数据结构使用 contracts 中的 C06 类型，见 contracts 的 CT-02）；配置项的读写。
- 接入责任：frontend-config 经 T-CF-3 的接口使用；migration 经 `ConfigImporter` 使用，T-AS-8 联调。
- 验收标准：模拟验证：C06 的每个样例都能保存；第 10 节每条校验各有一个通过和一个不通过的样例，不通过时什么都不写；通过 `ConfigImporter` 的契约测试，另按 C08 第 4 节验证：本批的项可以引用已有配置和本批的其他项，有一项不通过时整批不写，已有的项不覆盖、列入 `skipped`；同一批中两项类型和编码相同时整批拒绝，明细列出这两项，即使它们与已有配置项相同；错误明细的 `path` 以 `items[序号]` 开头；审批流（2026-10-28 随 C06 v17，只验正向流程）：C06 7.8、7.9、7.10 三个样例在 d_cg 上能保存，SQL 片段按 C06 7.2 包好后交给数据库解析通过；真实验证：在 d_cg 上保存、读取、删除配置项。
- 状态与证据：进行中（2026-10-29；还没有独立复核）。`ConfigImporter` 随迁移暂停，没有做，它的验收条目一并暂停。模拟验证：`backend` 目录 `uv run --with ..\rules-core\dist\python\cost_rules_core-0.1.0-cp313-cp313-win_amd64.whl pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/config`，102 passed、0 failed（`.reports/modules/config/pytest-config.txt`）；第 10 节每条校验的通过、不通过样例在 `tests/config/test_validation.py`（37 条），7.8～7.10 三个审批流样例的 SQL 片段按 7.2 包好后交给数据库（内存 SQLite）解析通过；不通过时什么都不写见 `test_save.py`。C06 正文中引用了不存在的列的几个样例不能保存，见 `.reports/modules/config/contract-gaps.md` 第 10 条。真实验证：`tests/config/test_oracle.py`（d_cg 上保存、读取、删除，三个样例交给 Oracle 解析）已写好，没有运行（等合并后统一升级 PF_ 表；7.8、7.10 还需要 db-core 把 T_COST_GOODS_PRICE_V 和液体成本的表、视图复制到 d_cg）。2026-10-30（丙组，`batch1/summary`）：C06 v18 第 10 节"页面字段的 `aggregate` 只能用于数值字段"在 `validation._page` 实现；seed 的成本核算页（主表 14 个字段、两个明细的 COST_BATCH 求和）经 `tests/config` 的保存用例校验通过（`tests/config` 全部通过，命令同上）。2026-10-30（随 C06 v18，T-OP-3）：保存校验覆盖 `replaceDetails`、`updateRows`（`validation.py` 的 `_replace_details`、`_update_rows`、`_sql_columns`；`catalog.references` 登记两个动作的 `entity`）；SQLite 测试库另挂 CMX 库建 `T_COST_BOM_GOODS_TREE_V`、`PUB_GOODS_V` 两张同名表（`tests/config/support.py`），seed 共 30 项（另加甲组的 3 条规则）；`test_validation.py` 加"SQL 多选了计算字段 BATCH_QTY 被拒"。seed 的两条操作在 d_cg 上通过校验的真实验证见 T-OP-3（`tests/operations/test_sql_actions_oracle.py`，只读，不写配置）。
  - 2026-10-30（H5，分支 batch3/goods-page，提交 a0fe21f，证据 `.reports/batch3-20261030/h5-goods-page/`）：seed 加物料清单页和两个审批流，共 39 项。来源（只读查询 `q01`～`q03`、`q05`、`q06`、`q09`）：旧页面 goods-price-manage（cmx 菜单 83"物料清单及成本"，父 41"基础信息"；表元数据 132 CostGoodsPrice，查询视图 T_COST_GOODS_PRICE_V、写入表 T_COST_GOODS、主键 GOODSID；组件 125、126；页面规则 519 GRID_OPTIONS、520 GRID_STYLE、521 EDITABLE、682 APPROVAL_REQUIRED；列元数据 1426～1433、1861、1884、2082），旧源码 `cost-web/src/v3/composables/meta-v3/usePageRules.ts`（APPROVAL_REQUIRED 作为单元格可编辑规则，ERP 行上 ZX_PRICE 仍可编辑）、`cost-server/.../approval/runtime/ApprovalRequiredFieldPolicy.java`（改了 ERP 行的 ZX_PRICE 必须走审批）、`dynamic/service/DynamicDataService.java`（虚拟列不写）。转换：
    - `entity.COST_GOODS_PRICE`：字段和标题按旧列元数据（GOODSNAME_EN 在视图中有，旧页面没有这一列，不放）；旧 EDITABLE（ISERP≠1 可编辑）加 APPROVAL_REQUIRED 转为 `erpRow`（ISERP，ERP 行 1、本地行 0）、ERP 列（ZX_PRICE 以外的业务列）和 `approvalRequired`（ZX_PRICE，ISERP=1，sourcePages GOODS_PRICE_MANAGE），写法同迁移的 `_erp_pattern` 和 authz 的样例；PRICE 旧为虚拟列、保存时跳过，设为不可编辑；ISERP 旧 EDITABLE=0；ROW_CLASS_FLAG 旧为不显示的虚拟列，只在视图中（`column` 为 null），不显示。序列用 d_cg 的 T_COST_GOODS_SEQ（旧为 SEQ_COST_GOODS，d_cg 没有）。
    - `page.GOODS_PRICE_MANAGE`：单表，标题取旧表名"物料清单及成本"；按钮同旧组件 126（新增、复制、删除、保存列配置，保存是页面级按钮）；`audit` 取旧 AUDIT_ENABLED=0；`grid.sideBar` 取旧 GRID_OPTIONS，旧的 infinite、cacheBlockSize、maxBlocksInCache 是分页加载参数，平台自己分页，不配置。
    - `operation.GOODS_PRICE_MANAGE.save`：可写字段为旧可编辑、非虚拟、非主键和 ERP 标识的列。
    - `rule.R_GOODS_ERP_GREEN`、`R_GOODS_ERP_UPDATED_YELLOW`、`R_GOODS_ERP_PRICE_NULL_RED`：旧 GRID_STYLE 三条，按 ROW_CLASS_FLAG 给整行 #E6FFED、#fff2a8、#f8d7da 底色。
    - `role.技术中心`：旧 T_COST_ROLE_PAGE 角色 101 在 cost-pinggu、goods-price-manage 的按钮、行、列权限（转换同 authz 的样例 `tests/authz/samples.py`）；旧角色的 cost-pinggu-lq、home、project 在平台中没有页面，不放。
    - 测试：`tests/config/support.py` 的部门加 18；按 seed 内容写的期望（条数、页面视图、规则包、ADMIN 内容）随 seed 更新；向导测试改用 GOODS_WIZARD、COST_GOODS_WIZARD 编码。`tests/config` 123 passed，后端 not oracle and not redis 1207 passed。
    - 注意：seed 的 TECH_CUSTOMER_MATERIAL 引用部门 18（d_cg 的技术中心）。在没有这个部门的新库上导入 seed，会因"部门 18 不存在"整批校验失败。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：本条"已写好，没有运行"的真实验证 `tests/config/test_oracle.py`（第 27 行标 oracle，含 `test_seed_config_validates_against_d_cg`）在 d_cg 上通过，第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`。`ConfigImporter` 随migration 暂停（`.kiro/steering/交付方式.md`"先有功能，才谈迁移"），它的验收条目一并暂停。"还没有独立复核"保持原样，按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-CF-2 页面视图与规则包生成

- 归属与目标：实现 CF-03、CF-11。
- 前置输入：开始前 T-CF-1；C05、C07 经用户确认。验收前 T-RC-2。
- 负责范围：config 中页面视图和规则包的生成。
- 交付物：按（页面、角色）生成的页面视图；按业务对象生成的规则包，规则和条件转成 JDM。
- 接入责任：页面视图经配置快照和 C09 供前后端使用；规则包由 rules-core 解释，T-AS-5 联调。
- 验收标准：基于属性的测试：任意实体、页面、角色设置叠加后，可见、可编辑不比上层宽，必填不比上层少，没有 `erpRow` 的实体 ERP 列始终只读；页面视图中内置按钮的 `requiresSelection` 符合 CF-03 的表，业务按钮的取页面配置中的值；C06 第 5 节的两条规则和 7.4、7.5 两个审批流生成的规则包能被 rules-core 编译并通过对应样例。
- 状态与证据：进行中（2026-10-29；还没有独立复核）。模拟验证（命令同 T-CF-1，102 passed）：`tests/config/test_views.py` 的属性测试（300 例）和按钮的 `requiresSelection`；`test_packs.py` 用 rules-core 的真实 wheel：seed 的成本核算配置加计算规则生成的规则包 `load_pack` 后对样例 09（cmx 单据 200726）算出相同结果，C06 第 5 节的计算规则对 E02 算出 1020 和 5.1，界面规则能编译（rules-core 还没有界面规则的求值，T-RC-2），依赖成环时保存被拒绝并列出环上的规则；`test_packs_jdm.py`：JDM 与 `rules-core/fixtures/gen_packs.py` 逐个相同。验收标准中"7.4、7.5 两个审批流生成的规则包"随 C07 v4 不再适用（审批条件是 SQL，不进规则包）。校验、界面规则在规则包中的写法见 contract-gaps 第 4 条。2026-10-30（丙组，`batch1/summary`）：页面视图带出页面字段的 `aggregate`（`views._view_field`、`page_view._view_field`），`tests/config/test_views.py::test_seed_page_view_summary_fields` 通过：seed 成本核算页主表 14 个字段、原辅料和包材的 COST_BATCH 为 `sum`，没有设置的字段在 JSON 中省略。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"待联调"改为"完成"：T-AS-5 联调 `tests/e2e/test_batch_b.py` 通过（第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`）；本条"rules-core 还没有界面规则的求值"已由 T-RC-2 补上（2026-10-30），浏览器 `frontend/tests/e2e/g0-1030.spec.ts:295`"场景 4a 红底"通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。"还没有独立复核"保持原样，按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-CF-3 保存接口、Redis 切换与崩溃恢复

- 归属与目标：实现 CF-02、CF-04、CF-05、CF-10 和 C09 第 3 节的接口；CF-05 中读取快照的部分属于 T-CF-4。
- 前置输入：开始前 T-CF-1、T-CF-2。验收前 T-DB-1、Redis 可用。
- 负责范围：config 的 HTTP 路由、配置代号表 `PF_CONFIG_GENERATION` 的迁移脚本、待生效登记、Redis 写入和原子切换（Lua 脚本）、恢复任务函数、`ADMIN` 角色初始化函数。
- 交付物：上述接口和函数；保存后发布 `config.changed`。
- 接入责任：T-AS-4 挂载路由，在启动时调用初始化，启动恢复任务。
- 验收标准：模拟验证，在每一步之后注入进程退出：Oracle 提交前退出，配置不变，60 秒后登记被删除；提交后、写 Redis 前退出，下一个请求就用上新配置（只为这个请求查一次 Oracle），5 秒内恢复任务补写 Redis 并发布 `config.changed`；Redis 不可用时保存返回 CONFIG_UNAVAILABLE；没有待生效登记时，读取快照不访问 Oracle；两次保存并发时依次执行，代号各加一；真实验证：在 Oracle 和 Redis 上重复以上中断，并确认一批配置项一起切换，读不到新旧混合的版本。
- 状态与证据：进行中（2026-10-29；还没有独立复核）。模拟验证（命令同 T-CF-1）：`tests/config/test_recovery.py` 6 条（E18 的两种恢复路径、提交前退出、Redis 不可用、提交后写 Redis 失败、依次保存），`test_save.py` 8 条，`test_router.py` 4 条（C09 第 3 节接口），`test_cache.py` 内存实现 6 条（按代号切换、不写回已删除的项、整体补写、待生效登记）。并发保存在替代实现上只能依次执行，真实的排队见 `test_oracle.py::test_concurrent_saves_queue_on_generation_row`。真实验证：`test_oracle_redis.py`（d_cg + Redis 上重复各步之后的中断）、`test_cache.py` 的 Redis 用例（Lua 脚本：一批一起切换、不回退）已写好，没有运行（本机没有 Redis；PF_ 表等合并后统一升级）。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：本条"已写好，没有运行"的 `tests/config/test_oracle_redis.py`（第 23 行标 oracle、redis）和 `tests/config/test_cache.py` 的 Redis 用例（第 42 行的 `redis` 参数带 redis 标记）在 d_cg + Redis 上通过，第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`。"还没有独立复核"保持原样，按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-CF-4 配置快照读取

- 归属与目标：实现 CF-06、CF-12 和 `ConfigSnapshotReader`。
- 前置输入：开始前 T-CF-1。验收前 Redis 可用。
- 负责范围：config 中的快照读取和进程内缓存。
- 交付物：`ConfigSnapshotReader`。
- 接入责任：T-AS-4 接入 assembly 的中间件。
- 验收标准：通过契约测试；一次读取只访问 Redis 一次；缺项时回查 Oracle 并补写，回查后仍取不到时按 C08 第 4 节报错（页面不存在 404、不能访问 403，其他配置项 500，角色已删除 401 SESSION_ROLE_REVOKED），已经取得的快照不受影响；基于属性的测试：保存和读取交替进行时，每次读到的快照都属于同一版本组合，同一快照的内容不变。
- 状态与证据：进行中（2026-10-29；还没有独立复核）。模拟验证（命令同 T-CF-1）：`tests/config/test_snapshot.py` 20 条，含 `ConfigSnapshotReaderContract` 契约测试（13 条，真实的保存流程 + 内存 Redis）、一次读取只访问 Redis 一次且不访问 Oracle、Redis 清空时回查并补写、Redis 不可用时直接查 Oracle、CF-12 菜单过滤、保存和读取交替的属性测试（两个进程，快照都属于同一版本组合）。真实验证：`test_oracle.py::TestOracleConfigReader`（d_cg 上跑同一套契约测试）、`test_oracle_redis.py::test_read_is_one_redis_round_trip`（统计 Redis 命令数）已写好，没有运行。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：`tests/config/test_oracle.py::TestOracleConfigReader`、`tests/config/test_oracle_redis.py::test_read_is_one_redis_round_trip` 通过，第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`。"还没有独立复核"保持原样，按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-CF-5 启动预热

- 归属与目标：实现 CF-13。
- 前置输入：开始前 T-CF-3、T-CF-4。验收前 T-DB-1、T-RC-2、Redis 可用。
- 负责范围：config 中的 `warm_up()` 和 `ready` 状态。
- 交付物：预热函数；`ready` 状态供 assembly 的 `/health` 和中间件读取。
- 接入责任：T-AS-2 在启动流程中调用（用替代实现），T-AS-4 接入真实实现联调。
- 验收标准：模拟验证：预热后，每个角色的第一个请求不再回查 Oracle，也不再编译规则包；Redis 中已有更新的版本时不被覆盖；有规则包编译失败时启动失败；Redis 不可用时 `ready` 为 false，恢复后自动完成；真实验证：用迁移后的配置在 d_cg 和 Redis 上预热，记录角色数、规则包数和耗时。
- 状态与证据：进行中（2026-10-29；还没有独立复核）。模拟验证（命令同 T-CF-1）：`tests/config/test_warmup.py` 5 条，覆盖验收标准的四项，另有 Oracle 不可用时启动失败。真实验证：`test_oracle_redis.py::test_warm_up_on_d_cg_and_redis` 已写好，没有运行；迁移暂停，先用 d_cg 中已有的配置预热。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：`tests/config/test_oracle_redis.py::test_warm_up_on_d_cg_and_redis` 通过，第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`。"还没有独立复核"保持原样，按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-CF-6 新建页面向导

- 归属与目标：实现 CF-14。
- 前置输入：开始前 T-CF-1、T-CF-3。验收前 T-DB-1。
- 负责范围：config 的向导接口。
- 交付物：C09 第 3 节的两个向导接口。
- 接入责任：frontend-config 使用（T-AS-7）。
- 验收标准：模拟验证：生成的实体、页面、保存操作、菜单和权限都通过 C06 第 10 节的校验；页面的 `audit`、`detailMode` 与请求相同；页面的 `saveOperation` 引用生成的保存操作，保存操作的 `kind`、`propagation` 符合 CF-14，`writableFields` 逐项符合 CF-14：不含计算字段和系统字段（`role` 不是 `input`）、只在视图中的字段、实体或页面设为不可编辑的字段、主键、主从关联字段、`erpRow.column` 和不可写的 ERP 列；在写入任一项时注入失败，什么都不写；要新建的实体、页面或保存操作已存在，或菜单、ADMIN 角色中已有这个页面时，返回 422 且什么都不写；菜单和 ADMIN 角色中原有的内容不变。真实验证：用 `T_COST_GOODS_PRICE_V` 和 `T_COST_GOODS` 生成物料清单页，生成的字段与视图列一致，视图独有的列为只读；序列不存在的表返回 422 且什么都不写；配置代号只加一。
- 状态与证据：进行中（2026-10-29；还没有独立复核）。模拟验证（命令同 T-CF-1）：`tests/config/test_wizard.py` 5 条（读结构、单表页、主从页、已存在时 422 且什么都不写、序列不存在时 422 且什么都不写），生成的各项经保存流程按 C06 第 10 节校验后写入，代号只加一。"在写入任一项时注入失败"上线后再补（写入在同一个事务中，校验失败和序列不存在的回滚已验证）。生成请求中实体的写法和响应体见 contract-gaps 第 6 条。真实验证：`test_oracle.py::test_wizard_on_d_cg` 已写好，没有运行（需要 d_cg 中有 T_COST_GOODS_PRICE_V）。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"。
    - 真实验证：`tests/config/test_oracle.py::test_wizard_on_d_cg` 在 d_cg 上通过（`T_COST_GOODS_PRICE_V` 已由 T-DB-3 建好），第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`。
    - "在写入任一项时注入失败"：上线后再补（`docs/工程约定.md` 第 5 节：用户没有点名的异常、边界、并发不做）。
    - 甲核对第四节 B14（向导导入列时标题不取列注释）、B15（向导不能按关键字列出表和视图）：未做，排在第 8 批。
    - 2026-10-31 第 8 批 G5（`batch8/config-caps`）：B14、B15 已做，见 T-CF-13（CF-20）、T-FC-5、T-DB-5。
    - "还没有独立复核"保持原样，按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-CF-7 成本核算币种 Lookup 带出汇率、状态改为字典下拉

- 归属与目标：盘点（`.reports/inventory-20261030/乙-旧系统功能对照.md` 第 2.3、2.4 节），用户 2026-10-30 回复"其它无异议"同意按旧系统补。只改配置（C06 v21 已有的 `lookup`、`dictType` 写法），另把币种视图加进 db-core 的复制清单。来源：cmx `T_COST_LOOKUP_CONFIG` 的 `formoney`（数据源 `T_COST_FORMONEY_V`，显示列 FMID、FMNAME、FMSIGN、FMRATE）、旧列配置 FMNAME 的回填映射（FMNAME、FMRATE）、USESTATUS 的 `agSelectCellEditor` 5 个值。
- 负责范围：seed `lookup.formoney.json`（列带旧系统的显示标题和宽度）、`dict.COST_PINGGU.USESTATUS.json`、`page.COST_PINGGU.json`（FMNAME 的 lookup、USESTATUS 的 dictType）、`entity.COST_PINGGU.json`（去掉 FMNAME 的不可编辑）、`operation.COST_PINGGU.save.json`（可写字段加 FMNAME）；`db_core/business_tables.json` 加 `T_COST_FORMONEY_V`（读 cmx 同名视图，汇率经 ERP 数据库链接取出）。
- 交付物：成本核算主表双击"币种"打开币种选择，选中后带出汇率；"状态"为 5 个值的下拉。
- 验收标准：业务例子（浏览器、d_cg，正式用例 `frontend/tests/e2e/cost-config.spec.ts`）：测试成本单选"欧元"，汇率等于运行时从 `T_COST_FORMONEY_V` 读出的欧元汇率，保存后重读一致；状态下拉按旧系统顺序列出 5 个值，选"已立项"保存后重读一致。
- 状态与证据：进行中（模拟验证和浏览器业务例子通过，待独立复核）。2026-10-31 第 7 批 CF 组，提交 fd1f3b1（`batch7/cost-config`），报告 `.reports/batch7-20261030/cf-cost-config/报告.md`。合并后主代理执行 `platform db copy-business-tables`，只新建了 `T_COST_FORMONEY_V`（4 列、4 行，其余对象"已存在，未改动"，`.reports/batch7-20261030/merge/copy-business-tables.txt`），再经配置接口写进 d_cg（`save_config.out.txt`）；整套端到端 42 passed，其中本卡 2 条（`e2e-6.txt`）。
  - d_cg 现有 700 张成本单中 256 张的状态不在这 5 个值里（自主 125、委托研发 43、委托转移 40、"0" 24 等，另有 21 张为空，cmx 分布相同，是旧数据本来就有的）：照常显示原值，打开下拉时列表里没有它们的原值，选了才会改；保存不按字典校验。

### T-CF-8 产品信息维护、客户信息（含分销商）、外币管理三个页面

- 归属与目标：实现 CF-15（第 8 批 G1）。来源：盘点乙第 1、2 节的旧页面 goods-manage、customer-manage、formoney-manage；用户 2026-10-30 对"外币管理（含同步ERP汇率）"回复"要"，2026-10-31 回复"开始"。只做配置，配置做不到的另立 T-CF-9、T-DB-4、T-OP-5。
- 前置输入：T-DB-4（d_cg 的表、序列和视图）；T-CF-9（`createdByColumn`、有 `readView` 时只锁表）。
- 负责范围：seed 新增 17 条：`entity.COST_GOODS`、`entity.COST_CUSTOMER`、`entity.COST_TRANPOSER`、`entity.COST_FORMONEY`，`page.GOODS_MANAGE`、`page.CUSTOMER_MANAGE`、`page.FORMONEY_MANAGE`，`operation.GOODS_MANAGE.save`、`operation.CUSTOMER_MANAGE.save`、`operation.FORMONEY_MANAGE.save`、`operation.FORMONEY_MANAGE.syncErpRate`（T-OP-5），`rule.R_GOODS_MANAGE_ERP_GREEN/READONLY`、`rule.R_CUSTOMER_ERP_GREEN/READONLY`、`rule.R_TRANPOSER_ERP_GREEN/READONLY`；`role.ADMIN` 加三个页面 `["*"]`。
- 交付物：三个页面由通用页面按页面编码打开（`/page/GOODS_MANAGE`、`/page/CUSTOMER_MANAGE`、`/page/FORMONEY_MANAGE`）。菜单项由主代理加在"基础信息"（`basic`）下：产品信息维护（排序 2，`mdi:package-variant`）、客户信息（3，`mdi:account-box`）、外币管理（10，`mdi:currency-usd`）。
- 接入责任：主代理合并后执行 `.reports/batch8-20261031/g1-basic-pages/save_g1_config.py after-merge`（经 8080 写外币管理的 4 项、把产品实体换成带 `createdByColumn` 的内容、ADMIN 加外币管理），再加菜单项。
- 验收标准：业务例子（浏览器、d_cg，`frontend/tests/e2e/basic-pages-1031.spec.ts` 第一个用例）：客户信息新增客户和一个分销商；产品信息维护新增产品，客户 ID 经客户 Lookup 选这个客户，带出客户名称、国家、分销商；保存后华益代码为 `OV` 加产品ID、创建人为 admin；成本核算的客户选择、产品选择能选到它们（产品的 BOM 状态为"ERP未搭建BOM"）；ERP 产品 392、ERP 客户 86 和它的分销商整行绿底、不能改。真实验证：同一流程经真实写入管道在 d_cg 上执行（`tests/operations/test_basic_pages_oracle.py`）。
- 状态与证据：进行中（模拟验证、真实验证、浏览器用例通过；待独立复核）。合并后（2026-10-31，main）主代理运行：浏览器用例全部通过（`.reports/batch8-20261031/merge/e2e-6.txt`，57 passed），后端真实测试 217 passed（`pytest-real-1.txt`）。2026-10-31 第 8 批 G1，分支 `batch8/basic-pages`，报告 `.reports/batch8-20261031/g1-basic-pages/报告.md`。
  - 模拟验证：后端 `pytest -m "not oracle and not redis"` 1311 passed（`pytest-all-3.txt`），其中 `tests/config` 的 seed 整体校验、页面视图和规则包生成（新增 3 个页面视图、3 个规则包）、seed 条数 62（原 45 条加本组 17 条）。
  - 真实验证：`tests/operations/test_basic_pages_oracle.py` 2 passed（`pytest-real-basic-2.txt`）：客户和分销商一次保存、改客户名称后两个 Lookup 视图都是新名称、删除客户连同分销商；产品经视图带出客户名称、国家、分销商名称，创建人、修改人为 admin。
  - d_cg：产品信息维护、客户信息的 13 项已在 2026-10-31 13:46 经 8080 保存（`save-now.log`），第三位代理经 8080 只读核对 12 项与 seed 相同，产品实体只差 `createdByColumn`（`check-d_cg-config.log`）。外币管理 4 项没有保存（8080 的代码只锁一行时对读取视图 FOR UPDATE，会落到 ERP 链接上）。

### T-CF-9 实体的创建人列；读取视图可以关联别的表

- 归属与目标：实现 C06 v28 第 2 节的两处改动和 CF-16；write-pipeline 的 WP-03 例外、WP-20 的创建人（第 8 批 G1）。来源：旧系统新增写 CREATE_BY（`DynamicDataService.java` 第 290–293 行）、旧产品信息维护显示"创建人"；旧产品、外币页面的查询视图关联客户、分销商表和 ERP 的外币（`q03-视图定义.out.txt`）。
- 前置输入：T-CF-1、T-WP-2。
- 负责范围：`contracts/types.py` 的 `EntityConfig.created_by_column`；`config/validation.py`（CF-16）；`pipeline/writer.py`（新增时写创建人）、`pipeline/document_store.py` 的 `lock_load`（有 `readView` 时只锁表）；前端 `config/core/types.ts`、配置页"表信息"的"创建人列"（`TableFieldsCard.vue`）。
- 交付物：上述功能。
- 接入责任：主代理合并即可，不改插件清单。
- 验收标准：模拟验证：新增的行同一条 INSERT 写创建人和修改人，修改只写修改人（`tests/pipeline/test_updated_by.py`）；有 `readView` 的实体只锁一行时，先锁表的这一行、再普通读视图（`tests/pipeline/test_document_store_sql.py`）。真实验证：外币管理"同步ERP汇率"的加锁语句都锁 T_COST_FORMONEY，不对经 ERP 链接的视图 FOR UPDATE；物料清单页保存的 SQL 条数（`tests/pipeline/test_oracle_goods_save_sql_count.py`）。
- 状态与证据：进行中（模拟验证、真实验证通过；待独立复核）。合并时（2026-10-31）改为只对关联了别的表的读取视图先锁表、再读视图（write-pipeline 的 T-WP-15），物料清单页保存仍为 7 条，不用再问用户。模拟 1311 passed（`pytest-all-3.txt`）；真实 `tests/db_core`、`tests/pipeline`、`tests/operations/test_sql_actions_oracle.py`、`test_basic_pages_oracle.py` 91 passed（`pytest-real-3.txt`）；`lint-imports` 5 kept。
### T-CF-10 液体成本核算页

- 归属与目标：实现 CF-17：按旧页面 cost-pinggu-lq（物料成本核算表_液体）用配置做出液体成本核算页。来源：盘点 `.reports/inventory-20261030/乙-旧系统功能对照.md` 第 1 节（旧系统有这个页面、新平台没有，物料清单改价审批却会改液体明细单价）、第 4 节（问用户液体页面是否还要），用户 2026-10-30 对第 4 项回复"要"，2026-10-31 回复"开始"。旧配置和源码的出处见 CF-17。
- 前置输入：db-core T-DB-3 已复制的液体表、视图和序列（T_COST_PINGGU_LQ_SEQ、T_COST_PINGGU_DTL_LQ_SEQ，2026-10-31 只读核对都在，不用补）；operations 的 `replaceDetails`（T-OP-3）。
- 负责范围：seed 的 `entity.COST_PINGGU_LQ`、`entity.COST_MATERIAL_LQ`、`entity.COST_PACKAGE_LQ`、`page.COST_PINGGU_LQ`、`operation.COST_PINGGU_LQ.save`、`operation.COST_PINGGU_LQ.generateFromBom`（见 operations 的 T-OP-6）、`rule.R_LQ_*` 17 条、`lookup.costMaterial`，`role.ADMIN`、`role.技术中心` 的 COST_PINGGU_LQ；`tests/config` 的支撑和计数（seed 由 45 项变成 69 项）。不改 config 的代码。
- 交付物：通用页面按页面编码 COST_PINGGU_LQ 打开液体成本核算，列、明细、按钮、规则都来自配置。
- 接入责任：主代理合并后在 `menu.main` 的"成本"分组、"成本核算"之后加菜单项"液体成本核算"（页面编码 COST_PINGGU_LQ，图标 `mdi:calculator-variant`，同旧 T_COST_RESOURCE 124）。
- 验收标准：模拟验证：业务例子 E43；seed 整体校验通过。真实验证（d_cg）：seed 的液体配置在 d_cg 的表结构上校验通过；规则对 d_cg 全部液体单据重算，结果与按旧计算引擎直接算的相同，与库里旧值不同的每一处都说明原因。浏览器：复制液体单据、改原辅料单价，预览和保存后每批成本、主表合计按规则重算，重新打开一致；备注"ERP未搭建BOM"的单据整行红底。
- 状态与证据：进行中（模拟验证、真实验证和浏览器业务例子通过，待独立复核）。2026-10-31 第 8 批 G2，分支 `batch8/liquid-cost`，报告 `.reports/batch8-20261031/g2-liquid-cost/报告.md`。
  - 命令（原始输出都在报告目录）：后端 `backend` 目录 `uv run --with ..\rules-core\dist\python\cost_rules_core-0.1.0-cp313-cp313-win_amd64.whl pytest -q -p no:cacheprovider -m "not oracle and not redis"`；真实 `-m "oracle or redis" tests/config/test_liquid_recompute_oracle.py tests/operations/test_liquid_oracle.py`（加 `--override-ini=log_cli=true --log-cli-level=INFO` 输出分类数字）；浏览器 `frontend` 目录 `pnpm exec playwright test -c <报告目录>\playwright.g2.config.ts tests/e2e/liquid-cost.spec.ts --project e2e`（`run-e2e.ps1`）。
  - 写进 d_cg（经用户的 8080，`save_liquid_config.py`）：24 项新配置都是 version 1；`role.ADMIN` 38 → 39、`role.技术中心` 2 → 3，回读液体的键都在。admin、jishu01 读 COST_PINGGU_LQ 的页面视图 200，chengben01 为 403（成本会计角色在旧系统也没有液体页面）；三人读 COST_PINGGU 都是 200。
  - 模拟验证：`tests/config/test_packs.py::test_seed_liquid_rules_sample_e43`；后端模拟全量 1310 passed（`unit-1.txt`）。
  - 真实验证：`tests/config/test_liquid_recompute_oracle.py` 2 passed（只读，`recompute-5.txt`）。d_cg 493 张液体单据、15342 个计算值：规则包的结果与按旧计算引擎（空值按 0、除以 0 得 0、分支都不匹配时不变）直接算的全部相同。与库里旧系统存下的值相比，11 张单据全部一致；不一致 6511 处，每一处都归了类（`sum_recompute.txt`）：只因用到的字段不同、本条公式没错的 3054；旧过程 P_PINGGU_DTL_COMPUTE_LQ 把包材每批数量按包装规格除 1445；成本核算（固体）的页面公式算的 1153（每批销售额除包装规格、每盒加工费乘 1000 等）；库里为空 691；旧过程 P_PINGGU_COMPUTE_LQ 的合计按明细表自己的分类求和、含两个视图看不到的 435 行明细 108；原辅料每批数量没乘（1 + 额外投料量）27；年销售额少除 100 共 1 处；逐条查过的旧数据 32（2931～2937、2950 主表的批量或合计后来清空或改过，2559 明细单价改过、主表没重算，2556 玉米淀粉每批成本没随每批数量重算，10007～10009 主表没有产品、包材数量手填）。这些单据在新平台保存一次，计算字段就按页面规则整单重算（WP-07）。seed 的液体配置在 d_cg 上校验通过见 `tests/operations/test_liquid_oracle.py` 第一个用例（T-OP-6）。
  - 浏览器（用户的 8080、9527，main 代码加 d_cg 已写的液体配置；配置 `playwright.g2.config.ts`）：`frontend/tests/e2e/liquid-cost.spec.ts` 第一个用例通过（与"由BOM生成明细"共 2 passed，`e2e-1.txt`）：2573 整行红底；复制 2571、改第一行原辅料单价，预览中每批成本等于精确值、主表合计变化，保存后重新打开显示与预览相同，接口读出的主表原料、辅料、包材合计等于明细按分类求和（有原料时除以 1.13）。测试单据结束时经平台删除，d_cg 液体主表 493、明细 5148 行不变（`q15-dcg-residue.out.txt`）。
### T-CF-11 只读页面和审计追踪页的配置

- 归属与目标：实现 CF-18（C06 v29、C05 v10），按旧系统审计追踪页 auditLog 配一个只读通用页。来源：盘点 `.reports/inventory-20261030/乙-旧系统功能对照.md` 第 1 节（审计追踪 auditLog）、第 4 节；用户 2026-10-30 对第 4 节回复"要"、2026-10-31 回复"开始"。旧系统的依据见 CF-18。
- 前置输入：write-pipeline 的 T-WP-13（视图 `PF_AUDIT_LOG_V`，迁移 wp_0003）。
- 负责范围：`contracts/types.py`（`PageConfig.save_operation`、`PageView.save_operation` 可为 null）、`config/validation.py`（实体的 `table` 可以是视图，不要序列）、`config/catalog.py` 和 `contracts/fakes/config.py`（只读页面不引用保存操作）、`config/views.py`、`config/page_view.py`（只读页面不给 `save`）；前端 `contracts/page-view.ts`、`config/core/types.ts`、`page/page-runtime.ts`（只读页面不保存）、`config/views/table-fields.ts`（保存列时只读页面不同步可写字段）；seed `entity.AUDIT_LOG.json`、`page.AUDIT_LOG.json`、`role.ADMIN.json`。
- 交付物：审计追踪页 `/page/AUDIT_LOG`：列为操作用户、操作时间、页面编码、表编码、表名称、记录ID、操作类型、字段编码、字段、修改前、修改后、创建时间（旧视图的 ID 是拼出来的长文本，不显示；旧的"字段变更"一列拆成四列，见 WP-22），可见列都设为高级查询的预置条件（旧列元数据 SEARCHABLE 全为 1），按 ID 升序（同旧页面）；只读，没有保存按钮；只给 ADMIN。菜单由主代理合并后统一加：顶层、最后一个，标题"审计追踪"，页面编码 `AUDIT_LOG`，图标 `mdi:file-document-outline`（旧 `T_COST_RESOURCE` 105，SORT_ORDER 99，无父级）。
- 验收标准：模拟验证：seed 的审计页生成的页面视图 `saveOperation` 为 null、`systemButtons` 只有高级查询、字段都不能编辑；实体的 `table` 为视图时校验通过、不查序列。业务例子（浏览器、d_cg，正式用例 `frontend/tests/e2e/audit-log-1031.spec.ts`）：admin 改测试成本单的备注后，审计追踪按记录ID 查出 INSERT 和 UPDATE 的备注行，字段"备注"、修改前、修改后、操作用户 admin 正确；没有保存按钮、格子不能编辑；chengben01 读这个页面视图为 403。
- 状态与证据：进行中（模拟验证、浏览器用例通过；待独立复核）。合并后主代理按下面的顺序执行了：迁移 wp_0003 已在 d_cg（视图 14:38 已由G3 起本分支后端时的启动迁移建好，`platform db upgrade` 报已是最新），重启 8080，`save_audit_log_config.py` 保存 entity、page，role/ADMIN 加 AUDIT_LOG（`.reports/batch8-20261031/merge/save-audit.log`），加菜单。合并后（2026-10-31，main）主代理运行：浏览器用例全部通过（`.reports/batch8-20261031/merge/e2e-6.txt`，57 passed），后端真实测试 217 passed（`pytest-real-1.txt`）。2026-10-31 第 8 批 G3，分支 `batch8/audit-export`，报告 `.reports/batch8-20261031/g3-audit-export/报告.md`。
  - 模拟验证：`uv run --with <rules-core wheel> pytest -q -p no:cacheprovider -m "not oracle and not redis"` 全部通过（条数见报告），其中 `tests/config/test_views.py::test_read_only_page_audit_log`；config 测试中按编码取成本核算页、seed 条数 45 → 48（本组新增 3 条）；`tests/contracts/test_samples.py` 的 C06 可为 null 的必填字段加 `PageConfig.save_operation`。前端 `pnpm typecheck`、`pnpm test`、`pnpm lint:deps` 通过。
  - 没有在 d_cg 保存：main 的代码校验不过这两种新写法。合并后主代理按顺序执行：`platform db upgrade`（建 `PF_AUDIT_LOG_V`）→ 重启 8080 → `.reports/batch8-20261031/g3-audit-export/save_audit_log_config.py`（保存 entity、page，role/ADMIN 只加 `AUDIT_LOG`）→ 加菜单 → 跑 `audit-log-1031.spec.ts`。
### T-CF-12 页面视图带默认值和对比的显示方式

- 归属与目标：实现 CF-19（盘点 `.reports/inventory-20261030/甲-任务卡核对.md` 第四节 B8、B9；用户 2026-10-31 回复"开始"）。契约 C05 v9。来源：旧系统 `cost-web/src/v3/composables/meta-v3/useWorkingSetStore.ts` 第 543–585 行、`useMetaColumns.ts` 第 166–176、204–219、423–455 行。
- 前置输入：开始前 T-CF-2。
- 负责范围：`contracts/types.py`（`ViewField.default`、`ViewField.compare`、`FieldCompareView`）、`config/views.py`。
- 交付物：页面视图的字段带出实体字段的 `default`，配了 `compare` 时带出 `{"format": ...}`，没有配置时省略。
- 接入责任：frontend-page 的 T-FP-18 使用；合并后主代理经配置接口重新生成页面视图（任何一次保存都会按新代码重新生成）。
- 验收标准：模拟验证：成本核算主表实体的商务人员配 `builtin` 当前用户姓名、状态配 `options`、每批物料成本配对比只显示百分比时，页面视图中这三个字段分别带出相同的 `default` 和 `{"format": "percent"}`，没有配置的字段省略这两项，页面视图能被解析回来。
- 状态与证据：进行中（模拟验证、浏览器用例通过；待独立复核）。合并后（2026-10-31，main）主代理运行：浏览器用例全部通过（`.reports/batch8-20261031/merge/e2e-6.txt`，57 passed），后端真实测试 217 passed（`pytest-real-1.txt`）。2026-10-31 第 8 批 G5，分支 `batch8/config-caps`，报告 `.reports/batch8-20261031/g5-config-caps/报告.md`。模拟验证：`tests/config/test_views.py::test_field_default_and_compare_format`；`pytest -m "not oracle and not redis"` 1316 passed（`pytest.txt`），`lint-imports` 5 kept。seed 的实体都没有配默认值和对比，页面视图不变。浏览器用例见 T-FP-18。

### T-CF-13 新建页面向导取列注释、按关键字搜表和视图；规则去掉数据项

- 归属与目标：实现 CF-20（盘点第四节 B14、B15）和 C06 v27 去掉规则的 `dataItems`（盘点第五节 U3：配置页能配数据项，保存和审批详情计算都不执行；主代理告诉用户"打算把这个入口去掉，而不是去实现它"，用户没有异议）。契约 C06 v27、C08 v21、C09 v16。来源：旧系统 `MetaConfigService.listDbObjects` 第 621–645 行、`listViewColumns`、`useWizardState.ts` 第 103 行；`RuleConfigDialog.vue`（规则没有数据项，`dataItems` 只在审批定义里）。
- 前置输入：开始前 T-CF-6、T-DB-5。
- 负责范围：`config/wizard.py`（`column_labels`、`schema_objects`）、`config/service.py`、`config/router.py`；`contracts/types.py`（`SchemaObjectsRequest`、`SchemaObject`、`SchemaObjectsResponse`，去掉 `DataItem` 和 `RuleConfig.data_items`）、`config/validation.py`、`config/packs.py`、`pipeline/calc.py` 和 `approval/calc.py` 的注释。
- 交付物：`wizard/columns` 的标题取列注释；`POST /api/config/schema/objects`；写了 `dataItems` 的规则保存时拒绝。
- 接入责任：frontend-config 的 T-FC-5 使用。
- 验收标准：模拟验证：液体成本核算主表 T_COST_PINGGU_LQ 导入列时 COST_PERBOX、M_PERPACK 的标题为"每盒成本""每中盒小盒数"，没有注释的列为列名，有视图时取视图的注释；输入"t_cost_goods"列出物料表和物料清单视图、先表后视图；接口返回同样的结果；写了 `dataItems` 的规则保存时拒绝，提示不允许出现 dataItems。真实验证（只读，只查 d_cg 的数据字典）：输入"T_COST_GOODS"列出 T_COST_GOODS（表）、T_COST_GOODS_PRICE_V（视图），名称都含关键字、先表后视图；T_COST_PINGGU_LQ 导入列的主键 DOCID、序列已存在，两列标题为列注释。
- 状态与证据：进行中（模拟验证、只读真实验证和浏览器用例通过；待独立复核）。2026-10-31 第 8 批 G5，分支 `batch8/config-caps`。模拟验证：`tests/config/test_wizard.py` 新增 2 条、`test_router.py::test_wizard_and_schema_endpoints` 加 `schema/objects`、`test_validation.py::test_rule_with_data_items_rejected`；`pytest -m "not oracle and not redis"` 1316 passed。真实验证：`tests/config/test_wizard_schema_oracle.py` 1 条，连同 T-DB-5 的 4 条只读用例 5 passed（`pytest-real-readonly.txt`）；`test_oracle.py::test_wizard_on_d_cg` 会写 d_cg 配置，没有跑。只读核对：d_cg `PF_CONFIG_ITEM` 中含 `dataItems` 的配置 0 行（`01-规则数据项.out.txt`），seed 也没有；审批流的数据项不是这一项，没有动（新平台审批流 C06 第 7 节本来没有数据项字段）。浏览器见 T-FC-5。

### T-CF-14 旧系统的 7 个业务角色迁到 seed 和 d_cg

- 归属与目标：实现 CF-21。依据用户 2026-10-31 原话"角色你迁移过来"。来源：cmx `T_COST_ROLE` 121～127（001、002、003、005、006、007、008）和它们在 `T_COST_ROLE_PAGE` 中的 56 行（只读查询 `.reports/batch9-20261031/a-roles/q02-角色页面内容.out.txt`），旧区域名取 `T_COST_PAGE_COMPONENT`、`T_COST_TABLE_METADATA`（`q06-旧区域名.out.txt`）。转换规则同 seed 的 `role.技术中心.json`（C06 v24 第 8 节），契约不改。
- 前置输入：开始前 T-CF-10（液体成本核算页）、T-CF-11；第 8 批 G1 的产品信息维护、客户信息、外币管理三个页面；导出配置 cost-pinggu-export、goods-price-pgoods-export。
- 负责范围：seed `role.001.json`、`role.002.json`、`role.003.json`、`role.005.json`、`role.006.json`、`role.007.json`、`role.008.json`；`tests/config` 中按 seed 枚举的断言（seed 89 → 96 项，页面视图多 39 份）和 `tests/config/support.py` 物料清单测试实体补 4 个 ERP 列。不改代码。不迁测试角色"普通用户""test11"，不迁账号。
- 交付物：7 个角色在 seed 中、在 d_cg 中；每一项旧权限迁成了什么、没迁的原因见 `.reports/batch9-20261031/a-roles/迁移对照.md`。
- 验收标准：模拟验证：整份 seed 能保存；每个角色读到的菜单与旧系统授给它的页面相同；采购在成本核算、物料清单、外币管理的按钮、列、导出与旧策略一致；7 个角色的行权限与旧系统相同（003 成本核算去掉一条不成立的条件，见 CF-21）。真实验证：经 8080 在 d_cg 新建这 7 个角色，回读内容与 seed 相同；admin、chengben01、jishu01 读成本核算页面视图仍是 200。浏览器（正式用例 `frontend/tests/e2e/roles-1031.spec.ts`）：业务例子 E44。
- 状态与证据：进行中（模拟验证、d_cg 保存和浏览器用例通过，待独立复核）。2026-10-31 第 9 批 A 组，分支 `batch9/roles`，报告 `.reports/batch9-20261031/a-roles/报告.md`。
  - 模拟验证：`tests/config/test_migrated_roles.py`（11 个用例）；`tests/config tests/authz` 189 passed（`pytest-03.txt`）；后端 `uv run --with <rules-core wheel> pytest -q -p no:cacheprovider -m "not oracle and not redis"` 1349 passed、217 deselected（`pytest-全量模拟.txt`）；`uv run lint-imports --no-cache` 5 kept。前端 `pnpm typecheck`、`pnpm test`（603 passed）、`pnpm lint:deps` 通过。
  - 真实验证（d_cg，经用户的 8080，`save_roles.py`，输出 `save_roles.out.txt`）：role/001、002、003、005、006、007、008 新建，版本都是 1，回读与 seed 相同；admin、chengben01、jishu01 读 `GET /api/pages/COST_PINGGU/view` 都是 200。只读核对 `PF_CONFIG_ITEM`：7 个角色的代号 7671～7677，页面视图 39 份（007 三份，其余各六份，`q07-保存后核对.out.txt`）。
  - 浏览器（本组 8091/9541，`run-e2e.ps1`）：`roles-1031.spec.ts` 3 passed（`e2e-2.txt`）：采购登录后菜单、物料清单的按钮和右键导出、成本核算的按钮、列和可编辑；生产登录后菜单。
