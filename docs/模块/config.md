# config

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：校验并保存配置项，保存即生效；生成页面视图和规则包；提供配置快照；把配置写入 Redis 并原子切换；崩溃恢复；发布配置变更事件；导入迁移生成的配置；提供 [C09 第 3 节](../契约/C09-HTTP接口.md)的接口。
- 不负责：配置编辑界面（frontend-config）；个人列配置（queries-export）；核对表结构的具体实现（db-core 的 `SchemaInspector`）。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `backend/src/cost_platform/config/` |
| 数据 | 表 `PF_CONFIG_GENERATION`（配置代号，只有一行）；表 `PF_CONFIG_ITEM`：每个配置项的类型、编码、名称、当前内容、版本号、保存人、保存时间；生成的页面视图和规则包也存在这里 |
| 状态 | Redis 键 `{ns}:cfg:*`（当前代号、内容、待生效登记）；每个进程按版本缓存的解析结果 |

## 3. 对外契约

提供 `ConfigSnapshotReader`、`ConfigImporter`（[C08](../契约/C08-后端端口.md)），以及 C09 第 3 节的接口。数据格式见 [C05](../契约/C05-页面视图.md)、[C06](../契约/C06-配置模型.md)、[C07](../契约/C07-规则内核接口.md)。

- CF-01：保存一个配置项时，按 C06 第 10 节校验；不通过时返回 422 VALIDATION_FAILED，什么都不写。
- CF-02：校验通过后，在一个 Oracle 事务内写入新内容、版本号加一，并重新生成受影响的页面视图（每个页面、每个角色一份）和规则包（每个业务对象一份）。
- CF-03：页面视图按实体、页面（主表区或明细区、Tab）、角色三层叠加：可见、可编辑只能收紧，必填只能加；没有 `erpRow` 的实体，ERP 列始终只读。内置按钮动作是否要求选中行，由平台统一规定如下，管理员不配置（C06 第 3 节）：

  | 内置动作 | 是否要求选中行 |
  |---|---|
  | `copyRow`（复制行） | 是 |
  | `deleteRow`（删除行） | 是 |
  | `addRow`（新增行） | 否 |
  | `saveGridConfig`（保存列配置） | 否 |

  页面视图中区域按钮的内置动作按此表给出 `requiresSelection`，业务动作的取页面配置中的值。

  按钮按角色过滤（C05 v8、C06 v24 第 8 节）：区域按钮只留角色有 `<区域>:<动作>` 或 `*` 的，新增、删除也一样按区域（`<区域>:addRow`、`<区域>:deleteRow`），`systemButtons` 只有 `save`、`advancedSearch`。区域的 `canModify` 为角色有没有 `<区域>:modify`：没有时为 false，字段的 `editable` 不因此改变（新增、复制出的行仍按 `editable` 填写），前端把这个区域已保存的行整行设为只读。旧代码生成的页面视图（`systemButtons` 带 `addRow`、`deleteRow`，没有 `canModify`）照样能读，下次保存任何配置时按 CF-02 重新生成。

  页面字段的 `aggregate`（汇总行求和，C06 v18 第 3 节）原样带进页面视图的字段（C05 v4），没有设置时省略；保存时只能用于数值字段（C06 第 10 节）。
  不可编辑的字段是本区域可编辑字段的 Lookup 回填目标（`fillBack` 为 true）、有写入列且在 `writableFields` 中时，页面视图的字段标 `fillWritable`（C05 v5），与 authz AZ-04 接受的回填字段相同：例如成本核算主表的产品名称、规格不能直接填写，随产品 Lookup 回填后写库。
  页面字段的 `searchable`（查询，C06 v23 第 3 节）为 true、且三层叠加后字段可见时，页面视图的字段标 `searchable`（C05 v7），否则省略：角色隐藏的字段不会出现在高级查询的预置条件中。
- CF-04：发布状态与生效时点。
  - 表 `PF_CONFIG_GENERATION` 只有一行，记录配置代号。每次保存都把代号加一，配置快照的版本号和 `X-Config-Version` 就是这个代号。
  - 一次保存的状态依次为：待生效（Redis 中已登记待生效标记，Oracle 尚未提交）→ 已生效（Oracle 已提交）→ 已同步（Redis 已切换到新代号）。Oracle 提交的那一刻就是生效时点。
  - 保存步骤：
    1. 按 CF-01 校验。
    2. 开启 Oracle 事务，`SELECT … FOR UPDATE` 锁定代号行，读出当前代号 G-1。多次保存在这里排队，依次执行。
    3. 在 Redis 的待生效哈希 `{ns}:cfg:pending` 中登记 G：本次改动的配置项和登记时间。Redis 不可用时回滚，返回 503 CONFIG_UNAVAILABLE，配置不变。
    4. 写入新内容，代号改为 G，提交。保存事务最长 30 秒，超时回滚。
    5. 用一个 Lua 脚本写入 Redis：新内容、当前代号 G，并删除待生效登记 G。脚本按代号比较，不会把更新的代号改回旧的。
    6. 发布 `config.changed`（[C10](../契约/C10-实时事件.md)）。
  - 第 4 步提交后，即使第 5、6 步失败或进程退出，接口也返回保存成功，因为配置已经生效。没有同步到 Redis 的部分由 CF-05 补齐。
- CF-05：崩溃恢复。
  - 读取配置快照时，同一次 Redis 读取会带出待生效登记。只有登记中的配置项与本次要用的配置项有交集时，才查一次 Oracle 的代号行和这些配置项：
    - Oracle 代号已达到登记的 G：使用 Oracle 中的内容，并按第 5 步补写 Redis、删除登记；
    - Oracle 代号仍小于 G：说明那次保存还没提交，或者已经回滚，继续使用 Redis 中的内容，这时新配置本来就还没生效。
  - 恢复任务在每个进程中每 5 秒运行一次，只读一行代号：
    - Redis 的代号落后于 Oracle 时，按 Oracle 补写 Redis，并发布 `config.changed`；
    - 待生效登记超过 60 秒、而 Oracle 代号仍小于 G 时，那次保存已经回滚（第 4 步有 30 秒上限），删除这条登记。
  - Redis 不可用时，读取配置快照直接查 Oracle，直到 Redis 恢复。
  - 已经取得配置快照的请求和命令，按快照执行到结束，不重新读取权限（[C04](../契约/C04-执行上下文.md)）。
- CF-06：读取配置快照时，一次 Redis 读取得到当前代号、本角色用到的配置项版本和待生效登记；没有待生效登记时，不访问 Oracle。缺项时按 CF-05 的方式回查 Oracle 并补写。同一快照的内容不变，不会读到新旧混合的版本。
- CF-07：审批流的先后由配置中的 `order` 决定，config 不另外分配（C06 7.1）。
- CF-08：两个管理员同时保存同一配置项时，后保存的覆盖先保存的。
- CF-09：仍被其他配置引用的配置项不能删除。
- CF-10：没有 `ADMIN` 角色配置时，启动时创建它（`admin` 为 true，可访问全部配置和管理功能）；已存在时不改。
- CF-11：保存规则时，把每条规则和条件（C06 第 5 节）转成 JDM 编进规则包；可视化条件先转成表达式。审批流的 SQL 片段不进规则包，保存时按 C06 7.2 包好后交给数据库解析（C06 第 10 节）。
- CF-12：配置快照的 `menus()` 只含该角色可以访问的页面。
- CF-13：启动预热 `warm_up()`，由 assembly 在启动时调用，完成前进程不接受业务请求：
  1. 用一条 SQL 从 Oracle 读出全部配置项的当前版本和内容（含生成的页面视图和规则包）。
  2. 把 Redis 中缺少或版本更旧的项补写进去，并按版本原子切换；Redis 中已有更新的版本时不覆盖。
  3. 按角色配置逐个角色生成配置快照，放进进程缓存：该角色的全部页面视图和菜单。
  4. 对每个规则包调用 `RulesEngine.load_pack`，句柄放进进程缓存。
  - 完成条件：每个角色都有快照，每个规则包都已编译。日志记录角色数、规则包数和耗时，之后 `ready` 为 true。
  - Oracle 不可用，或有规则包编译失败时，启动失败，进程以非零退出码结束。Redis 不可用时每 5 秒重试一次，期间 `ready` 保持 false。
  - 每个后端进程各自预热；Redis 补写可以重复执行，不会把新版本改回旧版本。运行中出现新版本时，按 CF-06 按需加载。
- CF-14：新建页面向导（C09 第 3 节）：读取视图和表的结构（经 `SchemaInspector`），按列生成实体字段，表中没有的列生成 `column` 为 null 的只读字段；主键取表的主键；序列 `<表名>_SEQ` 必须已经存在，不存在时返回 422，提示用户自己建立，平台不执行 DDL。向导生成一套能查询、编辑、保存的配置：
  - 实体、页面、页面的保存操作、菜单和 ADMIN 角色的 `*` 权限在同一个 Oracle 事务中写入，配置代号只加一；任一项校验或写入失败时整体回滚，什么都不写。实体、页面、保存操作是新建的配置项，与已有配置项的类型和编码相同时返回 422 VALIDATION_FAILED，不覆盖已有配置。菜单和 ADMIN 角色是已有的配置项，向导只在其中追加：在 `parentMenu` 下加入新页面的菜单项，在 ADMIN 角色的 `pages` 中加入新页面的 `*` 权限；菜单中已有这个页面编码的项，或 ADMIN 角色已有这个页面时，同样返回 422。
  - 页面的 `audit`、`detailMode` 取请求中的值（C09 第 3 节），由向导界面预填、管理员确认（frontend-config 的 FC-07）。
  - 保存操作的编码为 `<页面编码>.save`，页面的 `saveOperation` 引用它；`kind` 为 `save`，`propagation` 为 `continue`，`rowNotFound` 取默认的 `skip`，`impact` 为主表实体和各明细实体。
  - 保存操作的 `writableFields` 按生成的实体和页面配置逐个实体列出，不放开全部字段：只包含 `role` 为 `input`、`column` 不为 null、实体的 `fieldDefaults` 和页面都没有设为不可编辑的字段，不包含主键、主从关联字段和 `erpRow.column`；没有 `erpRow` 的实体不包含 ERP 列（C06 第 10 节）。
  - 已有实体可以从视图重新导入列：新列加入，已有列的设置不变，视图中已删除的列列出来，由管理员处理。
- CF-15：seed 带三个基础资料页（第 8 批 G1，2026-10-31；用户 2026-10-30 对"外币管理（含同步ERP汇率）"等回复"要"，2026-10-31 回复"开始"）。来源是旧系统 cmx 中 goods-manage、customer-manage、formoney-manage 的表元数据、列元数据、页面组件和页面规则（`.reports/batch8-20261031/g1-basic-pages/q01`～`q03`），页面由通用页面按页面编码打开：
  - 产品信息维护 `GOODS_MANAGE`：实体 `COST_GOODS`，写 `T_COST_GOODS`，经 `T_COST_GOODS_V` 读（只取产成品，外连接客户、分销商取名称）。它和物料清单的 `COST_GOODS_PRICE` 是同一张表上的两个主表实体，同旧系统 CostGoods、CostGoodsPrice 都写 T_COST_GOODS；两个视图的行不重叠（产成品；非产成品、半成品）。客户 ID 经客户 Lookup `costCustomer` 选，回填客户 ID、客户名称、国家、分销商 ID、分销商名称（旧列元数据 ZX_CUSTOMERID 的 cellEditorParams）；华益代码、分销商名称、客户名称、国家、创建人只在视图中；新增时写创建人、修改人（C06 v28 `createdByColumn`、`updatedByColumn`）。
  - 客户信息 `CUSTOMER_MANAGE`：主表 `COST_CUSTOMER`（T_COST_CUSTOMER），明细"分销商" `COST_TRANPOSER`（T_COST_TRANPOSER，关联 CUSTOMID）。
  - 外币管理 `FORMONEY_MANAGE`：实体 `COST_FORMONEY`（T_COST_FORMONEY，经 `T_COST_FORMONEY_V` 读，本地汇率为空时显示 ERP 的汇率）；各列都不能编辑（旧列元数据 EDITABLE 全为 0）；工具栏按钮"同步ERP汇率"（operations OP-11）。
  - 按钮同旧系统：新增、复制、删除、保存列配置、保存（客户信息的明细同样）；旧客户信息的"导出"按钮没有动作，不做（盘点乙第 3 节）。ERP 行（ISERP = 1）整行绿底 `#e6ffed`、整行不能改（旧 GRID_STYLE 和 EDITABLE 规则）；分销商是明细，这两条写成实体层的界面规则（页面层 `field` 为 null 的规则只作用于主表）。
  - 权限：ADMIN 三个页面 `["*"]`（旧系统管理员 `["*"]`）；旧系统技术中心在这三个页面没有权限（cmx T_COST_ROLE_PAGE 没有行），seed 的技术中心不授。菜单项由主代理加在"基础信息"（`basic`）下。
- CF-16：保存实体时，`createdByColumn`（C06 v28）与 `updatedByColumn` 的要求相同：是 `table` 中的列，不是任何实体字段写入的列；另外不能与 `updatedByColumn` 相同（C06 第 10 节）。`readView` 照旧只校验视图存在、包含主键和实体的全部字段；视图可以关联别的表或视图（C06 v28 第 2 节），不另校验。
- CF-17：seed 带液体成本核算（2026-10-31 第 8 批 G2，T-CF-10；用户 2026-10-30 对第 4 项回复"要"，2026-10-31 回复"开始"）。按旧页面 cost-pinggu-lq"物料成本核算表_液体"转换（cmx 表元数据 176～178、页面组件 176/177/186/187、页面规则 604/608/609/616/620、列元数据、Lookup 78、T_COST_ROLE_PAGE 143/261），共 24 项新配置，写法同成本核算，不改 config 的代码：
  - 实体 `COST_PINGGU_LQ`（T_COST_PINGGU_LQ，旧主表 42 列）、`COST_MATERIAL_LQ`、`COST_PACKAGE_LQ`（都写 T_COST_PINGGU_DTL_LQ，分别读 V_COST_PINGGU_MATERIAL_LQ、V_COST_PINGGU_PACKAGE_LQ）；页面 `COST_PINGGU_LQ`（标题"液体成本核算"，明细"原料/辅料""包材"，按钮同旧组件，去掉"同步采购价"）；操作 `COST_PINGGU_LQ.save`、`COST_PINGGU_LQ.generateFromBom`（operations OP-12）；规则 `R_LQ_*` 17 条（主表 12 条计算、1 条"ERP未搭建BOM"整行红底，原辅料、包材各 2 条计算）；Lookup `costMaterial`（物料选择，单价取参考价格 PRICE，旧液体页面用的就是它；成本核算用的是 `costMaterialEffective`）；`role.ADMIN`、`role.技术中心` 加这个页面。
  - 与旧系统一致：计算公式按旧前端规则 604、616、620（与成本核算不同：每批销售额不除包装规格，每盒成本、每盒加工费按批量除，没有"出厂价 = 外币 × 汇率"）；空值按 0、除以 0 得 0、包材名称三个分支都不匹配时每批数量不变，同旧计算引擎 `calculator.ts`。对 d_cg 493 张液体单据重算的对比见 T-CF-10。
  - 与旧系统不同：旧规则读 SOURCE_BATCH_QTY 的分支不写（d_cg 没有这一列，cmx 未删除明细中全为空或 0，分支不成立）；明细的分类 DTL_USEFLAG 由物料 Lookup 带出（明细表没有这一列，旧页面原辅料的下拉写的是视图不读的列，不带出时新增行分类为空、主表合计漏算）；旧 VALIDATION 615、619 字段名写成小写 `price`，旧系统取不到值、实际不校验，不写；"同步采购价"用户 2026-10-30 不要（同成本核算）。
- CF-18：只读页面（C06 v29 第 2、3 节，C05 v10）。页面配置的 `saveOperation` 为 null 时是只读页面：不引用保存操作，页面视图的 `saveOperation` 为 null，`systemButtons` 不给出 `save`（角色有 `*` 也一样），可写字段为空，所以字段的 `editable` 都为 false；查询、筛选、排序、高级查询、导出、保存列配置照常。实体的 `table` 可以是视图：这是只读实体，校验时视图和列必须存在、主键列在视图中，不要求序列 `<表名>_SEQ`；字段的 `column` 是视图的列。例：审计追踪页 `AUDIT_LOG`（seed `page.AUDIT_LOG.json`、`entity.AUDIT_LOG.json`）读 write-pipeline 的视图 `PF_AUDIT_LOG_V`（WP-22），只给 ADMIN（`role.ADMIN.json` 的 `AUDIT_LOG: ["*"]`）。来源：旧系统审计追踪页 auditLog 是通用页，cmx `T_COST_TABLE_METADATA` 146（QUERY_VIEW `V_COST_AUDIT_LOG`、AUDIT_ENABLED 0）、列元数据 10 列（`TABLE_METADATA_ID` 146），已删除的 COLUMN_OVERRIDE 规则 550 把全部列设为 `editable: false`；`T_COST_ROLE_PAGE` 142 只给系统管理员（`BUTTON_POLICY` 为 `["*"]`）；旧前端没有 auditLog 的专门代码。旧前端的保存按钮只看 `hasButton('save')`（`MasterDetailLayoutV3.vue` 第 74 行），系统管理员 `["*"]` 时审计页上也有保存按钮，新平台按"只读页面"做，不给保存。用户 2026-10-30 对盘点乙第 4 节回复"要"、2026-10-31 回复"开始"。
- CF-19：页面视图的字段带出实体字段的 `default` 和 `compare` 的显示方式（C05 v9，2026-10-31 第 8 批，盘点 B8、B9）：`default` 原样带出（写法同 C06 第 2 节），`compare` 只带 `{"format": ...}`，没有配置时两项都省略。新增行时前端立即按默认值填值、对比按配置的显示方式显示（frontend-page 的 FP-23、FP-24），同旧系统 `useWorkingSetStore.ts` 第 543–585 行、`useMetaColumns.ts` 第 166–176、423–455 行。保存时后端照样按实体字段补默认值（WP-16），与页面视图无关。seed 的实体都没有配这两项，页面视图不变。
- CF-20：新建页面向导读列注释、按关键字列出表和视图（2026-10-31 第 8 批，盘点 B14、B15）：
  - `wizard/columns` 的 `label` 取读结构的那个视图（没有视图时为表）的列注释，没有注释的列取列名，同旧系统 `MetaConfigService.listViewColumns`（DBA_COL_COMMENTS）和 `useWizardState.ts` 第 103 行 `headerText: vc.comment || vc.columnName`。例：液体成本核算主表 T_COST_PINGGU_LQ 的 COST_PERBOX 标题为"每盒成本"、M_PERPACK 为"每中盒小盒数"；生成的实体字段 `label` 取向导提交的标题（CF-14）。
  - `POST /api/config/schema/objects`（C09 v16）：经 db-core 的 `SchemaInspector.objects`（DB-07）列出 d_cg 中名称含关键字的表和视图，最多 100 个，先表后视图、各按名称排列，同旧系统 `MetaConfigService.listDbObjects` 第 621–645 行；只读，管理员才能用。
- CF-21：seed 带旧系统 cmx 的 7 个业务角色（2026-10-31 第 9 批；用户"角色你迁移过来"）。`role.001.json`、`role.002.json`、`role.003.json`、`role.005.json`、`role.006.json`、`role.007.json`、`role.008.json`，编码、名称取 cmx `T_COST_ROLE` 121～127 的 ROLE_CODE、ROLE_NAME（001 海外营销中心-商业运营、002 海外营销中心-商务、003 海外营销中心-项目维护、005 海外营销中心-调研、006 海外营销中心-注册、007 生产、008 采购），`admin` 都为 false（旧系统只有 ADMIN 有配置和权限管理页面）。
  - 页面权限取这些角色在 `T_COST_ROLE_PAGE` 中新平台有的页面：cost-pinggu → COST_PINGGU、cost-pinggu-lq → COST_PINGGU_LQ、goods-manage → GOODS_MANAGE、customer-manage → CUSTOMER_MANAGE、goods-price-manage → GOODS_PRICE_MANAGE、formoney-manage → FORMONEY_MANAGE。生产（007）只有前三个，其余 6 个角色都是这 6 个页面。
  - 转换规则同 seed 的 `role.技术中心.json`（C06 v24 第 8 节）：`系统默认按钮:save` 给 `system:save`、`master:modify` 和每个明细的 `addRow`、`deleteRow`、`modify`（旧后端保存只检查 save，`DynamicDataService.java` 第 1095 行）；`系统默认按钮:addRow`、`deleteRow` 给 `master:addRow`、`master:deleteRow`；`advancedSearch` 给 `system:advancedSearch`；`<旧区域名>:<动作>` 按旧 `T_COST_TABLE_METADATA.TABLE_NAME` 换成区域编码（例如 原辅料明细 → COST_MATERIAL、分销商信息 → COST_TRANPOSER），`外币管理:SYNC_ERP_RATE` 给 `master:syncErpRate`；`自定义导出:<编码>` 给 `export:<编码>`（cost-pinggu-export、goods-price-pgoods-export）。COLUMN_POLICY 按组件键（masterGrid、grid → master，material、package、tranposer → 明细实体）和 columnName 换成 `columns`，只留 visible、editable；ROW_POLICY 原样。
  - 不迁的旧权限：`系统默认按钮:approval.*`（审批的处理由审批流决定）；`物料成本核算表:syncPrice`、`物料成本核算表_液体:syncPrice`（同步采购价，用户 2026-10-30 不要，按钮已删，operations 的 T-OP-10）；客户信息页的 `客户信息:`、`分销商信息:`（冒号后没有动作，不对应任何按钮）；cost（"基础信息"目录的 `["*"]`，新平台的菜单分组按其中的页面显示，CF-12）、home（首页）两行；project、wms-shipping 两个新平台没有的页面。不迁测试角色"普通用户""test11"，不迁账号（`T_COST_USER`、`T_COST_USER_ROLE`）。
  - 与旧系统不同的一处：003 在成本核算的行权限（旧 `T_COST_ROLE_PAGE` 297）是 `USESTATUS = '委托研发' OR USESTATUS = '评估中' OR CREATE_BY = '委托转移'`，d_cg 的 T_COST_PINGGU 没有 CREATE_BY 列，保存时校验不过；cmx 中 CREATE_BY 为"委托转移"的单据 0 行，与其他条件是 OR，去掉这一条后能看到的单据与旧系统相同，迁成 `USESTATUS = '委托研发' OR USESTATUS = '评估中'`。同一角色液体页（298）的同一位置是 `USESTATUS = '委托转移'`，旧配置可能选错了字段，这里按旧系统的实际效果迁，没有改成状态"委托转移"。
  - 每一项的对照、生成脚本和只读查询见 `.reports/batch9-20261031/a-roles/`（`迁移对照.md`、`gen_roles.py`、`q02-角色页面内容.out.txt`）。d_cg 已经保存（版本 1）。
- 规则没有"数据项"（C06 v27，盘点 U3）：写了 `dataItems` 的规则保存时按未定义的字段拒绝（422），保存时也不再校验数据项的 SQL；规则包中规则的 `serverOnly`（C07）都为 false。
- CF-22：页面视图的字段带出页面字段设置的 `copy`（C06 v30 第 3 节，C05 v11；2026-10-31 第 9 批）：页面配置这个区域的这个字段写了 `copy: false` 时，页面视图中这个字段带 `"copy": false`，不论字段可不可见；没有写或写 `true` 时省略，页面视图与 v10 相同，没用这一项的页面在 main 的前端上照样能读。复制时前端不复制这一列（frontend-page 的 FP-25），后端也不取源行的值（write-pipeline 的 WP-24）。保存页面配置时不另做校验。例（E45）：客户信息页主表的区域 ZONE 写 `copy: false`，系统管理员的页面视图中只有 ZONE 带 `"copy": false`。依据：用户 2026-10-31"复制主表要把明细表一起复制过来，这个是通用方法，但是也可以配置哪些列可以不复制，这个在元数据中配置即可"；旧系统复制只排除 id 和主键（`cost-web/src/v3/composables/meta-v3/copy-row-fields.ts` 第 3–12 行），没有这项配置，是新增能力；配在页面字段设置上，同旧系统每个页面一份列元数据。代码在 `views.py`（`_view_field`）、`page_view.py`（文件配置用）。

## 4. 依赖

| 契约 | 提供方 | 用途 |
|---|---|---|
| `UnitOfWork`、`SchemaInspector` | db-core | 写入配置；保存时核对表和列 |
| `RulesEngine` | rules-core | 保存时编译规则包，检查能否编译 |
| `RealtimePublisher` | realtime | 发布配置变更事件 |

## 5. 内部流程

保存：校验 → 生成页面视图和规则包 → 一个事务写入 → 提交 → 写 Redis 并切换 → 发布事件。读取快照：一次 Redis 读取 → 有缺项时回查 Oracle → 解析结果按版本放进进程缓存。

## 6. 接入方式

- assembly 的中间件调用 `ConfigSnapshotReader`；assembly 在启动时调用 CF-10 和 CF-13，并启动恢复任务。
- frontend-config 调用 C09 第 3 节的接口；migration 调用 `ConfigImporter`。
- 真实联调：批次 A。

## 7. 验收边界

- 开始开发的前置条件：contracts 完成。
- 本模块完成（模拟验证）：用替代实现验证 C06 第 10 节的每条校验、三层叠加的结果、快照不混用版本，以及 CF-05 的各种中断情况。
- 联调后才能确认：在 Oracle 和 Redis 上保存配置后，打开的页面无需刷新即可生效（批次 A、D）。
