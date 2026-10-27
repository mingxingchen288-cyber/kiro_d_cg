# migration

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：命令 `platform migrate`：只读连接 cmx，读取旧元数据，生成配置项（[C06](../契约/C06-配置模型.md)）和三份盘点清单；用户确认后，经各模块的导入接口写入配置、账号和个人列配置；按迁移后的配置重算真实单据并对账；编写切换手册。
- 不负责：配置、账号、个人配置的存储（config、identity、queries-export）；业务表的复制（db-core）。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `backend/src/cost_platform/migration/` |
| 产物 | 迁移输出目录 `.reports/migration/`：生成的配置、三份清单、对账报告；切换手册 `docs/切换手册.md` |

## 3. 对外契约

命令行：`platform migrate generate`（生成配置和清单）、`platform migrate import`（导入）、`platform migrate reconcile`（对账）。

- MG-01：可以反复运行；同样的输入生成逐字节相同的内容，不含运行时间。
- MG-02：三份清单：
  - 人工改写清单：不能原样迁移的 SQL 和 JS（例如审批条件中的 SQL、规则中的 JS）、无法自动转换的公式；
  - 候选逃生舱清单：旧审批动作和按钮调用的存储过程，默认改写成通用动作，由用户逐条决定；
  - 审批确认清单：新旧审批规则有差异的审批流。
  不能自动转换的内容不生成近似配置，只列入清单。
- MG-03：旧审批配置中的存储过程动作 `PKG_APPROVAL_PRICE_ACTIONS.COST_TO_GOODS`、`GOODS_TO_COST`，改写为 C06 7.4、7.5 的通用动作。旧审批流的 `trigger.operations`（`modified`、`added`、`deleted`）分别转为 `modify`、`add`、`delete`。
- MG-04：账号（含 BCrypt 哈希）、角色分配和部门经 identity 的 `AccountImporter` 导入；个人列配置经 queries-export 的 `PersonalConfigImporter` 导入；配置经 config 的 `ConfigImporter` 导入。
- MG-05：对账：按迁移后的配置，用 rules-core 重算真实单据，与业务表中计算字段的现有值比较；差异归入旧项目 `D:\chonggou\my-project\公式差异.md` 中的某一条，或列为未解释的差异。
- MG-06：切换手册写明每一步的操作和完成后的检查，包括停止旧系统写入、迁移配置和账号、虚拟列改为普通列并回填、核对，以及回退步骤。业务表整表复制到 d_cg 之后的数据同步由用户的 CDC 负责，手册只要求切换前确认同步已完成。
- MG-07：旧导出配置迁移为 C06 第 9 节的 `export`：MASTER_SQL、DETAIL_SQL 原样保留；`PAGE_FK_COLUMN` 是页面主表主键时，`MASTER_LINK_COLUMN` 对应 `keyColumn`，`DETAIL_LINK_COLUMN` 对应 `linkColumn`，否则列入人工改写清单。
- MG-08：旧角色权限迁移为 C06 第 8 节的格式：BUTTON_POLICY 的分组从区域标题换成区域编码（`系统默认按钮` 为 `system`，`自定义导出` 为 `export`），`approval.*` 不迁移（审批改为保存时自动触发，处理权限由审批流决定，进度所有人可看），列入报告；COLUMN_POLICY、ROW_POLICY 原样迁移。
- MG-09：旧系统的以下配置原样转为新格式：`APPROVAL_REQUIRED` 规则转为实体的 `approvalRequired`；字段的默认值转为 `default`；`rulesConfig.compare` 转为 `compare`；Lookup 的 `multiple`、`filterColumn`、`filterValueFrom`、`noFillback` 转为 C06 第 3 节的写法；审批的 SQL 审批人、`NODE_COMPLETED` 动作和动作参数转为 C06 7.1 的写法。旧审批流在 `FLOW_REJECTED`、`FLOW_CANCELED` 上的动作不迁移，列入审批确认清单。
- MG-10：生成的配置项写出 C06 第 1.1 节要求必须写的全部字段（例如页面的 `audit`、`detailMode`，操作的 `propagation`，角色的 `admin`）。旧配置中没有对应项的，按旧系统的实际行为取值，并写入迁移报告；不能确定取值的，列入人工改写清单（MG-02）。
- MG-11：生成的每个配置项都记下来源，即旧表名和行的主键（例如 `CMX.T_COST_PAGE_RULE` 中 `ID` 为 1234 的行），写在迁移输出中，不写进配置内容。`ConfigImporter` 拒绝整批时（422，C08 第 4 节），按错误明细 `path` 开头的 `items[<序号>]` 找回对应的配置项，在迁移输出目录写出拒绝清单：每个被拒绝的配置项一行，列出类型和编码、来源表和行、拒绝原因（中文，取错误明细的 `message`）。同一批中类型和编码重复的，重复的每一项各占一行，分别列出来源。被拒绝时什么都没有写入，修正后重新导入。

## 4. 依赖

| 契约 | 提供方 | 用途 |
|---|---|---|
| `ConnectionFactory` | db-core | 只读连接 cmx |
| `ConfigImporter` | config | 导入配置 |
| `AccountImporter` | identity | 导入账号 |
| `PersonalConfigImporter` | queries-export | 导入个人列配置 |
| `RulesEngine` | rules-core | 对账时重算 |

## 5. 内部流程

读取旧元数据 → 按 C06 生成配置 → 不能转换的内容列入清单 → 用户确认清单 → 导入 → 对账 → 演练切换。

## 6. 接入方式

- 命令行 `platform migrate` 由 assembly 组装后转给本模块。
- 真实联调：批次 E。

## 7. 验收边界

- 开始开发的前置条件：contracts 完成；d_cg 能以只读事务读取 `CMX.*`。
- 本模块完成（模拟验证）：用旧导出数据生成配置和清单，重复运行结果相同；清单中的每一项、生成的每个配置项都能追溯到旧数据中的位置；导入被拒绝时拒绝清单列出每项的来源和原因。
- 联调后才能确认：真实旧数据迁移后，页面能打开、能保存，对账没有未解释的差异，切换和回退都演练通过（批次 E）。

