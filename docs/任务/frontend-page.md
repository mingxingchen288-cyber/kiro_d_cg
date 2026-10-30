# frontend-page 任务

模块说明：[frontend-page](../模块/frontend-page.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E01、E02、E09（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-FP-1 编辑缓冲与视图模型

- 归属与目标：实现 FP-04。
- 前置输入：开始前 T-CT-4。
- 负责范围：`frontend/src/modules/page/` 的 edit-buffer、view-model，不引用 AG Grid 和 Vue 组件。
- 交付物：编辑缓冲（修改、新增、删除、改动标记、撤销重做、生成命令）；视图模型（合并正式数据、修改和预览结果）。
- 接入责任：T-FP-2、T-FP-3 使用；真实联调在 T-AS-7。
- 验收标准：基于属性的测试（fast-check）：任意编辑序列全部撤销后回到初始状态，撤销后重做回到撤销前；改回原值时修改和标记消失；删除未保存的新增行不进入命令；生成的命令符合 C02，只含修改的字段。
- 状态与证据：待联调（模拟验证通过，待独立复核）。2026-10-29 按模块说明一次做完：编辑缓冲移到 `frontend/src/modules/page/edit-buffer.ts`（`views/cost-pinggu` 已删除），记录修改、新增行、删除标记、改动标记，撤销和重做按行记录修改前后的状态，表格和表单共用，`batch` 把 Lookup 回填、复制、粘贴合成一步；生成命令时只带可写字段（不带计算字段、主键、关联字段、`erpRow.column`、只读的 ERP 列），删除主表行时不列出明细；按钮结果中的行可以单独丢弃修改并从历史中去掉。视图模型 `view-model.ts` 合并正式数据、修改和预览结果，给出明细行顺序（新增行插在原位）、冻结、可编辑和标记。先写测试 `frontend/tests/page/edit-buffer.test.ts`（例子取成本单 2550、2551 和 E01 的 200680；fast-check：任意编辑序列全部撤销后回到初始状态、撤销若干步再重做回到撤销前、改回原值时修改和标记消失、删除未保存的新增行不进入命令、命令符合 C02 且只含修改过的可写字段），实现前因缺少模块失败（`.reports/modules/frontend-page/vitest-edit-buffer-red.txt`），实现后 14 个通过（`vitest-edit-buffer-green.txt`）。全部前端测试见 T-FP-2 的结果。2026-10-30（G2 组，`batch2/config-ui`）：属性测试"撤销若干步后再重做"在 seed 1327463905 下失败（同一批次改明细备注、删主表行、改明细物料，撤销 1 步再重做 1 步后命令中两张单据的先后变了；撤销"删除新增行"后这一行排到同位置其他新增行之后也是同一原因）：未保存的行原来按 Map 的插入顺序列出，撤销、重做会把行重新插到最后。改为每行记先后号 `seq`，随行状态进撤销历史，列出时按它排序。加反例、新增行回原位、seed 1327463905 共 3 个用例，修改前失败、修改后通过；属性测试临时调到 5000 轮跑 3 次、30000 轮跑 1 次都通过。另：新增行中为空的数值字段在命令中写 null（FP-04），加 1 个用例。`edit-buffer.test.ts` 18 个通过。

### T-FP-2 页面渲染与原地表单

- 归属与目标：实现 FP-01–FP-03、FP-08、FP-10、FP-14，以及 Lookup、字典、高级查询和按钮。
- 前置输入：开始前 T-FP-1，`ShellApi` 用模拟实现。
- 负责范围：page 的 grid-adapter、renderers。
- 交付物：单表页和主从页；原地表单（24 列网格）；表格适配（服务端行模型、客户端行模型、逐行更新）。
- 接入责任：T-AS-3 注册到外壳；真实联调在 T-AS-7。
- 验收标准（模拟验证）：点击展开图标后表单在主表区原地显示，返回后滚动位置和选中行不变，明细区不变；双击单元格进入编辑；不可见字段不出现在列、表单和列工具面板中；查询、翻页后列宽、顺序、固定和显隐不变；按钮只按 `systemButtons` 和区域 `buttons` 显示，没有选中行时删除、复制和 `requiresSelection` 为 true 的业务按钮不可用，新增可用，没有 `save` 时整页只读；业务按钮的命令只带选中行的主键，`documents` 为空数组；成本单 D 的明细改了单价没保存、另有一张成本单 E 也改了没保存，选中 D 点"同步价格"：不提示保存，直接执行，命令中没有这些修改；成功后 D 中受影响的行显示后端返回的值，这些行没保存的修改丢弃，E 的修改仍在编辑缓冲中；命令失败时编辑缓冲不变。
- 状态与证据：进行中（页面运行时的模拟验证通过；界面行为还没有在浏览器中验证）。2026-10-29：通用页面 `frontend/src/modules/page/`，按页面编码打开（路由 `/page/:pageCode`，elegant-router 的 `src/views/page/[pageCode].vue` 是唯一的视图文件，不在菜单中显示；`index.ts` 导出 C11 的 `FrontendModule`），列、明细、按钮、规则都来自页面视图。`page-runtime.ts` 管页面行为、经 GridPort 驱动表格；`grid-adapter/`（`columns.ts`、`PageGrid.vue`、`LookupGrid.vue`）是唯一引用 AG Grid 的部分：主表服务端行模型、明细客户端行模型、逐行事务更新，列宽和固定用 initial 属性，关闭 AG Grid 自带的撤销，改动标记的颜色沿用旧系统 `MasterDetailPageV3.vue`；`renderers/`：`GenericPage.vue`（单表页和主从页，明细 Tab 或堆叠，分隔线可拖动）、`RecordForm.vue`（原地表单，24 列网格，返回、上一条、下一条）、`LookupDialog.vue`、`AdvancedSearchDialog.vue`（运算符与旧系统相同）、`CopyDialog.vue`、`ApprovalProgressDialog.vue`。字典按 `dictType` 读取一次，显示标签。模拟验证（`frontend/tests/page/buttons-config.test.ts` 等，用 contracts 的模拟实现）：按钮只按 `systemButtons` 和区域 `buttons` 显示，没有选中行时删除、复制和 `requiresSelection` 的按钮不可用、新增可用，没有 `save` 时整页只读；成本单 D（2550）和 E（2551）都有没保存的修改时选中 D 点"同步价格"：不提示保存，命令只带 D 的主键、`documents` 为空，成功后 D 受影响的行显示后端的值、这些行的修改丢弃，E 的修改保留；命令失败时编辑缓冲不变；字典。结果：`pnpm test` 8 个文件 401 个通过（`.reports/modules/frontend-page/vitest.txt`），`pnpm typecheck` 通过（`typecheck.txt`），`pnpm build` 通过（`build.txt`）。还没验证（要在浏览器中做）：点击展开图标后表单原地显示、返回后滚动位置和选中行不变；双击单元格进入编辑；不可见字段不在列工具面板中；查询、翻页后列宽、顺序、固定和显隐不变。E01、明细的 Playwright 用例已改为按 `/page/COST_PINGGU` 打开（`frontend/tests/e2e/e01.spec.ts`、`cost-detail.spec.ts`，断言不变，只按区域和列标识限定定位），这次没有运行。2026-10-30（T-OP-3）：`runOperation` 中前端还没有的明细行（按钮新增的行）按关联字段归到所属单据，不用后端生成的 `clientRowId` 作表格标识，明细区显示的单据有新增、删除的行时重新排列明细行；模拟验证 `tests/page/buttons-config.test.ts` 新增 2 个："同步采购价"（`requiresSelection` 为 false）没有选中行也能点、`selectedRows` 为空，结果中的行显示后端的值；选中 2550 点"由BOM生成明细"，删掉的 3 行从明细区去掉、新增的 208500、208501 出现，主表显示重算后的总成本。浏览器中没有验证。

### T-FP-3 预览、保存与局部刷新

- 归属与目标：实现 FP-05–FP-07、FP-12、FP-16。
- 前置输入：开始前 T-FP-1、T-FP-2。
- 负责范围：page 的 preview 和 page-runtime 的保存流程。
- 交付物：编辑后经 `ShellApi.calc` 预览；保存、局部刷新、错误定位；审批中和冻结状态的显示；修改被锁定的单据时弹出审批进度。
- 接入责任：与真实后端和真实 rules-core 的联调在 T-AS-7。
- 验收标准（模拟验证）：编辑后只刷新受影响的行；保存期间整页只读；成功后只更新有差异的行，新增行换成正式主键且行节点不变；失败或没有响应时保留全部修改并定位到字段，不自动重发；已提交审批时显示审批中，被冻结的单据整张只读（单表页为整行）；成本单 2550 被审批 203 锁定时，双击它的单价、删除它的明细或给它新增明细，都不进入编辑，弹出审批 203 的进度（C09 第 6 节样例：第 1 级系统管理员待处理，第 2 级还没到）；页面加载后 2551 才被锁定，修改 2551 后保存返回 FROZEN_BY_APPROVAL，弹出锁定它的审批的进度，页面上的修改保留；有未保存修改时离开页面前确认。
- 状态与证据：进行中（页面运行时的模拟验证通过；计算 Worker 只在构建产物中可用，界面上的双击、粘贴没有在浏览器中验证）。2026-10-29：预览 `preview.ts` 按 C07 第 2 节组装一张单据的 preview 请求（`old` 取已提交值），经 `ShellApi.calc` 求值，结果只用于显示；过渡的 ShellApi（`frontend/src/service/shell.ts`）用 rules-core 交付的 `createCalcWorkerClient`（`rules-core/dist/web/`），`pnpm build` 的产物中 Worker 和 WASM 已打包，开发服务器上 `rules-core/dist/web` 在工程之外、返回 403，预览提示不可用、编辑和保存照常（见 `.reports/modules/frontend-page/contract-gaps.md` 的接入事项，归 assembly）。模拟验证（`frontend/tests/page/save.test.ts`、`buttons-config.test.ts`）：E01 改 200680 的备注后保存，命令只含这一格，成功后逐行比对、只更新有差异的行，清空编辑缓冲；保存期间整页只读；新增明细保存后换成正式主键、表格行标识不变；结果中缺的行按主键补查；失败或没有响应时保留全部修改并按错误明细定位到行和字段，不自动重发；E20：D 提交审批、E 写入，D 整张显示正式数据（新增行移除、改价恢复）并冻结，E 按结果刷新；成本单 2550 被审批 203 锁定时改单价、删除明细、新增明细都不进入编辑，弹出审批 203 的进度（C09 第 6 节样例：第 1 级两个节点待处理，第 2 级还没到）；页面加载后 2551 才被锁定，保存返回 FROZEN_BY_APPROVAL 时弹出锁定它的审批，修改保留；编辑后只刷新预览结果中有变化的行；Worker 不可用时照常编辑；有未保存修改时标记页签（`tabs.setDirty`），刷新或关闭窗口前由 `beforeunload` 确认。结果见 T-FP-2。

### T-FP-4 配置原地替换与个人列配置

- 归属与目标：实现 FP-09、FP-11。
- 前置输入：开始前 T-FP-2。
- 负责范围：page-runtime 的配置变更处理、grid-adapter 的个人列状态。
- 交付物：收到 `config.changed` 后重新读取页面视图并原地替换；个人列配置的读写。
- 接入责任：真实推送的联调在 T-AS-7。
- 验收标准（模拟验证）：替换后滚动位置、选中行、展开的表单和正在输入的值不变；上层隐藏的列不能被个人配置设为显示；个人配置只保存改变的部分。
- 状态与证据：进行中（页面运行时的模拟验证通过；滚动位置要在浏览器中验证）。2026-10-29：页面运行时订阅本页面的 `config.changed`，收到后以后台请求重新读取页面视图和新版本的规则包，原地替换列、表单布局、按钮和规则（表格不重建，列宽、固定用 initial 属性，`maintainColumnOrder`），编辑缓冲保留；个人列配置 `personal.ts`：打开页面时读取，只应用页面视图中可见的列，"保存列配置"按钮只提交与上次保存（或页面默认）不同的表格，明细显示方式（Tab、堆叠）切换后单独保存，提示文字沿用旧系统 `useUserGridConfig.ts`。模拟验证（`frontend/tests/page/buttons-config.test.ts`）：推送 C10 样例后以后台请求读取页面视图和规则包 `COST_PINGGU/8`，QTY 改为不可编辑立即生效，选中行、展开的表单和正在输入的备注不变；个人配置中页面不可见的 FORM 不应用；只改了主表列宽时只提交主表；明细显示方式。真实推送要等 assembly 接上 `/ws`（开发代理还没转发 WebSocket，见 `.reports/modules/frontend-page/contract-gaps.md` 的接入事项）。结果见 T-FP-2。

### T-FP-5 复制

- 归属与目标：实现 FP-13。
- 前置输入：开始前 T-FP-1、T-FP-2。
- 负责范围：page 的复制对话框，以及编辑缓冲中的复制操作。
- 交付物：复制对话框（选择主表字段、明细行和明细字段）；主表区和明细区的复制。
- 接入责任：真实联调在 T-AS-7。
- 验收标准（模拟验证）：默认全选时，复制结果除主键外与源单据相同（含全部未删除的明细，明细的关联字段指向新主表行）；只勾选部分行或字段时只复制这些行，未勾选的字段为空；源单据有未保存的修改时带上修改后的值；计算字段复制后由预览重新计算，生成的命令中新单据和明细都是 `add` 且不含计算字段；撤销一次撤回整个复制。
- 状态与证据：模拟验证通过；2026-10-30 在 T-AS-7 中真实联调（浏览器、d_cg）发现并修复 1 个缺陷后通过（见本条最后一项），待独立复核。2026-10-29：`frontend/src/modules/page/copy.ts`、`renderers/CopyDialog.vue`，对照旧系统 `useWorkingSetStore.ts` 的 copyMasterRow、copyDetailRow：主表区复制一行时勾选主表字段和每个明细的行、字段，明细区复制时勾选行（默认是选中的行）和字段，默认全选；主键和关联字段留空，`erpRow.column` 设为本地值；复制当前显示的值，标为删除的行不复制，源单据明细没加载时先加载；新主表行在源行下方，明细行在最后一个选中行下方；整个复制是一个撤销步骤，复制后为新单据安排预览。模拟验证（`frontend/tests/page/copy-lookup.test.ts`）：E09 复制有 3 条原辅料明细的成本单 2550，只勾选 2 条、去掉备注：新单据 2 条明细，备注为空，其余与源单据相同（含没保存的改价 72），主键为空；命令中主表和明细都是 `add`，不含计算字段 TOTAL_COST、AMOUNT 和不可编辑的字段；撤销一次撤回整个复制，源单据的改价保留；明细区复制的位置。结果见 T-FP-2。
  - 2026-10-30（G5，T-AS-7 真实联调发现并修复）：在浏览器中复制成本单 2550、不勾"年需求量"，保存后新单据的 ANNUAL_QTY 为 0 而不是空（`.reports/batch2-20261030/g5-acceptance/as7-playwright-3.txt`）。原因：编辑缓冲生成命令时新增行为空的字段不写，后端按 WP-16 给为空的数值字段补 0，而 WP-16 规定复制出的行不补默认值。改法：`edit-buffer.ts` 的新增行记 `copied`，复制出的行为空的可写字段照写 null；`copy.ts` 的主表区、明细区复制都按 `copied` 新增（模块说明 FP-13 补了这一条）。`tests/page/copy-lookup.test.ts` 的 E09 改为命令中带 `MEMO: null`。结果：`pnpm exec vitest run tests/page` 6 个文件 49 passed，`pnpm test` 31 个文件 502 passed（`vitest-1.txt`），`pnpm typecheck` 通过，`pnpm lint:deps` 通过；浏览器用例 `frontend/tests/e2e/batch-d.spec.ts` 的复制一条通过（`as7-playwright-6.txt`）。复制对话框的界面已在浏览器中验证（勾选主表字段、明细行和明细字段）。

### T-FP-6 默认值、Lookup 扩展与对比显示

- 归属与目标：实现 FP-15。
- 前置输入：开始前 T-FP-2。
- 负责范围：page 的新增行默认值、Lookup 对话框和对比显示。
- 交付物：上述功能。
- 接入责任：真实联调在 T-AS-7。
- 验收标准：业务例子 E28、E29；模拟验证：多选 Lookup 回填为逗号连接的值；`fillBack` 为 false 时只读单元格也能打开且不改数据；按单元格值过滤时请求带 `filter`；查询响应的 `keywordSearch` 为 false 时对话框不显示搜索框；对比上升和下降的箭头、颜色与旧系统相同。
- 状态与证据：待联调（模拟验证通过，待独立复核；Lookup 对话框的界面没有在浏览器中验证）。2026-10-29：默认值（`fields.ts` 的 `newRowValues`，对照旧系统 `useWorkingSetStore.ts` 的 resolveColumnDefaultValue）：`static`、`builtin`（当前用户、部门、角色、时间）、`options`（下拉选第一个值，单元格用下拉选择），没有配置时数值为 0、其他为空；Lookup（`lookup.ts`、`renderers/LookupDialog.vue`，布局沿用旧系统 `LookupDialog.vue`）：打开时先用空关键字查询，`keywordSearch` 为 false 时不显示搜索框，`filter` 取当前行字段或单元格的值，多选用英文逗号连接，`fillBack` 为 false 时只读单元格也能打开、只有"关闭"；对比（`fields.ts` 的 `compareDisplay`，与旧系统 `useMetaColumns.ts` 的 renderCompareValue 相同）：上升红色 `#e53935` ↑、下降绿色 `#43a047` ↓，11px。模拟验证（`frontend/tests/page/copy-lookup.test.ts`）：E28 张三新增一行，CREATE_BY 显示张三且不可编辑，STATUS 默认"草稿"，命令中不带 CREATE_BY；E29 当前 3.80、历史 3.50 显示"↑0.30 (8.57%)"，历史为 0 时只显示差值；Lookup 回填和撤销、多选、单元格值过滤、`keywordSearch` 为 false、只查看。页面视图中还没有字段的 `default` 和对比的显示方式（契约缺口第 1、2 项，`.reports/modules/frontend-page/contract-gaps.md`），前端先按建议的写法实现，后端给出前 E28 的默认值只能按"数值为 0、其他为空"。结果见 T-FP-2。

### T-FP-7 汇总行

- 归属与目标：实现 FP-17。
- 前置输入：开始前 T-FP-2；C06 v18 的 `aggregate`、C05 v4。
- 负责范围：page 的 `summary.ts`、page-runtime 的汇总、grid-adapter 的底部固定行。
- 交付物：主表区、明细区底部的汇总行。
- 接入责任：页面上的汇总行要已发布的配置（seed 的 COST_PINGGU 已配），浏览器验证由合并后完成（T-AS-7）。
- 验收标准：模拟验证：成本核算主表的汇总等于列表的 `aggregates` 加上还没保存的修改（改数量、预览改总成本、新增一张单据、撤销），保存后按同样的筛选重新取汇总；成本单 2550 的原辅料金额为三行之和，改价后按预览的金额，标为删除的行不计入，新增行计入；汇总行按列的小数位显示、不能编辑、没有表单按钮。真实验证（浏览器）：打开成本核算，主表底部显示 14 个求和列的汇总，与 d_cg 上同样筛选的 SUM 相同；选中一张单据，原辅料、包材底部显示金额合计。
- 状态与证据：进行中（模拟验证通过；浏览器中没有验证）。2026-10-30（丙组，`batch1/summary`）：`frontend/src/modules/page/summary.ts`（对照旧系统 `useMasterGridBindings.ts` 的 `updatePinnedSumRow`、`usePageRules.ts` 的 `computeSumRow`、`DetailGridV3.vue` 的 `grandTotalRow`），`PageRuntime.summaryRow`、`refreshAggregates`，`PageGrid.vue` 主表和明细都用 `pinnedBottomRowData`。模拟验证 `frontend/tests/page/summary.test.ts` 2 个通过（`pnpm test` 30 个文件 498 个通过，`pnpm typecheck` 通过）。

### T-FP-8 页面一显示就带界面规则的效果

- 归属与目标：实现 FP-18。由旧系统 `usePageRules.ts` 的 `buildRowStyleCallback` 推出：GRID_STYLE 作为 `getRowStyle` 在渲染行时按行数据算样式，页面加载即显示，不需要编辑。
- 前置输入：C07 v6 第 3.1 节（显示求值，`purpose: display`）；rules-core 的 RC-11。
- 负责范围：page 的 preview（`buildDisplayRequest`）、view-model（显示求值的结果、`ruleView`）、page-runtime（何时做显示求值）、grid-adapter（行样式、单元格样式取 `ruleView`）。
- 交付物：主表每取到一块数据、单据的明细加载时做显示求值；保存、按钮成功、配置变更后重新做；单据有修改后改用预览的结果。
- 接入责任：用 assembly 已接好的 `ShellApi.calc`，不另接线。
- 验收标准：成本核算页加载后不编辑，MEMO 为"ERP未搭建BOM"的主表行就是红底，其他行不是；显示的仍是加载来的值；没有修改时不出校验提示；选中单据后明细行一显示就按界面规则不可编辑、必填；在已取到的块里滚动不再求值。
- 状态与证据：进行中——模拟验证和真实浏览器验证都已通过，待独立复核（工程约定第 7 节）后改为完成。2026-10-30（G1，worktree `batch2/rules-ui`，输出在 `.reports/batch2-20261030/g1-rules-ui/`）：
  - 模拟验证：`frontend/tests/page/display.test.ts` 3 个：主表一块数据取到后 2919（MEMO 为 ERP未搭建BOM）就是红底、显示的仍是加载来的值、没有规则提示、请求不带明细和修改；选中 2550 后硬脂酸镁的单价不可编辑、字体变灰、备注必填，其他行不受影响；备注改成 ERP未搭建BOM 后按预览变红，保存后按保存的值重新做显示求值仍是红底。`buttons-config.test.ts` 的预览用例改为只取 `purpose` 为 `operation` 的请求，"Worker 不可用"用例改为每次求值都失败（单据加载时的显示求值也经 Worker）。`pnpm typecheck` 通过，`pnpm test` 32 个文件 507 passed，`pnpm lint:deps` 没有违规（`frontend-*.log`）。
  - 真实浏览器（后端 8084 + d_cg、前端 9532、本机 Chrome，`e2e/rules-ui.spec.cjs`，`e2e/results.json`）：打开成本核算页不编辑，第一块 100 行中 MEMO 为 ERP未搭建BOM 的 2553、2555、2561、2563、2565、2569 都是红底（`rgb(255, 204, 204)`），其他行都不是，页面没有未保存修改、没有规则提示（截图 `e2e/01-加载即红底.png`）；显示求值向 Worker 发了 100 个求值请求，从第一个发出到最后一个回复 20–29 毫秒；在已取到的块里来回滚动，求值请求数不变（100 → 100）。
  - 没有验证：明细行的界面规则在浏览器中的效果（d_cg 目前没有发布明细的界面规则）；配置变更后重新做显示求值（只有模拟验证）。

### T-FP-9 新增、复制的成本单带上产品

- 归属与目标：实现 FP-15 中"`fillWritable` 字段写进命令"一项。由旧系统推出：成本核算主表产品ID（EDITABLE=0）配产品 Lookup（`cellEditorParams.lookupCode = costGoods`），点单元格即打开（`useLookupDialog.ts:79-98`，只看行能否编辑），回填产品名称、规格等不可编辑的列；新增、复制的行保存时提交全部字段（`useWorkingSetStore.ts:834-876`），`DynamicDataService.insert/update` 只跳过虚拟列，照样写库。
- 前置输入：C05 v5 的 `fillWritable`（config 的 `views.py` 计算，与 authz AZ-04 相同）；seed 的 `lookup.costGoods`、`lookup.costCustomer`、`lookup.costUser`，页面主表 GOODSID、CUSTOMID、BUSINESS_USER 的 Lookup，实体去掉 GOODSID、CUSTOMID 的 `editable: false`，保存操作的 `writableFields` 加上产品ID、客户ID 和它们的回填目标。
- 负责范围：page 的 `fields.ts`（`fieldEditable` 管能否填写，`fieldWritable` 管能否写进命令）、view-model。
- 交付物：新增行用产品 Lookup 选产品后保存，产品ID、产品名称等写库；复制出的成本单保存后产品ID 不变；已保存的成本单换产品时回填的字段一起保存。
- 接入责任：d_cg 要先建三个 Lookup 数据源视图（`.reports/batch3-20261030/h3-new-doc/建Lookup视图-待人工审核.sql`），再按合并后的代码把配置项写进 d_cg（同目录 `save_config.py`）。
- 验收标准：模拟验证：新增一行、产品 Lookup 选产品 392，命令的 `values` 带产品ID 和不可编辑的回填目标；复制 200721 只复制主表，命令带产品ID 392、产品名称；明细的物料名称照旧不进命令。真实验证（浏览器、d_cg）：新增成本单选产品 392 保存后库里产品ID 为 392，"由BOM生成明细"生成 BOM 的 11 行；复制 200721 保存后产品ID 仍是 392。

### T-FP-10 成本核算页的显示问题（批次 2 核对时记下的 5 处）

- 归属与目标：FP-06、FP-14、FP-17、FP-02、FP-09 的显示细节。来源：`.reports/batch2-20261030/g0-verify/findings.md` 场景 4b、5-2、8，`.reports/batch2-20261030/g5-acceptance/findings.md`。
- 负责范围：page 的 `failure.ts`（新）、page-runtime（`failed`、`announce`、`columnsLoaded`）、personal（`columnOrder`）、grid-adapter（`columns.ts`、`PageGrid.vue`）。
- 交付物：
  1. 保存被拒绝时顶部提示同样的话只出现一次，并列出涉及的行（明细用物料名称，主表用单据号和产品名称）；
  2. 汇总行的布尔列（"客户指定"）不画复选框；
  3. `cacheBlockSize` 只给主表、`groupDefaultExpanded` 只给明细，控制台不再有两条"not supported with the … row model"警告；
  4. 业务按钮返回 `unchanged` 时提示"<按钮名称>：没有需要修改的数据"；
  5. 配置变更后列的先后按页面视图（与刷新后相同），重新显示的列不再跑到最右边。
- 验收标准：模拟验证：`save.test.ts`（2919 那样同一条规则拒绝两行、两种文字和主表行）、`buttons-config.test.ts`（按钮 unchanged；QTY 设为不显示再改回后按页面视图重排；有个人列配置时按个人配置）、`summary.test.ts`（汇总行的布尔列）。真实验证（浏览器）：5 处都在成本核算页上看到。
