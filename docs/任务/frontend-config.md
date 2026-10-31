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
- 状态与证据：进行中（模拟验证通过；界面已注册到外壳并在浏览器中运行，见 2026-10-31 核对；待独立复核）。2026-10-29：`frontend/src/modules/config/index.ts` 导出 C11 的 `configModule`（路由 `/config`，`?tab=` 选 unified / lookup / permission / dict / items），`canConfigure` 按 `session.role.admin` 判断，非管理员只显示提示（FC-01）。`core/store.ts` 先 `POST /api/config/validate` 再 `PUT`，422 和校验错误按 `path` 解析（`core/errors.ts`），`core/item-editor.ts` 是各类配置共用的"列表 → 打开 → 编辑 → 校验 → 保存 → 新版本号"；新建时预填 C06 1.1 必须写的字段（`core/defaults.ts`，FC-02）。界面沿用旧项目 `views/_builtin/meta-config`：一体化配置（菜单树可拖动排序、目录信息、页面配置的基本信息 / 表与列 / 页面行为 / 表单布局 / 导出配置 / 审批流）、Lookup管理、角色权限（同旧 `views/_builtin/permission/index.vue`：页面权限树、配置按钮、配置列、配置行，行权限可视化和自定义 SQL，SQL 生成同旧 `generateSqlFromConditions`，FC-04）、字典管理、全部配置项；操作在"页面行为 → 操作"中编辑。模拟验证：`pnpm exec vitest run tests/config`，`tests/config/items.test.ts` 6 个、`rules-role-layout.test.ts` 中行权限 3 个，全部通过（字典列表 → 编辑 → 先校验再保存 → 版本 3；页面保存 422 时明细带配置项和路径；新建 Lookup、角色预填并保存；模块装载和非管理员判断）。`pnpm typecheck` 0 个错误，`pnpm test` 28 个文件 487 个用例全部通过（`.reports/modules/frontend-config/pnpm-*.txt`）。上线后再补：两人同时编辑同一配置项、接口失败重试等非正向流程。缺口见 `.reports/modules/frontend-config/contract-gaps.md` 第 6～8 条。2026-10-30（随 C06 v18，T-OP-3）：操作的动作加"按 SQL 替换选中单据的明细（replaceDetails）""按 SQL 找到记录并更新，不用选中行（updateRows）"，在"页面行为 → 操作"中编辑明细实体、SQL、绑定变量、单据主键列和明细主键列（`views/OperationDialog.vue`、`operation-form.ts`、`core/types.ts`）；模拟验证 `tests/config/operation-actions.test.ts` 2 个（动作列表、预填，按 seed 的写法新建两条操作并保存），界面没有在浏览器中运行。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"待联调"改为"完成"。
    - 浏览器：`frontend/tests/e2e/basic-1029.spec.ts:104`"场景 1 配置生效"（表与列取消主表包装形式的编辑后成本核算里不能编辑）、`:328`"场景 3 角色权限"通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。
    - 两人同时编辑同一配置项、接口失败重试：本条已标上线后再补。
    - 缺口第 8 条中的列"千分位"（甲核对第四节 B6）和 Lookup 显示列的标题、宽度（B7）由第 7 批 PG 组做（没有单独的任务卡；提交 7d00696，C06 v22、C05 v6；报告 `.reports/batch7-20261030/pg-page-display/报告.md`）：配置页"表与列"加"千分位"勾选，Lookup管理"配置显示列"加"显示标题""宽度"；浏览器 `frontend/tests/e2e/batch7-page-display.spec.ts:30`、`:43`（千分位）、`:56`（Lookup 表头和列宽）通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。
    - 缺口第 8 条中的菜单图标（甲核对第四节 B13）：未做，排在第 8 批。
    - `.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

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
- 状态与证据：进行中（模拟验证通过；界面已在浏览器中运行，见 2026-10-31 核对；待独立复核）。2026-10-29：审批流 `approval/`：`flow-model.ts`（行结构与 C06 第 7 节互转，审核操作摘要）、`flow-editor.ts`（读取、新增流程、三个 Tab 的新增删除上移下移、弹窗应用、先校验再保存并回读、删除，错误按 path 定位到流程列表或某个 Tab 的某行某格）、`params.ts`（来源 / 表 / 字段插入 `:new_`、`:old_`、`:master_*`、`:user_*`、`:operation`、`:billId`、`:row_`、`:params_`）；界面 `SectionApproval.vue` 的布局和样式同旧 `SectionApproval.vue`、`ApprovalConfigGrid.vue`、`approval-config-columns.ts`（AG Grid 行高 28、表头 #f5f7fa），流程列表列为流程名称、所属页面、审核操作、启用、顺序，三个 Tab 审批节点 / 冻结节点 / 展示数据，弹窗：审核操作（按表格勾新增、修改、删除）、入口条件 / 关联条件（同旧 `ApprovalConditionEditor.vue`）、审批人（人员、角色、SQL 选人）、审批展示 · 列映射、审批通过后写入的字段（另可选新增一行、删除这一行、逃生舱）、参数、通知；展示数据另有"块编码"列（C06 7.5 的 `key`）。规则 `rules/`：`rule-editor.ts`、`RuleConfigDialog.vue`（计算、校验，卡片 + 字段参考，同旧 `RuleConfigDialog.vue`）、`CellEditableDialog.vue`、`GridStyleDialog.vue`，入口在"页面行为"（同旧 `SectionBehavior.vue`）。模拟验证：`tests/config/approval-flow.test.ts` 7 个用例通过——7.8、7.9、7.10 三个审批流经编辑界面的动作配出后，`PUT /api/config/items/approvalFlow/{key}` 的 `content` 与 C06 样例逐字段相同（`tests/config/flow-samples.ts` 照抄样例），审核操作摘要为"原辅料.新增、原辅料.修改、包材.新增、包材.修改"，再次打开后不改动保存内容不变；422 `levels[1].nodes[0].approvers` 定位到第 2 级那一行的审批人格；校验错误定位到展示数据的显示列格和流程列表的审核操作格。`rules-role-layout.test.ts` 中规则 2 个用例通过：包材批量的两条分支（条件由"分支字段 + 正则 + 值"生成）和 ERP 物料整行不可编辑，保存内容与 C06 第 5 节样例相同。缺口见 contract-gaps 第 4～6 条。2026-10-30（G2 组，`batch2/config-ui`）：条件中的字符串改为与后端 `_string` 相同（含单引号用双引号、不转义，`rule-model.ts` 的 `quote`），`rules-role-layout.test.ts` 加含单引号的值（乙酰'唑胺）1 个用例。数值字段的"必填"（FC-06）：`rule-editor.ts` 的 `RequiredCard`、`toRequired`、`saveRequired`，`RuleConfigDialog.vue` 的"设为字段必填"和"字段必填"卡片，`PageConfigPanel.vue` 在保存后让"表与列"重新挂载；`tests/config/field-required.test.ts` 4 个用例通过（单价必填按实体写 `fieldDefaults.PRICE.required`、按本页面写原料/辅料区的字段设置，都不生成规则配置项，"表与列"显示勾选；再次打开列为已保存；删除后只去掉必填；文本字段仍生成条件）。页面上的效果由写入管道的测试证明（`backend/tests/pipeline/test_flow.py` 的 `test_required_number_price_*` 2 个：新增原辅料单价为 null 时 422 指出 PRICE，填 0 能保存；已保存的行清空单价被拒绝），前端新增行清空的数值字段在命令中写 null 见 frontend-page 的 T-FP-1。浏览器核对（后端 8085、前端 9533，d_cg）：原料/辅料的校验规则弹窗列出 seed 已有的"每片含量""单价"两项字段必填（本页面 · 已保存），已有的两条校验规则"规则"显示为"自定义"；新加一条、字段选单价、规则必填，按钮变为"设为字段必填"并显示说明，点后换成"单价 · 实体默认（所有页面）"卡片；点保存时在浏览器中拦下全部写请求，发出的校验请求体是原辅料实体只多了 `fieldDefaults.PRICE.required: true`、没有规则配置项，d_cg 中原辅料实体仍是版本 2。另经校验接口（只校验不保存）核对：条件 `MEMO == "乙酰'唑胺"` 通过，旧写法 `MEMO == '乙酰\'唑胺'` 报 Lexer error。没有把"单价必填"保存到 d_cg 做页面验证。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"待联调"改为"完成"。
    - 浏览器：`frontend/tests/e2e/basic-1029.spec.ts:575`"场景 4a 审批流配置：在配置页新建 C06 7.8 的成本明细改价审批，保存后读回与 7.8 相同"通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。
    - "没把单价必填保存到 d_cg 做页面验证"：seed 已有原辅料"每片含量""单价"必填；浏览器 `g0-1030.spec.ts:319`"场景 4b 拒绝提示"通过，后端 `tests/pipeline/test_flow.py` 的 `test_required_number_price_empty_rejected_zero_saved`、`test_required_number_price_modified_to_empty_rejected` 通过（第 7 批合并后模拟全量 1309 passed，`.reports/batch7-20261030/merge/pytest-1.txt`）。
    - `.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-FC-4 新建页面向导与扩展配置的编辑

- 归属与目标：实现 FC-07、FC-08、FC-10（"表与列"的"求和"，2026-10-30 加入）。
- 前置输入：开始前 T-FC-1。
- 负责范围：config 模块中的向导和扩展配置表单。
- 交付物：向导界面；必须审批规则、默认值、对比、SQL 审批人和动作参数的编辑。
- 接入责任：真实联调在 T-AS-7。
- 验收标准：模拟验证：按向导生成物料清单页的请求与 C09 样例一致；审计默认开启、明细显示方式默认多 Tab，管理员改为关闭审计后，请求中的 `audit` 为 false；单表页不显示明细显示方式，请求仍带 `detailMode`；序列不存在时提示先建序列，不能继续生成。
- 状态与证据：待联调（模拟验证通过；界面没有在浏览器中运行）。2026-10-29：向导 `wizard/wizard-state.ts`、`WizardPanel.vue`、`WizardTableForm.vue`，步骤同旧 `WizardPanel.vue`（页面菜单 / 导入表与配置字段 / 确认生成），页面编码输入同旧 `handleCodeInput`；归属菜单取菜单配置的分组；导入列经 `POST /api/config/wizard/columns`，序列不存在时提示并不能进入下一步、不发生成请求。显示、编辑的调整随请求带 `fieldDefaults`，后端没有写进实体时生成后补存（contract-gaps 第 2 条）。扩展配置：实体的必须审批字段规则（`entity/ApprovalRequiredDialog.vue`，入口"页面行为 → 需审批的编辑字段"）、默认值和选项值、对比（`views/TableFieldsCard.vue` 的列、`CompareDialog.vue`），审批流的 SQL 审批人和参数（审批人弹窗、参数弹窗）。模拟验证：`tests/config/wizard.test.ts` 7 个用例通过——生成请求顶层与 C09 样例一致（parentMenu cost、GOODS_PRICE_MANAGE、物料清单及成本、single、tabs、audit true、details 空），`master` 为 wizard.py 的写法；关闭审计后 `audit` 为 false、单表页仍带 `detailMode`；序列 T_COST_GOODS_SEQ 不存在时提示、不能继续、没有生成请求；调整显示、编辑后实体补存 `fieldDefaults`；物料实体保存必须审批规则、选项默认值、对比；审批流保存 SQL 审批人的绑定变量和最终批准时填写的参数。2026-10-30（丙组，`batch1/summary`）：FC-10，`views/TableFieldsCard.vue` 的列表格在"不能修改的原因"后加"求和"勾选列（非数值字段不能勾，悬停提示"只有数值字段能求和"），`table-fields.ts` 读写页面字段设置的 `aggregate`。模拟验证：`tests/config/table-fields.test.ts` 新增 1 个通过（seed 成本核算主表的总成本、原辅料金额显示已勾选；勾选主表批量 APEX_PL 并保存，页面只多写 `APEX_PL: {aggregate: "sum"}`）。界面没有在浏览器中运行。

### T-FC-5 新建页面向导搜表和视图、标题取列注释；规则编辑去掉数据项

- 归属与目标：实现 FC-14、FC-15（盘点 `.reports/inventory-20261030/甲-任务卡核对.md` 第四节 B14、B15，第五节 U3；用户 2026-10-31 回复"开始"）。来源：旧系统 `cost-web/src/views/_builtin/meta-config/panels/unified/sections/SectionTables.vue` 第 47–56、587–601 行（NAutoComplete，两个字符起查）、`panels/composables/useWizardState.ts` 第 103 行、`panels/RuleConfigDialog.vue`。
- 前置输入：开始前 T-FC-4、T-CF-13。
- 负责范围：`wizard/wizard-state.ts`（`searchObjects`）、`wizard/WizardTableForm.vue`；`contracts/http.ts`、`contracts/api.ts`、`contracts/fakes/`（`schema/objects`）；`rules/RuleConfigDialog.vue`、`rules/rule-editor.ts`、`core/types.ts`（去掉数据项）。
- 交付物：向导"视图名""目标表"输入关键字列出表和视图；导入后的标题为列注释；规则对话框没有"+ 数据项"，保存的规则不带 `dataItems`。
- 接入责任：真实联调在本卡的浏览器用例。
- 验收标准：模拟验证：输入一个字符不查询；输入"T_COST_GOODS"请求带这个关键字，下拉为 T_COST_GOODS（表）、T_COST_GOODS_PRICE_V（视图）；导入的标题为后端给出的列注释，生成请求只提交与列名不同的标题；包材批量规则保存的内容与 C06 第 5 节样例相同（不带 `dataItems`）。业务例子（浏览器、d_cg，正式用例 `frontend/tests/e2e/batch8-config-caps.spec.ts` 场景 1）：配置 →"+ 新增页面"，第 2 步目标表输入 T_COST_GOODS，下拉列出物料表和物料清单视图、先表后视图，与接口结果相同；输入 T_COST_PINGGU_LQ 选中液体成本核算主表，导入列后每盒成本、每中盒小盒数的标题为列注释，DOCID 为列名；不点生成，全程没有写配置的请求。
- 状态与证据：进行中（模拟验证和浏览器用例通过；待独立复核）。2026-10-31 第 8 批 G5，分支 `batch8/config-caps`。模拟验证：`tests/config/wizard.test.ts` 新增 1 条、`rules-role-layout.test.ts` 改期望（不带 `dataItems`）、契约测试加 `schema/objects` 的请求、响应和替代实现；`pnpm test` 42 个文件 590 passed（`pnpm-test.txt`），`pnpm typecheck`、`pnpm lint:deps` 通过。浏览器：后端 8097（本分支代码），setup 3 个、本卡 1 个 passed（`e2e-2.txt`）；第一次运行发现 NAutoComplete 选中时把下拉文字"T_COST_PINGGU_LQ（表）"填进输入框，改为 label 只放名称、用 render-label 显示类型后通过。
  - 与旧系统的差别：下拉中名称后加"（表）""（视图）"（旧系统只显示名称）；输入框共用一份下拉、只用最后一次输入的结果，与旧系统共用 `dbObjectOptions` 相同。
