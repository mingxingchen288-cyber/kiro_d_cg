# frontend-config 任务

模块说明：[frontend-config](../模块/frontend-config.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E18（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-FC-1 配置列表与通用编辑

- 归属与目标：实现 FC-01、FC-02、FC-04，覆盖实体、页面、操作、角色、菜单、字典、Lookup、导出的编辑。
- 前置输入：开始前 T-CT-4，`ShellApi` 用模拟实现。
- 负责范围：`frontend/src/modules/config/`。
- 交付物：配置项列表和各类配置的编辑表单；行权限编辑（可视化条件和自定义 SQL）。
- 接入责任：T-AS-3 注册到外壳；T-AS-7 与真实后端联调。
- 验收标准（模拟验证）：每类配置都能读取、修改、校验、保存；校验错误定位到配置的具体位置；非管理员看不到入口。
- 状态与证据：待联调（模拟验证通过；Vue 界面只经过类型检查，没有在浏览器中运行，注册到外壳后在 T-AS-3 核对）。2026-10-29：`frontend/src/modules/config/index.ts` 导出 C11 的 `configModule`（路由 `/config`，`?tab=` 选 unified / lookup / permission / dict / items），`canConfigure` 按 `session.role.admin` 判断，非管理员只显示提示（FC-01）。`core/store.ts` 先 `POST /api/config/validate` 再 `PUT`，422 和校验错误按 `path` 解析（`core/errors.ts`），`core/item-editor.ts` 是各类配置共用的"列表 → 打开 → 编辑 → 校验 → 保存 → 新版本号"；新建时预填 C06 1.1 必须写的字段（`core/defaults.ts`，FC-02）。界面沿用旧项目 `views/_builtin/meta-config`：一体化配置（菜单树可拖动排序、目录信息、页面配置的基本信息 / 表与列 / 页面行为 / 表单布局 / 导出配置 / 审批流）、Lookup管理、角色权限（同旧 `views/_builtin/permission/index.vue`：页面权限树、配置按钮、配置列、配置行，行权限可视化和自定义 SQL，SQL 生成同旧 `generateSqlFromConditions`，FC-04）、字典管理、全部配置项；操作在"页面行为 → 操作"中编辑。模拟验证：`pnpm exec vitest run tests/config`，`tests/config/items.test.ts` 6 个、`rules-role-layout.test.ts` 中行权限 3 个，全部通过（字典列表 → 编辑 → 先校验再保存 → 版本 3；页面保存 422 时明细带配置项和路径；新建 Lookup、角色预填并保存；模块装载和非管理员判断）。`pnpm typecheck` 0 个错误，`pnpm test` 28 个文件 487 个用例全部通过（`.reports/modules/frontend-config/pnpm-*.txt`）。上线后再补：两人同时编辑同一配置项、接口失败重试等非正向流程。缺口见 `.reports/modules/frontend-config/contract-gaps.md` 第 6～8 条。2026-10-30（随 C06 v18，T-OP-3）：操作的动作加"按 SQL 替换选中单据的明细（replaceDetails）""按 SQL 找到记录并更新，不用选中行（updateRows）"，在"页面行为 → 操作"中编辑明细实体、SQL、绑定变量、单据主键列和明细主键列（`views/OperationDialog.vue`、`operation-form.ts`、`core/types.ts`）；模拟验证 `tests/config/operation-actions.test.ts` 2 个（动作列表、预填，按 seed 的写法新建两条操作并保存），界面没有在浏览器中运行。

### T-FC-2 表单布局编辑

- 归属与目标：实现 FC-03。
- 前置输入：开始前 T-FC-1。
- 负责范围：config 模块中的表单布局编辑（grid-layout-plus）。
- 交付物：拖动和缩放字段、保存布局。
- 接入责任：保存后经 `config.changed` 推给已打开的页面，T-AS-7 联调。
- 验收标准（模拟验证）：拖动和缩放按整列、整行，不超出 24 列；保存的布局符合 C05；退出编辑而不保存时恢复原布局。
- 状态与证据：待联调（模拟验证通过；拖动界面没有在浏览器中运行）。2026-10-29：规则在 `layout/form-layout.ts`（空布局从每行 3 个开始、取整、贴边、重叠时往下推、`cancel` 恢复、`result` 按行列排序），界面 `layout/SectionFormLayout.vue`（选区域、编辑布局、保存布局、退出编辑）和 `FormLayoutEditor.vue`。模块说明指定的 grid-layout-plus 没有安装，拖动用指针事件实现（contract-gaps 第 1 条）。旧项目没有表单布局拖动编辑，按模块说明实现。模拟验证：`tests/config/rules-role-layout.test.ts` 中表单布局 2 个用例通过（缩放到 30 列只到右边界、12.4 格取整为 12 并把压住的字段往下推、保存写进 `master.formLayout` 版本 2、退出不保存恢复原布局）。`config.changed` 推给已打开页面在 T-AS-7 联调。

### T-FC-3 规则与审批流编辑

- 归属与目标：实现 FC-05、FC-06。
- 前置输入：开始前 T-FC-1；C06 第 5、7 节经用户确认。
- 负责范围：config 模块中的规则和审批流编辑。
- 交付物：规则表单（规则类型、作用字段、条件、表达式、分支）；审批流配置（C06 第 7 节的全部配置项，界面同旧系统页面配置中的"审批流"，FC-05）。
- 接入责任：T-AS-7 与真实后端联调。
- 验收标准：能编辑并保存 C06 第 5 节的两条规则；在成本核算、物料清单及成本两个页面的"审批流"中，按《审批流配置定稿》的界面配出 C06 7.8、7.9、7.10 三个审批流并保存，保存内容与样例相同：审核操作弹窗勾出"原辅料.新增、原辅料.修改、包材.新增、包材.修改"，审批节点写入第 1、2 级入口条件和会签，冻结节点写表名和关联条件，展示数据写视图、修改的表、主键列、显示列和写入字段。
- 状态与证据：待联调（模拟验证通过；界面没有在浏览器中运行）。2026-10-29：审批流 `approval/`：`flow-model.ts`（行结构与 C06 第 7 节互转，审核操作摘要）、`flow-editor.ts`（读取、新增流程、三个 Tab 的新增删除上移下移、弹窗应用、先校验再保存并回读、删除，错误按 path 定位到流程列表或某个 Tab 的某行某格）、`params.ts`（来源 / 表 / 字段插入 `:new_`、`:old_`、`:master_*`、`:user_*`、`:operation`、`:billId`、`:row_`、`:params_`）；界面 `SectionApproval.vue` 的布局和样式同旧 `SectionApproval.vue`、`ApprovalConfigGrid.vue`、`approval-config-columns.ts`（AG Grid 行高 28、表头 #f5f7fa），流程列表列为流程名称、所属页面、审核操作、启用、顺序，三个 Tab 审批节点 / 冻结节点 / 展示数据，弹窗：审核操作（按表格勾新增、修改、删除）、入口条件 / 关联条件（同旧 `ApprovalConditionEditor.vue`）、审批人（人员、角色、SQL 选人）、审批展示 · 列映射、审批通过后写入的字段（另可选新增一行、删除这一行、逃生舱）、参数、通知；展示数据另有"块编码"列（C06 7.5 的 `key`）。规则 `rules/`：`rule-editor.ts`、`RuleConfigDialog.vue`（计算、校验，卡片 + 字段参考，同旧 `RuleConfigDialog.vue`）、`CellEditableDialog.vue`、`GridStyleDialog.vue`，入口在"页面行为"（同旧 `SectionBehavior.vue`）。模拟验证：`tests/config/approval-flow.test.ts` 7 个用例通过——7.8、7.9、7.10 三个审批流经编辑界面的动作配出后，`PUT /api/config/items/approvalFlow/{key}` 的 `content` 与 C06 样例逐字段相同（`tests/config/flow-samples.ts` 照抄样例），审核操作摘要为"原辅料.新增、原辅料.修改、包材.新增、包材.修改"，再次打开后不改动保存内容不变；422 `levels[1].nodes[0].approvers` 定位到第 2 级那一行的审批人格；校验错误定位到展示数据的显示列格和流程列表的审核操作格。`rules-role-layout.test.ts` 中规则 2 个用例通过：包材批量的两条分支（条件由"分支字段 + 正则 + 值"生成）和 ERP 物料整行不可编辑，保存内容与 C06 第 5 节样例相同。缺口见 contract-gaps 第 4～6 条。

### T-FC-4 新建页面向导与扩展配置的编辑

- 归属与目标：实现 FC-07、FC-08。
- 前置输入：开始前 T-FC-1。
- 负责范围：config 模块中的向导和扩展配置表单。
- 交付物：向导界面；必须审批规则、默认值、对比、SQL 审批人和动作参数的编辑。
- 接入责任：真实联调在 T-AS-7。
- 验收标准：模拟验证：按向导生成物料清单页的请求与 C09 样例一致；审计默认开启、明细显示方式默认多 Tab，管理员改为关闭审计后，请求中的 `audit` 为 false；单表页不显示明细显示方式，请求仍带 `detailMode`；序列不存在时提示先建序列，不能继续生成。
- 状态与证据：待联调（模拟验证通过；界面没有在浏览器中运行）。2026-10-29：向导 `wizard/wizard-state.ts`、`WizardPanel.vue`、`WizardTableForm.vue`，步骤同旧 `WizardPanel.vue`（页面菜单 / 导入表与配置字段 / 确认生成），页面编码输入同旧 `handleCodeInput`；归属菜单取菜单配置的分组；导入列经 `POST /api/config/wizard/columns`，序列不存在时提示并不能进入下一步、不发生成请求。显示、编辑的调整随请求带 `fieldDefaults`，后端没有写进实体时生成后补存（contract-gaps 第 2 条）。扩展配置：实体的必须审批字段规则（`entity/ApprovalRequiredDialog.vue`，入口"页面行为 → 需审批的编辑字段"）、默认值和选项值、对比（`views/TableFieldsCard.vue` 的列、`CompareDialog.vue`），审批流的 SQL 审批人和参数（审批人弹窗、参数弹窗）。模拟验证：`tests/config/wizard.test.ts` 7 个用例通过——生成请求顶层与 C09 样例一致（parentMenu cost、GOODS_PRICE_MANAGE、物料清单及成本、single、tabs、audit true、details 空），`master` 为 wizard.py 的写法；关闭审计后 `audit` 为 false、单表页仍带 `detailMode`；序列 T_COST_GOODS_SEQ 不存在时提示、不能继续、没有生成请求；调整显示、编辑后实体补存 `fieldDefaults`；物料实体保存必须审批规则、选项默认值、对比；审批流保存 SQL 审批人的绑定变量和最终批准时填写的参数。
