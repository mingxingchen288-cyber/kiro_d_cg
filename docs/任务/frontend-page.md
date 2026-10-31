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
- 状态与证据：进行中（模拟验证通过，T-AS-7 联调通过，待独立复核）。2026-10-29 按模块说明一次做完：编辑缓冲移到 `frontend/src/modules/page/edit-buffer.ts`（`views/cost-pinggu` 已删除），记录修改、新增行、删除标记、改动标记，撤销和重做按行记录修改前后的状态，表格和表单共用，`batch` 把 Lookup 回填、复制、粘贴合成一步；生成命令时只带可写字段（不带计算字段、主键、关联字段、`erpRow.column`、只读的 ERP 列），删除主表行时不列出明细；按钮结果中的行可以单独丢弃修改并从历史中去掉。视图模型 `view-model.ts` 合并正式数据、修改和预览结果，给出明细行顺序（新增行插在原位）、冻结、可编辑和标记。先写测试 `frontend/tests/page/edit-buffer.test.ts`（例子取成本单 2550、2551 和 E01 的 200680；fast-check：任意编辑序列全部撤销后回到初始状态、撤销若干步再重做回到撤销前、改回原值时修改和标记消失、删除未保存的新增行不进入命令、命令符合 C02 且只含修改过的可写字段），实现前因缺少模块失败（`.reports/modules/frontend-page/vitest-edit-buffer-red.txt`），实现后 14 个通过（`vitest-edit-buffer-green.txt`）。全部前端测试见 T-FP-2 的结果。2026-10-30（G2 组，`batch2/config-ui`）：属性测试"撤销若干步后再重做"在 seed 1327463905 下失败（同一批次改明细备注、删主表行、改明细物料，撤销 1 步再重做 1 步后命令中两张单据的先后变了；撤销"删除新增行"后这一行排到同位置其他新增行之后也是同一原因）：未保存的行原来按 Map 的插入顺序列出，撤销、重做会把行重新插到最后。改为每行记先后号 `seq`，随行状态进撤销历史，列出时按它排序。加反例、新增行回原位、seed 1327463905 共 3 个用例，修改前失败、修改后通过；属性测试临时调到 5000 轮跑 3 次、30000 轮跑 1 次都通过。另：新增行中为空的数值字段在命令中写 null（FP-04），加 1 个用例。`edit-buffer.test.ts` 18 个通过。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"待联调"改为"完成"：编辑缓冲在浏览器端到端中经真实后端保存、撤销，例如 `frontend/tests/e2e/e01.spec.ts:16`、`g0-1030.spec.ts:110`"场景 2 明细汇总行：标删除后……撤销恢复"（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）；"待独立复核"按用户规则（`.kiro/steering/测试范围.md`）不阻断完成，保持原样，没有改成已复核。

### T-FP-2 页面渲染与原地表单

- 归属与目标：实现 FP-01–FP-03、FP-08、FP-10、FP-14，以及 Lookup、字典、高级查询和按钮。
- 前置输入：开始前 T-FP-1，`ShellApi` 用模拟实现。
- 负责范围：page 的 grid-adapter、renderers。
- 交付物：单表页和主从页；原地表单（24 列网格）；表格适配（服务端行模型、客户端行模型、逐行更新）。
- 接入责任：T-AS-3 注册到外壳；真实联调在 T-AS-7。
- 验收标准（模拟验证）：点击展开图标后表单在主表区原地显示，返回后滚动位置和选中行不变，明细区不变；双击单元格进入编辑；不可见字段不出现在列、表单和列工具面板中；查询、翻页后列宽、顺序、固定和显隐不变；按钮只按 `systemButtons` 和区域 `buttons` 显示，没有选中行时删除、复制和 `requiresSelection` 为 true 的业务按钮不可用，新增可用，没有 `save` 时整页只读；业务按钮的命令只带选中行的主键，`documents` 为空数组；成本单 D 的明细改了单价没保存、另有一张成本单 E 也改了没保存，选中 D 点"同步价格"：不提示保存，直接执行，命令中没有这些修改；成功后 D 中受影响的行显示后端返回的值，这些行没保存的修改丢弃，E 的修改仍在编辑缓冲中；命令失败时编辑缓冲不变。
- 状态与证据：进行中（页面运行时的模拟验证通过；界面行为还没有在浏览器中验证）。2026-10-29：通用页面 `frontend/src/modules/page/`，按页面编码打开（路由 `/page/:pageCode`，elegant-router 的 `src/views/page/[pageCode].vue` 是唯一的视图文件，不在菜单中显示；`index.ts` 导出 C11 的 `FrontendModule`），列、明细、按钮、规则都来自页面视图。`page-runtime.ts` 管页面行为、经 GridPort 驱动表格；`grid-adapter/`（`columns.ts`、`PageGrid.vue`、`LookupGrid.vue`）是唯一引用 AG Grid 的部分：主表服务端行模型、明细客户端行模型、逐行事务更新，列宽和固定用 initial 属性，关闭 AG Grid 自带的撤销，改动标记的颜色沿用旧系统 `MasterDetailPageV3.vue`；`renderers/`：`GenericPage.vue`（单表页和主从页，明细 Tab 或堆叠，分隔线可拖动）、`RecordForm.vue`（原地表单，24 列网格，返回、上一条、下一条）、`LookupDialog.vue`、`AdvancedSearchDialog.vue`（运算符与旧系统相同）、`CopyDialog.vue`、`ApprovalProgressDialog.vue`。字典按 `dictType` 读取一次，显示标签。模拟验证（`frontend/tests/page/buttons-config.test.ts` 等，用 contracts 的模拟实现）：按钮只按 `systemButtons` 和区域 `buttons` 显示，没有选中行时删除、复制和 `requiresSelection` 的按钮不可用、新增可用，没有 `save` 时整页只读；成本单 D（2550）和 E（2551）都有没保存的修改时选中 D 点"同步价格"：不提示保存，命令只带 D 的主键、`documents` 为空，成功后 D 受影响的行显示后端的值、这些行的修改丢弃，E 的修改保留；命令失败时编辑缓冲不变；字典。结果：`pnpm test` 8 个文件 401 个通过（`.reports/modules/frontend-page/vitest.txt`），`pnpm typecheck` 通过（`typecheck.txt`），`pnpm build` 通过（`build.txt`）。还没验证（要在浏览器中做）：点击展开图标后表单原地显示、返回后滚动位置和选中行不变；双击单元格进入编辑；不可见字段不在列工具面板中；查询、翻页后列宽、顺序、固定和显隐不变。E01、明细的 Playwright 用例已改为按 `/page/COST_PINGGU` 打开（`frontend/tests/e2e/e01.spec.ts`、`cost-detail.spec.ts`，断言不变，只按区域和列标识限定定位），这次没有运行。2026-10-30（T-OP-3）：`runOperation` 中前端还没有的明细行（按钮新增的行）按关联字段归到所属单据，不用后端生成的 `clientRowId` 作表格标识，明细区显示的单据有新增、删除的行时重新排列明细行；模拟验证 `tests/page/buttons-config.test.ts` 新增 2 个："同步采购价"（`requiresSelection` 为 false）没有选中行也能点、`selectedRows` 为空，结果中的行显示后端的值；选中 2550 点"由BOM生成明细"，删掉的 3 行从明细区去掉、新增的 208500、208501 出现，主表显示重算后的总成本。浏览器中没有验证。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）："由BOM生成明细"已在浏览器中验证：`frontend/tests/e2e/g0-1030.spec.ts:376`"场景 5a"（生成 11 行明细、主表合计更新）、`:507`"场景 6"（不选行时不可用），第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`；双击进入编辑在多个浏览器用例中用到（例如 `batch-d.spec.ts:82`）。原地表单、返回后滚动和选中行、列工具面板、翻页后列状态仍没有浏览器用例（甲核对 A\*），状态不改。

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
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：真实推送已接上：开发代理加了 `ws: true`（`frontend/build/config/proxy.ts` 第 45 行，T-AS-7 缺陷 1），浏览器 `frontend/tests/e2e/batch-d.spec.ts:157`"管理员保存配置后，已打开的成本核算页无需刷新即生效"通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。滚动位置仍只有模拟验证（甲核对 A\*），状态不改。

### T-FP-5 复制

- 归属与目标：实现 FP-13。
- 前置输入：开始前 T-FP-1、T-FP-2。
- 负责范围：page 的复制对话框，以及编辑缓冲中的复制操作。
- 交付物：复制对话框（选择主表字段、明细行和明细字段）；主表区和明细区的复制。
- 接入责任：真实联调在 T-AS-7。
- 验收标准（模拟验证）：默认全选时，复制结果除主键外与源单据相同（含全部未删除的明细，明细的关联字段指向新主表行）；只勾选部分行或字段时只复制这些行，未勾选的字段为空；源单据有未保存的修改时带上修改后的值；计算字段复制后由预览重新计算，生成的命令中新单据和明细都是 `add` 且不含计算字段；撤销一次撤回整个复制。
- 状态与证据：模拟验证通过；2026-10-30 在 T-AS-7 中真实联调（浏览器、d_cg）发现并修复 1 个缺陷后通过（见本条最后一项），待独立复核。2026-10-29：`frontend/src/modules/page/copy.ts`、`renderers/CopyDialog.vue`，对照旧系统 `useWorkingSetStore.ts` 的 copyMasterRow、copyDetailRow：主表区复制一行时勾选主表字段和每个明细的行、字段，明细区复制时勾选行（默认是选中的行）和字段，默认全选；主键和关联字段留空，`erpRow.column` 设为本地值；复制当前显示的值，标为删除的行不复制，源单据明细没加载时先加载；新主表行在源行下方，明细行在最后一个选中行下方；整个复制是一个撤销步骤，复制后为新单据安排预览。模拟验证（`frontend/tests/page/copy-lookup.test.ts`）：E09 复制有 3 条原辅料明细的成本单 2550，只勾选 2 条、去掉备注：新单据 2 条明细，备注为空，其余与源单据相同（含没保存的改价 72），主键为空；命令中主表和明细都是 `add`，不含计算字段 TOTAL_COST、AMOUNT 和不可编辑的字段；撤销一次撤回整个复制，源单据的改价保留；明细区复制的位置。结果见 T-FP-2。
  - 2026-10-30（G5，T-AS-7 真实联调发现并修复）：在浏览器中复制成本单 2550、不勾"年需求量"，保存后新单据的 ANNUAL_QTY 为 0 而不是空（`.reports/batch2-20261030/g5-acceptance/as7-playwright-3.txt`）。原因：编辑缓冲生成命令时新增行为空的字段不写，后端按 WP-16 给为空的数值字段补 0，而 WP-16 规定复制出的行不补默认值。改法：`edit-buffer.ts` 的新增行记 `copied`，复制出的行为空的可写字段照写 null；`copy.ts` 的主表区、明细区复制都按 `copied` 新增（模块说明 FP-13 补了这一条）。`tests/page/copy-lookup.test.ts` 的 E09 改为命令中带 `MEMO: null`。结果：`pnpm exec vitest run tests/page` 6 个文件 49 passed，`pnpm test` 31 个文件 502 passed（`vitest-1.txt`），`pnpm typecheck` 通过，`pnpm lint:deps` 通过；浏览器用例 `frontend/tests/e2e/batch-d.spec.ts` 的复制一条通过（`as7-playwright-6.txt`）。复制对话框的界面已在浏览器中验证（勾选主表字段、明细行和明细字段）。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：剩下的只有独立复核，"待独立复核"按用户规则（`.kiro/steering/测试范围.md`）不阻断完成，保持原样，没有改成已复核。

### T-FP-6 默认值、Lookup 扩展与对比显示

- 归属与目标：实现 FP-15。
- 前置输入：开始前 T-FP-2。
- 负责范围：page 的新增行默认值、Lookup 对话框和对比显示。
- 交付物：上述功能。
- 接入责任：真实联调在 T-AS-7。
- 验收标准：业务例子 E28、E29；模拟验证：多选 Lookup 回填为逗号连接的值；`fillBack` 为 false 时只读单元格也能打开且不改数据；按单元格值过滤时请求带 `filter`；查询响应的 `keywordSearch` 为 false 时对话框不显示搜索框；对比上升和下降的箭头、颜色与旧系统相同。
- 状态与证据：待联调（模拟验证通过，待独立复核；Lookup 对话框已在浏览器中验证；E28、E29 还没有在浏览器中联调，页面视图的 `default`、对比显示方式未做）。2026-10-29：默认值（`fields.ts` 的 `newRowValues`，对照旧系统 `useWorkingSetStore.ts` 的 resolveColumnDefaultValue）：`static`、`builtin`（当前用户、部门、角色、时间）、`options`（下拉选第一个值，单元格用下拉选择），没有配置时数值为 0、其他为空；Lookup（`lookup.ts`、`renderers/LookupDialog.vue`，布局沿用旧系统 `LookupDialog.vue`）：打开时先用空关键字查询，`keywordSearch` 为 false 时不显示搜索框，`filter` 取当前行字段或单元格的值，多选用英文逗号连接，`fillBack` 为 false 时只读单元格也能打开、只有"关闭"；对比（`fields.ts` 的 `compareDisplay`，与旧系统 `useMetaColumns.ts` 的 renderCompareValue 相同）：上升红色 `#e53935` ↑、下降绿色 `#43a047` ↓，11px。模拟验证（`frontend/tests/page/copy-lookup.test.ts`）：E28 张三新增一行，CREATE_BY 显示张三且不可编辑，STATUS 默认"草稿"，命令中不带 CREATE_BY；E29 当前 3.80、历史 3.50 显示"↑0.30 (8.57%)"，历史为 0 时只显示差值；Lookup 回填和撤销、多选、单元格值过滤、`keywordSearch` 为 false、只查看。页面视图中还没有字段的 `default` 和对比的显示方式（契约缺口第 1、2 项，`.reports/modules/frontend-page/contract-gaps.md`），前端先按建议的写法实现，后端给出前 E28 的默认值只能按"数值为 0、其他为空"。结果见 T-FP-2。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：开头的"Lookup 对话框的界面没有在浏览器中验证"已不对，改为现状；状态仍为"待联调"。
    - Lookup 对话框：浏览器 `frontend/tests/e2e/g0-1030.spec.ts:376`"场景 5a"（产品 Lookup 选 392）、`batch7-page-display.spec.ts:56`（产品选择的表头是中文标题、产品ID 列宽 80）通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。Lookup 显示列的标题和宽度（甲核对第四节 B7）由第 7 批 PG 组做（没有单独的任务卡；提交 7d00696，C06 v22、C05 v6；报告 `.reports/batch7-20261030/pg-page-display/报告.md`）。
    - 页面视图没有字段的 `default`（甲核对第四节 B8）、对比的显示方式（B9），以及默认值"当前部门名称"取不到（B10）：未做，排在第 8 批。第 8 批已做：B8、B9 见 T-FP-18，B10 见 identity 的 T-ID-4。
    - "待独立复核"按用户规则（`.kiro/steering/测试范围.md`）不阻断完成，保持原样，没有改成已复核。
  - 2026-10-31 第 8 批 G5（`batch8/config-caps`）：B8、B9 已做，见 T-FP-18 和 config 的 T-CF-12（C05 v9：页面视图带 `default`、`compare.format`），上面"页面视图的 `default`、对比显示方式未做"和"后端给出前 E28 的默认值只能按'数值为 0、其他为空'"已不对。E28、E29 的写法在浏览器中的用例（`batch8-config-caps.spec.ts` 场景 2、3）合并后主代理运行通过（`e2e-6.txt`）。B10 归第 8 批 G4。

### T-FP-7 汇总行

- 归属与目标：实现 FP-17。
- 前置输入：开始前 T-FP-2；C06 v18 的 `aggregate`、C05 v4。
- 负责范围：page 的 `summary.ts`、page-runtime 的汇总、grid-adapter 的底部固定行。
- 交付物：主表区、明细区底部的汇总行。
- 接入责任：页面上的汇总行要已发布的配置（seed 的 COST_PINGGU 已配），浏览器验证由合并后完成（T-AS-7）。
- 验收标准：模拟验证：成本核算主表的汇总等于列表的 `aggregates` 加上还没保存的修改（改数量、预览改总成本、新增一张单据、撤销），保存后按同样的筛选重新取汇总；成本单 2550 的原辅料金额为三行之和，改价后按预览的金额，标为删除的行不计入，新增行计入；汇总行按列的小数位显示、不能编辑、没有表单按钮。真实验证（浏览器）：打开成本核算，主表底部显示 14 个求和列的汇总，与 d_cg 上同样筛选的 SUM 相同；选中一张单据，原辅料、包材底部显示金额合计。
- 状态与证据：进行中（模拟验证和浏览器验证通过；待独立复核）。2026-10-30（丙组，`batch1/summary`）：`frontend/src/modules/page/summary.ts`（对照旧系统 `useMasterGridBindings.ts` 的 `updatePinnedSumRow`、`usePageRules.ts` 的 `computeSumRow`、`DetailGridV3.vue` 的 `grandTotalRow`），`PageRuntime.summaryRow`、`refreshAggregates`，`PageGrid.vue` 主表和明细都用 `pinnedBottomRowData`。模拟验证 `frontend/tests/page/summary.test.ts` 2 个通过（`pnpm test` 30 个文件 498 个通过，`pnpm typecheck` 通过）。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：浏览器 `frontend/tests/e2e/g0-1030.spec.ts:69`"场景 1 主表汇总行"、`:110`"场景 2 明细汇总行"通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-FP-8 页面一显示就带界面规则的效果

- 归属与目标：实现 FP-18。由旧系统 `usePageRules.ts` 的 `buildRowStyleCallback` 推出：GRID_STYLE 作为 `getRowStyle` 在渲染行时按行数据算样式，页面加载即显示，不需要编辑。
- 前置输入：C07 v6 第 3.1 节（显示求值，`purpose: display`）；rules-core 的 RC-11。
- 负责范围：page 的 preview（`buildDisplayRequest`）、view-model（显示求值的结果、`ruleView`）、page-runtime（何时做显示求值）、grid-adapter（行样式、单元格样式取 `ruleView`）。
- 交付物：主表每取到一块数据、单据的明细加载时做显示求值；保存、按钮成功、配置变更后重新做；单据有修改后改用预览的结果。
- 接入责任：用 assembly 已接好的 `ShellApi.calc`，不另接线。
- 验收标准：成本核算页加载后不编辑，MEMO 为"ERP未搭建BOM"的主表行就是红底，其他行不是；显示的仍是加载来的值；没有修改时不出校验提示；选中单据后明细行一显示就按界面规则不可编辑、必填；在已取到的块里滚动不再求值。
- 状态与证据：进行中——模拟验证和真实浏览器验证都已通过，待独立复核（工程约定第 7 节）。2026-10-30（G1，worktree `batch2/rules-ui`，输出在 `.reports/batch2-20261030/g1-rules-ui/`）：
  - 模拟验证：`frontend/tests/page/display.test.ts` 3 个：主表一块数据取到后 2919（MEMO 为 ERP未搭建BOM）就是红底、显示的仍是加载来的值、没有规则提示、请求不带明细和修改；选中 2550 后硬脂酸镁的单价不可编辑、字体变灰、备注必填，其他行不受影响；备注改成 ERP未搭建BOM 后按预览变红，保存后按保存的值重新做显示求值仍是红底。`buttons-config.test.ts` 的预览用例改为只取 `purpose` 为 `operation` 的请求，"Worker 不可用"用例改为每次求值都失败（单据加载时的显示求值也经 Worker）。`pnpm typecheck` 通过，`pnpm test` 32 个文件 507 passed，`pnpm lint:deps` 没有违规（`frontend-*.log`）。
  - 真实浏览器（后端 8084 + d_cg、前端 9532、本机 Chrome，`e2e/rules-ui.spec.cjs`，`e2e/results.json`）：打开成本核算页不编辑，第一块 100 行中 MEMO 为 ERP未搭建BOM 的 2553、2555、2561、2563、2565、2569 都是红底（`rgb(255, 204, 204)`），其他行都不是，页面没有未保存修改、没有规则提示（截图 `e2e/01-加载即红底.png`）；显示求值向 Worker 发了 100 个求值请求，从第一个发出到最后一个回复 20–29 毫秒；在已取到的块里来回滚动，求值请求数不变（100 → 100）。
  - 没有验证：明细行的界面规则在浏览器中的效果（d_cg 目前没有发布明细的界面规则）；配置变更后重新做显示求值（只有模拟验证）。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"："待独立复核"按用户规则（`.kiro/steering/测试范围.md`）不阻断完成，保持原样，没有改成已复核。本条"没有验证"的两项不用做：d_cg 没有发布明细的界面规则，前台没有这条路径，按用户规则不另做（`.kiro/steering/测试范围.md`："我前台只开放了xx功能……"）；配置变更后重新做显示求值有模拟验证。浏览器 `frontend/tests/e2e/g0-1030.spec.ts:295`"场景 4a 红底"通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。

### T-FP-9 新增、复制的成本单带上产品

- 归属与目标：实现 FP-15 中"`fillWritable` 字段写进命令"一项。由旧系统推出：成本核算主表产品ID（EDITABLE=0）配产品 Lookup（`cellEditorParams.lookupCode = costGoods`），点单元格即打开（`useLookupDialog.ts:79-98`，只看行能否编辑），回填产品名称、规格等不可编辑的列；新增、复制的行保存时提交全部字段（`useWorkingSetStore.ts:834-876`），`DynamicDataService.insert/update` 只跳过虚拟列，照样写库。
- 前置输入：C05 v5 的 `fillWritable`（config 的 `views.py` 计算，与 authz AZ-04 相同）；seed 的 `lookup.costGoods`、`lookup.costCustomer`、`lookup.costUser`，页面主表 GOODSID、CUSTOMID、BUSINESS_USER 的 Lookup，实体去掉 GOODSID、CUSTOMID 的 `editable: false`，保存操作的 `writableFields` 加上产品ID、客户ID 和它们的回填目标。
- 负责范围：page 的 `fields.ts`（`fieldEditable` 管能否填写，`fieldWritable` 管能否写进命令）、view-model。
- 交付物：新增行用产品 Lookup 选产品后保存，产品ID、产品名称等写库；复制出的成本单保存后产品ID 不变；已保存的成本单换产品时回填的字段一起保存。
- 接入责任：d_cg 要先建三个 Lookup 数据源视图（`.reports/batch3-20261030/h3-new-doc/建Lookup视图-待人工审核.sql`），再按合并后的代码把配置项写进 d_cg（同目录 `save_config.py`）。
- 验收标准：模拟验证：新增一行、产品 Lookup 选产品 392，命令的 `values` 带产品ID 和不可编辑的回填目标；复制 200721 只复制主表，命令带产品ID 392、产品名称；明细的物料名称照旧不进命令。真实验证（浏览器、d_cg）：新增成本单选产品 392 保存后库里产品ID 为 392，"由BOM生成明细"生成 BOM 的 11 行；复制 200721 保存后产品ID 仍是 392。
- 状态与证据：进行中（模拟验证通过；真实验证在浏览器、d_cg 上通过；待独立复核）。2026-10-30（H3，`batch3/new-doc`，输出在 `.reports/batch3-20261030/h3-new-doc/`）：
  - 模拟验证：前端 `tests/page/product-lookup.test.ts` 4 个（新增选产品 392、复制 200721、已保存的单据重新选产品、明细物料名称不进命令），`tests/config/table-fields.test.ts` 改用不是回填目标的字段并加 1 个回填目标用例；后端 `tests/config/test_views.py` 2 个（seed 的 fillWritable、角色锁住产品ID 时回填目标不可写），authz、config 的用例按新 seed 更新。前端 34 个文件 526 passed，后端 not oracle and not redis 1209 passed，lint-imports 5 kept。
  - 没有在浏览器验证：d_cg 中没有 V_COST_GOODS_LOOKUP、V_COST_CUSTOMER_LOOKUP、V_COST_USER（只在 cmx），按 d_cg 表结构校验 seed 时这三个 Lookup 报"表或视图不存在"（`validate_seed.out.txt`；另一条"部门 18 不存在"是 d_cg 已有的审批流，main 的 seed 同样报，`validate_seed_main.out.txt`）；另外 C05 改了，页面视图是存进 PF_CONFIG_ITEM 的派生项，用新代码保存配置后 main 的后端读不了。所以配置没有写进 d_cg。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：浏览器 `frontend/tests/e2e/g0-1030.spec.ts:376`"场景 5a"（新建成本单选产品 392 保存、由BOM生成 11 行明细）、`:456`"场景 5b"（复制 200721 只要主表，保存后产品ID、产品名称都在）通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`），覆盖验收标准的真实验证两项。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

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
- 状态与证据：模拟验证和真实浏览器验证都通过，待独立复核。2026-10-30（H3，`batch3/new-doc`，后端 8085 + d_cg、前端 9533、本机 Chrome，脚本和结果在 `.reports/batch3-20261030/h3-new-doc/e2e/`）：
  - 第 1 处：2919 原辅料比沙可啶、一水乳糖（200目）单价都改后保存，422 RULE_REJECTED 两条明细，顶部提示"每片含量必填且必须大于0（原料/辅料 比沙可啶、一水乳糖（200目））"，两格标红（`t2b.out.json`、`t2b-reject-two.png`）；只改一行时提示"…（原料/辅料 一水乳糖（200目））"（`t2a`）。都刷新放弃，没有写库。
  - 第 2 处：2919 原辅料汇总行的"客户指定"格为空、没有复选框，普通行有复选框（`t2a.out.json`、`t2b.out.json`）。
  - 第 3 处：打开成本核算、选单据、保存的全程，控制台没有"is not supported with the … row model"（`t2a.out.json` 的 console；只剩 AG Grid 授权过期的提示）。
  - 第 4 处：200204（产品ID 0、没有明细）点"由BOM生成明细"，返回 unchanged，提示"由BOM生成明细：没有需要修改的数据"（`t2c.out.json`、`t2c-bom-unchanged.png`）。
  - 第 5 处：配置变更是模拟的——没有改 d_cg 的配置，Playwright 接管页面的实时连接，注入两条 config.changed，第一次把页面视图中年需求量设为不可见再交给页面，第二次原样交给页面；页面走真实的重新读取路径。年需求量先消失，再回到第 8 列（注册证号之后），与开始时、刷新后都相同，没有到最后一列（第 44 列）（`t2d.out.json`、`t2d-2-restored.png`）。
  - 核对后只读查询（`q09-浏览器核对后.out.txt`）：T_COST_PINGGU 700 行、最大 200726，明细 7926 行、最大 208527，2919 两行单价仍为 2489.725、26，200204 仍没有明细，冻结 0 条，配置代号 4225 没变。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：剩下的只有独立复核，"待独立复核"按用户规则（`.kiro/steering/测试范围.md`）不阻断完成，保持原样，没有改成已复核。

### T-FP-11 复制时勾选的字段都写进新行

- 归属与目标：FP-13 中"勾选的字段不论能不能编辑都写进新行"一项（C02 v8 的 `copyOf`，后端 WP-21）。来源：旧系统 `copy-row-fields.ts` 第 23–29 行复制源行全部字段、`useWorkingSetStore.ts` 第 834–876 行新增行提交全部字段；现象见 `.reports/batch3-20261030/v3-verify/findings.md` 观察 2-1（复制 200721 后币种、项目号为空）；用户 2026-10-30 同意按旧系统做。
- 前置输入：contracts 的 `MasterAdd`、`DetailAdd` 加 `copyOf`；write-pipeline 的 T-WP-10。
- 负责范围：page 的 `copy.ts`（`originOf`）、`edit-buffer.ts`（`PendingRow.origin`、`copyOrigin`、命令中的 `copyOf` 和不可写的复制字段）、`fields.ts`（`fieldCopyable`）、`view-model.ts`（`createBuffer` 的 `copyable`）。
- 验收标准：模拟验证：E09 复制 2550 时命令带 `copyOf` 和不可编辑的创建人、明细的物料名称，不带计算字段和产品名称（没有 `erpRow` 的实体的 ERP 列）；复制 200721 只复制主表时命令带 `copyOf: 200721` 和项目号。业务例子（浏览器、d_cg）：复制 200721 只复制主表，保存后新单据的币种是"人民币"、项目号与源单据相同（源为空则为空），产品等字段照旧；删掉这张单据。
- 状态与证据：模拟验证和浏览器业务例子通过（2026-10-30，P 组，`batch4/pipeline-fixes`）：`tests/page/copy-lookup.test.ts`、`tests/page/product-lookup.test.ts`。浏览器（后端 8084 + d_cg、前端 9532，`.reports/batch4-20261030/p-pipeline-fixes/e2e/p2.out.json`、`p2-saved.png`）：复制 200721 只复制主表并保存，新单据 200834 的币种"人民币"、项目号为空（源为空）、产品ID 392、产品名称与源相同，页面与单据读取接口一致；随后删掉（之后读取为 404）。

### T-FP-12 保存、按钮之后显示重新读到的值

- 归属与目标：FP-06、FP-14 中"写入的行按主键重读再显示"。现象：点"由BOM生成明细"后，明细的"客户指定"显示不确定状态、"额外投料量"显示 0.00、包材"参考采购价""最后采购数量"为空；新单据保存后"币种"为空；重新打开单据后才正确（`.reports/batch3-20261030/v3-verify/findings.md` 观察 1-1、2-1）。原因：命令结果的行取自后端手里的数据，不重新查库（WP-12），只在读取视图中的字段和数据库端默认值到不了页面。来源：旧系统保存后后端重查主表行（`DynamicDataService.java` 第 1232–1255 行）、前端明细有改动时重读（`useWorkingSetStore.ts` 第 1047–1076 行），按钮执行后 `reloadMasterRow` + `loadDetailData`（`runtime/useRuntimeActions.ts` 第 75–110 行）；用户 2026-10-30 同意按旧系统做。
- 前置输入：C09 第 4 节的按主键取行（`POST /api/pages/{pageCode}/rows/by-keys`）。
- 负责范围：page 的 `page-runtime.ts`（`applySaveResult` 把结果中写入的行并入补查，`runOperation` 的 `rereadResultRows`）。
- 交付物：命令成功后，结果中写入的行（被冻结的、删除的除外）按实体各一个 `rows/by-keys` 请求重读，读到的值登记为正式数据再显示。不在命令事务里，命令的 SQL 条数不变（WP-10）。用 `rows/by-keys` 而不是单据加载接口：两者经同一个视图、同样的字段读取；按主键只读命令写到的行，每个实体一个请求，一次保存几张单据也不多请求，明细的显示顺序（新增行保存后留在原位，FP-06）不被单据加载的排序打乱。
- 验收标准：模拟验证：保存新单据后按新主键重读主表行，库里的默认值显示出来；按钮新增的明细按主键重读，显示视图中的物料名称。业务例子（浏览器、d_cg）：新建一张产品 392 的成本单（产品 Lookup 选 392）保存后币种马上显示"人民币"；点"由BOM生成明细"后客户指定为未勾选、额外投料量为空、包材参考采购价显示 0.10、0.07 等；最后删掉这张单据。
- 状态与证据：模拟验证和浏览器业务例子通过（2026-10-30，P 组，`batch4/pipeline-fixes`）：`tests/page/save.test.ts` 的"保存成功后按主键重读结果中写入的行""按钮成功后按主键重读结果中写到的行再显示"。浏览器（后端 8084 + d_cg、前端 9532，`.reports/batch4-20261030/p-pipeline-fixes/e2e/p3.out.json` 和 `p3-*.png`）：新建产品 392 的成本单 200835，命令结果中币种为空，保存后重读，页面马上显示"人民币"；"由BOM生成明细"后按实体重读原辅料 5 行、主表、包材 6 行，客户指定都是未勾选（不再是不确定状态），包材参考采购价 0.10、0.07、0.17、4.16、0.48，最后采购数量也显示，与重新打开后逐格相同；随后删掉。
  - 与任务描述不同的一处：额外投料量在按钮之后和重新打开后都是 0.00，不是"为空"。库里写的就是 0：写入管道对按钮新增的行也按 WP-16 把没配默认值的数值字段补 0；旧 P_COST_BOM_INSERT 不写这一列（为空）。要改在 `merge.IntentMerger`（审批通过的待审新增行也走这里，要按来源区分），没改，见 P 组汇报。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：本条"与任务描述不同的一处"（按钮之后额外投料量显示 0.00、不是空）已由 write-pipeline T-WP-11 改掉：浏览器 `frontend/tests/e2e/g0-1030.spec.ts:376`"场景 5a"断言由BOM生成的明细额外投料量的格子为空（第 367 行）、读回的数据中为 null（第 448 行），第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`。

### T-FP-13 测试模式下关掉表格的列虚拟化（端到端测试）

- 归属与目标：FP-02 的"列虚拟化（测试模式专用）"。上一批重做端到端测试时试过视口 5000×1200：成本核算主表 43 列只渲染 26 列，明细 18 列全部渲染，工具 `cell()` 要在列不在视野里时横向逐段滚动（`.reports/batch4-20261030/e-e2e/findings.md` 第 4 条）。用户 2026-10-30 同意"只在 `vite --mode test` 下关掉列虚拟化（回归也要改成用 `build:test` 构建才生效）"。
- 前置输入：AG Grid 35 的 `suppressColumnVirtualisation`（只在建表时读）；`.env.test` 与 `.env.prod` 的取值相同，两种构建只差 `import.meta.env.MODE`。
- 负责范围：page 的 `grid-adapter/columns.ts`（开关）、`PageGrid.vue`、`LookupGrid.vue`；端到端用到列的另外两处表格一起改：config 的 `components/grid-columns.ts`、`ConfigGrid.vue`，approval 的 `renderers/grid-theme.ts`、`ApprovalViewGrid.vue`（前端模块之间不能互相导入，各放一份开关）；`frontend/package.json` 的 `test:e2e`；`frontend/tests/e2e/` 的 `support.ts`、`columns.spec.ts`、`g0-1030.spec.ts`、`batch-d.spec.ts`、`playwright-base.ts`。系统管理（人员、部门）、待办、审批进度的列固定，1600 宽放得下，不改。
- 交付物：测试模式下上面这些表格一次渲染全部列，正式模式不变；`pnpm test:e2e` 先跑 `pnpm build:test`；`cell()` 不再横向滚，去掉 `headerShown`（改用 `header()` 在不在），`scrollToColumn` 只在悬停列头前按位置滚一次，g0 的汇总行一次读完、求和列不横向滚；`columns.spec.ts` 断言全部渲染。
- 验收标准：测试模式 1600×900 下主表 43 列、原料/辅料和包材各 18 列全部渲染，并与页面视图的可见字段逐个对上；正式构建仍开着列虚拟化；测试模式构建由后端托管时接口地址仍是页面的 origin、AG Grid 授权照旧；回归、开发两种方式全量通过；记录前后用时。
- 状态与证据：待独立复核（2026-10-30，V 组，`batch5/column-virtual`，提交 f170349 和本卡所在的提交；原始输出在 `.reports/batch5-20261030/v-column-virtual/`）。
  - 测试模式：回归、开发全量各 30 条通过（`after-build-1.txt` 4.4m、`after-dev-3.txt` 4.5m；`after-dev-2.txt` 那次 E01 第二次打开页面时 Vite 代理转发 `/api/me` 报 `read ECONNRESET`、页面停在启动画面，与列虚拟化无关，重跑通过）。列数 43/43、18/18、18/18。
  - 正式模式：`pnpm build` 产物里三处开关都是 `!1`（测试模式 `!0`，`flag-build-prod.txt`、`flag-build-test.txt`）；在正式产物上跑 `columns.spec.ts`，主表只渲染 9/43 列、明细 9/18 列，用例失败（预期如此，`run-columns-prod-build.txt`）。两种产物的接口地址都是 `window.location.origin`、没有 `/proxy-default`，授权字符串都是 538 个字符（`origin-license-*.txt`，只报长度）。
  - `pnpm test` 35 个文件 535 个通过，`pnpm typecheck`、`pnpm lint:deps` 通过。
  - 用时：全量（4 个 worker）回归 改前 4.0m / 4.1m、改后 4.4m / 5.5m；开发 改前 4.4m / 6.0m、改后 4.4m / 4.5m。同一份代码两次相差 1.4–1.6 分钟（机器负载 3%–78%，别的组也在用），总用时看不出变化。单 worker 跑 4 条（`*-w1-*.txt`）：g0 场景 1 汇总行 改前 9.3 / 8.1s → 改后 6.4 / 6.6s；E01 改前 19.6 / 14.4s → 改后 16.3 / 16.5s；cost-detail 两条情况相同。不再逐列滚动的用例变快，反复打开主表、保存重读的用例可能每条多 1–2s（全部列都渲染，格子多了），幅度小于负载的波动。
  - d_cg 只读核对（`q01-结束后核对.out.txt`）：没有 PF_TEST 残留，冻结 0，审批仍是原来的 6 条。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：剩下的只有独立复核，"待独立复核"按用户规则（`.kiro/steering/测试范围.md`）不阻断完成，保持原样，没有改成已复核。

### T-FP-14 主表右键的"自定义导出"

- 归属与目标：FP-19。用户 2026-10-30 同意"通用页面加'自定义导出'按钮（旧系统成本核算页有，按钮权限 自定义导出:cost-pinggu-export）"，行为同旧系统。来源：旧系统 `cost-web/src/v3/composables/meta-v3/useGridContextMenu.ts` 第 367–406 行、`useCustomExport.ts`、`cost-web/src/service/api/export-config.ts` 第 47–59 行和第 96–110 行。
- 前置输入：C09 第 4 节的 `GET /api/pages/{pageCode}/exports`、`POST /api/pages/{pageCode}/export`（`mode: config`，queries-export 的 QE-06）；d_cg 上的导出配置 cost-pinggu-export（seed 提交 616f14a）。
- 负责范围：page 的 `export.ts`（新文件：子菜单项、导出请求、文件名、浏览器下载）、`page-runtime.ts`（`ui.exports`、`loadExports`、`exportMenu`、`exportFile`）、`grid-adapter/PageGrid.vue`（主表右键菜单）；contracts 随 C11 v2 改 `shell.ts`（`DownloadedFile`）、`api.ts`（`exports` 可标为后台请求）、`fakes/http.ts`（下载走路由表）；`service/platform.ts`（读 `Content-Disposition`）；后端只加测试辅助 `backend/tests/e2e/xlsx_sheets.py`（读下载文件的工作表名称，只读本地文件）。
- 交付物：主表右键菜单在区域按钮之后有分隔线和"自定义导出"子菜单，每个可用的导出配置有"导出当前""导出所有"两项；导出当前带主表当前的筛选、高级查询和排序，导出所有都不带；浏览器下载的文件名取 `Content-Disposition`，取不到为 export.xlsx。
- 验收标准：模拟验证：子菜单项、没有可用配置时为空、配置变更后以后台请求重新取、导出当前的请求带当前条件、导出所有的请求不带条件、文件名解析。业务例子（浏览器、d_cg，正式用例 `frontend/tests/e2e/export-menu.spec.ts`）：admin 打开成本核算，按单据号筛选 2550，主表右键 → 自定义导出 → "物料成本核算表导出 - 导出当前"，下载到"物料成本核算表导出.xlsx"，文件里是"物料成本核算""明细_2550"两张工作表。
- 状态与证据：模拟验证和浏览器业务例子通过，待独立复核（2026-10-30，FP 组，`batch6/export-menu`，本卡所在的提交；原始输出在 `.reports/batch6-20261030/fp-export-menu/`）。
  - 模拟验证：`frontend/tests/page/export.test.ts` 7 个通过（`vitest-export.txt`）；`tests/contracts/fakes.test.ts` 的导出用例改为核对文件和响应头。`pnpm test` 37 个文件 545 个通过（`pnpm-test.txt`），`pnpm typecheck`、`pnpm lint:deps` 通过（`lint-deps.txt`）。
  - 浏览器（`pnpm build:test` 后由后端 8091 托管，d_cg）：`export-menu.spec.ts` 跑两次，每次 setup 3 个加本用例共 4 个通过（`e2e-1.txt`、`e2e-2.txt`，用例 8.6s）：导出请求为 `scope: current`、`filterModel.DOCID` 为 2550，提示"导出已开始"，下载文件名"物料成本核算表导出.xlsx"，工作表"物料成本核算""明细_2550"。只读，不改数据。
  - 与旧系统的两处差别（FP-19 末项）：提示"导出已开始"只出现一次（旧系统开始 info、下载后 success 各一次）；导出当前同时带高级查询（旧系统只带表格的筛选和排序）。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：独立复核按用户规则（`.kiro/steering/测试范围.md`）不阻断完成，保持原样。

### T-FP-15 按地址定位单据；查看审批进度、进度弹窗到审批详情
- 归属与目标：FP-20、FP-21（FP-16 的弹窗加"查看审批详情"），C11 v3、C09 v14。盘点（`.reports/inventory-20261030/甲-任务卡核对.md` 第四节 B2、B3，`乙-旧系统功能对照.md` 第 2.8、2.9 节），用户 2026-10-30 回复"其它无异议"同意按旧系统补。来源：旧系统 `approval-notification-center.vue` 第 141–158 行（`focusId`）、`useWorkingSetStore.ts` 第 255–262 行、`MasterDetailLayoutV3.vue` 第 428–460 行和第 816 行、`ApprovalActionGroup.vue` 第 16、23 行。
- 前置输入：C09 第 4 节 `rows/by-keys`；approval T-AP-9 的 `box=record`；frontend-shell T-FS-3 的 `tabs.open` 带查询参数。
- 负责范围：`renderers/PageRoute.vue`（读 `record`）、`GenericPage.vue`（工具栏"查看审批进度"、"只显示单据 X / 显示全部"）、`ApprovalProgressDialog.vue`（标题、状态、"查看审批详情"）、`page-runtime.ts`（`focus`、`clearFocus`、`fetchFocused`、`showRecordApprovals`、`openApprovalDetail`，`FrozenState.title`）、`approval-progress.ts`（审批状态文字）、`grid-adapter/PageGrid.vue`（选中定位的行）。没有改 `fields.ts`、`grid-adapter/columns.ts`、`LookupGrid.vue`、`AdvancedSearchDialog.vue`。
- 交付物：`/page/{pageCode}?record={主键}` 打开后只显示、选中这张单据并显示明细；工具栏"查看审批进度"；审批进度弹窗每个审批有"查看审批详情"。
- 验收标准：模拟验证（`tests/page/approval-progress.test.ts`）：定位时主表按主键取一行、返回要选中的行、去掉地址中的 `record`，再查询照常、"显示全部"从第一页查；查看审批进度按单据查、显示进行中的、没有进行中的显示最近一个、没有时"暂无审批记录"、没选中时提示；"查看审批详情"打开审批详情页签并关闭弹窗；冻结时的弹窗标题不变。业务例子：见 frontend-approval T-FA-2 的 `batch7-approval.spec.ts`（第 1、5、6 步）。
- 状态与证据：模拟验证和浏览器业务例子通过，待独立复核（2026-10-31，AP 组，`batch7/approval-history`，本卡所在的提交；原始输出在 `.reports/batch7-20261030/ap-approval/`，`pnpm-test.txt`、`e2e-2.txt`）。
  - 与旧系统的差别：定位用按主键取行（旧系统加查询条件）；"查看审批进度"是工具栏上一个按钮，不做成"送审"下拉（新平台不做送审、撤销送审），每个页面都有（旧系统授给全部业务角色）；进度弹窗不显示修改内容，从"查看审批详情"进审批详情页（旧系统是同一个对话框）。

### T-FP-16 高级查询按旧系统：预置条件、值用 Lookup 选

- 归属与目标：FP-22；同时改 contracts（C06 v23、C05 v7 的 `searchable`）、config（页面视图带 `searchable`，CF-03）、frontend-config（"表与列"的"查询"，FC-13）和 seed。用户 2026-10-30 回复"其它无异议"同意按旧系统补（盘点 `.reports/inventory-20261030/乙-旧系统功能对照.md` 第 1.2 节"高级查询"、第 2.11 节）。来源：旧系统 `cost-web/src/v3/components/AdvancedSearchDialog.vue`、`composables/meta-v3/useAdvancedSearch.ts`（第 248 行只列可见且勾了"查询"的列，第 301–309 行默认运算符）、`advanced-search-values.ts`、配置页 `SectionTables.vue` 第 79–82 行；cmx `T_COST_COLUMN_METADATA.SEARCHABLE`。
- 前置输入：C09 第 4 节 `ListRequest.advanced`（格式不变，后端不改）；FP-15 的 Lookup 对话框；cmx 旧列配置的"查询"标记（`.reports/batch7-20261030/qs-advanced-search/02-旧列查询标记.out.txt`、`03-旧列未勾查询.out.txt`）。
- 负责范围：后端 `contracts/types.py`（`FieldSetting.searchable`、`ViewField.searchable`）、`config/views.py`、`config/page_view.py`；seed `page.COST_PINGGU.json`、`page.GOODS_PRICE_MANAGE.json` 只加 `searchable: true`；前端 `contracts/page-view.ts`、`modules/config/core/types.ts`、`views/table-fields.ts`、`views/TableFieldsCard.vue`、`modules/page/advanced-search.ts`、`page-runtime.ts`（`openSearchLookup`）、`renderers/AdvancedSearchDialog.vue`。
- 交付物：高级查询对话框一打开就列出预置条件，填值即勾上，有 Lookup 的字段能用 Lookup 选值（IN、NOT IN 时多选，追加去重）；条件可以隐藏、在"显示字段"中恢复；"添加条件"保留。"表与列"有"查询"勾选列。
- 验收标准：模拟验证：预置条件的范围和顺序、默认运算符、填值勾上和清空取消、明细预置条件在同一组、隐藏和重新打开保留、重置；客户ID 选 IN 后两次用 Lookup 选值追加、请求带 `in`；"表与列"读写 `searchable`；seed 的页面视图带 `searchable`。业务例子（浏览器、d_cg，正式用例 `frontend/tests/e2e/advanced-search.spec.ts`）：admin 打开成本核算点"高级查询"，预置条件有产品名称等，产品名称填"片"后查出的单据与列头筛选"产品名称含片"相同；客户ID 用 Lookup 选两个客户（IN），查出的单据只属于这两个客户。只读。
- 状态与证据：进行中（模拟验证通过；2026-10-31 主代理把 seed 的 `searchable` 经配置接口写进 d_cg 后，浏览器用例 `advanced-search.spec.ts` 两条在整套端到端中通过，`.reports/batch7-20261030/merge/e2e-6.txt`；待独立复核）。（2026-10-30，第 7 批 QS 组，`batch7/advanced-search`；原始输出在 `.reports/batch7-20261030/qs-advanced-search/`）。
  - 模拟验证：前端 `tests/page/advanced-search.test.ts` 5 个、`tests/config/table-fields.test.ts` 新增 1 个（另 3 个按 seed 多了 `searchable` 改了期望），`copy-lookup.test.ts` 的 E30 改为条件已勾上；`pnpm test` 38 个文件 551 个通过（`pnpm-test.txt`），`pnpm typecheck`、`pnpm lint:deps` 通过。后端 `tests/config/test_views.py` 新增 `test_seed_page_view_searchable`；`pytest -m "not oracle and not redis"` 1294 passed（`pytest.txt`），`lint-imports` 5 kept。
  - 没做：seed 的 FMNAME、FMRATE、USESTATUS 归 CF 组，没加 `searchable`（旧系统三者都勾了"查询"），合并时补。

### T-FP-17 千分位、Lookup 列标题和宽度、分类可填写的字典下拉

- 归属与目标：盘点（`.reports/inventory-20261030/甲-任务卡核对.md` 第四节 B6、B7，`乙-旧系统功能对照.md` 第 2.5、2.10 节），用户 2026-10-30 回复"其它无异议"同意按旧系统补。同时改 contracts（C06 v22、C05 v6）、config（页面视图带 `grouping`、`dictFreeText`、Lookup 显示列）、frontend-config（"表与列"的"千分位""字典可填写"，Lookup 管理的"显示标题""宽度"）和 seed。来源：旧系统 `cost-web/src/v3/composables/meta-v3/useMetaColumns.ts` 第 244–260、288–290 行（千分位）、`v3/components/LookupDialog.vue` 第 107–116 行（Lookup 标题和宽度）、`v3/components/meta-v3/editors/TagSelectCellEditor.vue`（下拉可填写，单值）、配置页 `SectionTables.vue` 第 36、99 行；cmx `T_COST_LOOKUP_CONFIG.DISPLAY_COLUMNS`、旧列元数据的 `useGrouping`。
- 负责范围：后端 `contracts/types.py`（`EntityField.grouping`、`LookupColumn`、`ViewLookup`、`FieldSetting.dict_free_text`、`ViewField.grouping`、`ViewField.dict_free_text`）、`config/views.py`、`config/page_view.py`、`queries/lookups.py`、`config/validation.py`；前端 `modules/page/fields.ts`（`groupThousands`、`formatNumber`、粘贴时去掉千分位）、`grid-adapter/LookupGrid.vue`、`grid-adapter/lookup-columns.ts`、`grid-adapter/DictSelectCellEditor.vue`、`renderers/RecordForm.vue`、配置页"表与列"和 Lookup 管理；seed 三个实体的 `grouping`、四个 Lookup 的显示列、字典 `pingguClass`、页面 COST_PINGGU 的 PINGGU_CLASS。
- 交付物：数值列按配置带千分位显示（表格、汇总行、表单只读格），编辑框里是原值，导出不变；Lookup 对话框表头为配置的标题、配了宽度的列固定宽度；成本核算"分类"为可填写的字典下拉，存选中或填写的文本。
- 验收标准：业务例子（浏览器、d_cg，正式用例 `frontend/tests/e2e/batch7-page-display.spec.ts`）：成本单 2555 的批量显示 3,500,000，主表汇总行带千分位；编辑框里是 3500000；新增成本单打开产品选择，表头是中文标题、产品ID 列宽 80；测试成本单的分类选"委托研发"、再填写字典以外的值，保存后重新打开都一致。
- 状态与证据：进行中（模拟验证和浏览器业务例子通过，待独立复核）。2026-10-30 第 7 批 PG 组，提交 7d00696（`batch7/page-display`），报告 `.reports/batch7-20261030/pg-page-display/报告.md`。合并后（2026-10-31，主代理）seed 的变化经配置接口写进 d_cg（`.reports/batch7-20261030/merge/save_config.out.txt`：seed 45 项与 d_cg 相同），后端模拟 1309 passed、真实 196 passed，前端单元 581 passed，整套端到端 42 passed，其中本卡 4 条（`.reports/batch7-20261030/merge/e2e-6.txt`）。
  - 与任务描述的差别：盘点写的是"分类多选"，核对旧系统后按旧系统做成单值的"下拉（可填写）"：旧 `TagSelectCellEditor.vue` 用 naive-ui `NSelect` 的 `tag`、`filterable`、`clearable`，没有 `multiple`；cmx 和 d_cg 的实际数据都是单值。
  - 物料清单页旧系统没有一列配千分位，没有补。

### T-FP-18 新增行立即显示默认值、对比按配置的显示方式

- 归属与目标：实现 FP-23、FP-24（盘点 `.reports/inventory-20261030/甲-任务卡核对.md` 第四节 B8、B9；用户 2026-10-31 回复"开始"）。契约 C05 v9（后端 T-CF-12）。来源：旧系统 `cost-web/src/v3/composables/meta-v3/useWorkingSetStore.ts` 第 543–585 行、`useMetaColumns.ts` 第 166–176、204–219、423–455 行。
- 前置输入：开始前 T-FP-6、T-CF-12。
- 负责范围：`contracts/page-view.ts`（`default`、`compare` 由契约缺口改为 C05 v9 的字段）、`modules/page/fields.ts`（`newRowValues`、`optionValues`、`compareDisplay` 已按可选字段实现，本卡核对并补测试）、`grid-adapter/columns.ts`、`renderers/RecordForm.vue`（`options` 下拉，已有）。
- 交付物：新增行时立即按页面视图的默认值显示，`options` 字段用下拉；对比按 `compare.format` 只显示差值、只显示百分比或都显示。
- 接入责任：真实联调在本卡的浏览器用例（合并后通过）。
- 验收标准：业务例子 E28、E29；模拟验证：配置为只显示差值、只显示百分比、都显示时，当前 3.80、历史 3.50 分别显示"0.30""8.57%""0.30 (8.57%)"。浏览器（d_cg，正式用例 `frontend/tests/e2e/batch8-config-caps.spec.ts` 场景 2、3，`@shared-config`，临时改实体配置、结束时恢复）：成本核算主表商务人员配当前用户姓名、剂型下拉"片剂、胶囊剂"、收率固定 98，admin 点"新增"后新行立即显示 admin 的姓名、片剂、98，剂型双击出这两个值的下拉，不保存；物料清单执行价配"与参考价格对比"，物料 14142 的执行价旁按"只显示差值""只显示百分比"显示，与列表接口的对比结果相同。
- 状态与证据：完成（模拟验证、浏览器用例通过；独立复核通过，`.reports/review/T-FP-18.md`）。合并后（2026-10-31，main）主代理运行：浏览器用例全部通过（`.reports/batch8-20261031/merge/e2e-6.txt`，57 passed），后端真实测试 217 passed（`pytest-real-1.txt`）。2026-10-31 第 8 批 G5，分支 `batch8/config-caps`。模拟验证：`tests/page/copy-lookup.test.ts` 新增 FP-24 一条（E28、E29 原有）；契约测试 `samples.test.ts` 去掉 ViewField 的 `default`、`compare` 缺口，与后端 `types.py` 字段一致；`pnpm test` 42 个文件 590 passed。浏览器：两条用例列在 `shared-config` 项目（`e2e-list-shared.txt`），合并后运行 `.reports/batch8-20261031/g5-config-caps/run-e2e.ps1 -Project shared-config -Grep 'B8|B9'`（脚本里的 worktree 路径、端口按合并后的位置改）。

### T-FP-19 复制不带"不复制"的列；客户信息复制客户带分销商

- 归属与目标：实现 FP-25（C05 v11 字段的 `copy`，后端 T-CF-15）。依据用户 2026-10-31："跟着复制（复制主表要把明细表一起复制过来，这个是通用方法，但是也可以配置哪些列可以不复制，这个在元数据中配置即可）"。旧系统没有这项配置，是新增能力。另核对第 8 批 G1 留下的未核实项"客户信息复制客户时分销商是否跟着复制"（FP-13 的现有能力，不改代码）。
- 前置输入：开始前 T-FP-5、T-FP-11、T-CF-15。
- 负责范围：`contracts/page-view.ts`（`ViewField.copy`）、`modules/page/copy.ts`（`copyableFields`）、`page-runtime.ts`（`openCopy` 明细区默认勾选的字段改用 `copyableFields`）。复制对话框 `renderers/CopyDialog.vue` 已按 `copyableFields` 列字段，不用改。
- 交付物：配置为不复制的列在主表区复制（连明细）和明细区复制的对话框里都不出现，新行这一列为空。
- 接入责任：真实联调在本卡的浏览器用例 2（合并后运行）。
- 验收标准：业务例子 E45；模拟验证：成本核算页把主表数量（可写）、创建人（不可写）和原辅料单价（可写）配成不复制，复制 2550（连明细）时对话框不列出这三列，新单据这三列为空，命令中数量、单价为 null、不带创建人；明细区复制一行时默认勾选的字段不含单价，新行单价为空。浏览器（d_cg，正式用例 `frontend/tests/e2e/copy-config-1031.spec.ts`）：1. 客户信息复制一个带一个分销商的测试客户，对话框默认全选，保存后新客户的客户名称、区域与源相同，分销商明细一行、名称相同、分销商ID 新的、客户ID 指向新客户（不改配置）；2. E45（`@shared-config`，测试锁 `page.CUSTOMER_MANAGE`，结束时恢复页面配置）。
- 状态与证据：完成（模拟验证和浏览器用例 1 通过；独立复核通过，`.reports/review/T-FP-19.md`）。合并后（2026-10-31）主代理在 main 上运行：后端真实测试 217 passed（`.reports/batch9-20261031/pytest-real-1.txt`），浏览器用例全部运行（`.reports/batch9-20261031/e2e-1.txt` 61 passed；失败的 E45 修正后单独通过，`e2e-3.txt`）。2026-10-31 第 9 批 B 组，分支 `batch9/copy-config`，报告 `.reports/batch9-20261031/b-copy-config/报告.md`。模拟验证：`tests/page/copy-lookup.test.ts`"不复制的列"两例；`pnpm test` 44 个文件 606 passed，`pnpm typecheck` 通过，`pnpm lint:deps` 通过；契约测试 `samples.test.ts` 的 ViewField 字段与后端 `types.py` 一致（别名 `copy`）。浏览器：`pnpm build:test` 后在本组后端 8092 运行用例 1，1 passed（`e2e-1.txt`），测试客户、分销商结束时删掉（只读核对 `q01-测试客户残留.out.txt`：PF_TEST 客户 0、分销商 0）。用例 2 要保存本组的新配置写法（`copy`），main 的后端读不懂，没有运行；合并、重启后运行 `.reports/batch9-20261031/b-copy-config/run-e2e.ps1 -Project shared-config -Grep 'E45' -Out e2e-2.txt`（脚本里的 worktree 路径、端口按合并后的位置改）。
### T-FP-20 按单据提交的保存和按钮结果
- 归属与目标：实现 FP-06、FP-14 中按单据提交（C02 v10）的结果处理。依据用户 2026-10-31："100个单据 失败了1个，就全部失败"是不可以的；做法同旧系统 `useWorkingSetStore.ts`：只对成功和送审的单据清除修改（第 1086–1125 行），提示张数和每张失败的原因（第 1169–1186 行）。后端为 T-WP-17。
- 前置输入：T-FP-3、T-WP-17。
- 负责范围：`contracts/command.ts`（`DocumentFailure`、`CommandResult.failed`）、`modules/page/failure.ts`（`documentFailuresText`）、`modules/page/page-runtime.ts`（`applySaveResult`、`reportFailures`、`announce`、`runOperation`）、`modules/shell/app.ts`（提示文字中的换行）。测试工具 `tests/e2e/support.ts`：按单据提交的命令记录按子请求键清理，一起删几张测试单据时只把没删掉的留给直接删。
- 交付物：结果的 `failed` 中的单据修改保留、错误定位到行和字段；成功的单据照常刷新、丢弃修改；一条提示列出张数和每张的原因；被审批冻结的弹出审批进度。
- 验收标准：模拟验证：`tests/page/doc-commit.test.ts`（2550 被规则拒绝、2551 保存；2550 在审批 204 中；主表选中两行点"同步价格"）；契约样例 `tests/contracts/samples.test.ts` 的"C02 按单据提交，一张没成功"。浏览器（d_cg，`frontend/tests/e2e/doc-commit-1031.spec.ts`）：两张测试成本单一起保存，A 的预胶化淀粉每片含量改成 0 被拒，B 的聚维酮K30 备注写入；提示"保存成功 1 张，失败 1 张"和 A 的原因，A 的修改留在页面上（1 行未保存），每片含量格子标出错误，数据库中 A 不变。
- 状态与证据：进行中（模拟验证和浏览器用例通过；独立复核 `.reports/review/T-WP-17-T-FP-20.md` 后补了新建单据没成功的用例："新建的成本单数量填 0 被规则拒绝、2551 照常保存"，新建的单据留在编辑缓冲、错误按 clientRowId 标在格子上、提示"单据 新增的一张：数量必须大于0"；按复核建议改了部分失败后规则效果栏被清空：只去掉保存过的单据的效果，没成功的单据的效果照旧显示，同一用例核对）。2026-10-31，分支 `batch10/doc-commit`。复核后 `pnpm exec vitest run` 46 个文件 616 passed（`.reports/doc-commit-20261031/vitest-2.txt`），`pnpm typecheck` 通过（`typecheck-2.txt`）；复核前 614 passed；浏览器：`pnpm build:test` 后由 worktree 后端 8093 运行全部用例 63 passed（`.reports/doc-commit-20261031/e2e-all-1.txt`，含新用例；结束时删掉命令记录按子请求键找到）。合并进 main 后：vitest 616 passed（`main-vitest.txt`），浏览器用例 63 passed（`main-e2e-1.txt`，后端 8090）。

### T-FP-21 通用的行表单（主表、明细都有）

- 归属与目标：实现 FP-03 的通用行表单：主表区和每个明细区用同一套实现，表单和表格用同一份区域元数据、同一个编辑缓冲，只有排布按区域的 `formLayout`（C05 v12）。依据用户 2026-11-01 原话："我知道旧项目没有，但是新项目要有，而且主表已经有表单了，明明可以做成一个通用方法套用的，表单和表格可以公用一个元数据，表单唯一的区别仅仅是可以调整每个表单列的位置和带线啊哦"（"带线"按"大小"理解，即 `formLayout` 的 x、y、w、h）。旧系统没有行表单，主表、明细都没有（调查见 `.reports/detail-form-20261101/报告.md`、`findings.md`），这是新平台的能力。
- 前置输入：T-FP-2（主表的原地表单）、T-FC-2（配置页按区域保存表单布局）。后端原来就输出、校验明细的 `formLayout`（`config/views.py`、`page_view.py`、`validation.py`），不用改。
- 负责范围：`modules/page/page-runtime.ts`（`state.forms` 按区域，`openForm`、`closeForm`、`stepForm`、`editForm` 带区域，`closeStaleForms`）、`record-form.ts`（新：字段、位置、标题）、`marks.ts`、`marks.css`（新：改动标记和错误标记，表格和表单共用）、`renderers/RecordForm.vue`（按区域）、`renderers/RegionPane.vue`（新：一个区域的表格加表单）、`renderers/GenericPage.vue`、`grid-adapter/columns.ts`（⊞ 列给所有区域）、`grid-adapter/PageGrid.vue`（标记样式改用 `marks.css`）；契约 C05 v12 的 `formLayout` 说明。
- 交付物：经通用页面按页面编码打开的所有页面（单表页、主从页、液体成本核算等），主表区和每个明细区的每行都有 ⊞（汇总行没有），点了在这个区域原地显示这一行的表单；主表和明细的表单可以同时开；明细区换了单据时明细的表单关上。主表原来的表单改走同一套实现，没有另一份代码。
- 验收标准：模拟验证 `frontend/tests/page/record-form.test.ts`：2550 原料/辅料点聚维酮K30 的 ⊞，表单显示这一行、按明细的 `formLayout` 排，主表的表单同时开着；明细没有布局时可见字段每行 3 个；表单里改备注进编辑缓冲，表格同一行同步、标为改过，撤销、重做，保存的命令与在表格里改相同；上一条、下一条按明细表格的先后、含新增的行，主表按主表表格；主表选 2551 或明细清空时明细的表单关上、主表的表单不动。原有主表用例（`buttons-config.test.ts` 配置原地替换后表单还开着）照常通过，只改了调用写法。浏览器（d_cg，`frontend/tests/e2e/detail-form-1101.spec.ts`）：经平台复制 2550 出测试成本单，原料/辅料点聚维酮K30 的 ⊞，表单里把备注改为"表单测试"并保存，提示"已保存"；返回后表格同一行是改后的值、选中行还在；重新打开再点 ⊞，表单里是改后的值，`api.record` 读回也是。测试数据由 fixture 结束时删除，不改共用配置。
- 状态与证据：进行中（模拟验证和浏览器用例通过，待独立复核）。2026-11-01 已合并进 main（40904a1），合并后 main 上 vitest 47 个文件 621 passed（`.reports/detail-form-20261101/main-vitest.txt`）、`pnpm typecheck` 通过（`main-typecheck.txt`）；主代理在 9527 打开 2550 原料/辅料聚维酮K30 的表单，显示正常（只看，没改数据）。2026-11-01，分支 `batch10/detail-form`，报告 `.reports/detail-form-20261101/报告-实现.md`。`pnpm exec vitest run` 47 个文件 621 passed（`vitest-2.txt`；改动前 616，新增 5 条）；`pnpm typecheck` 通过（`typecheck-2.txt`）；eslint 对改动的文件按文件计都不多于 main（`eslint-final.txt` 69 个，main 同一批文件 `eslint-main.txt` 74 个，新文件 0 个）。浏览器：`pnpm build:test` 后由 worktree 后端 8094 运行（`run-e2e.ps1`），只跑新用例 `e2e-new-1.txt` 4 passed（3 个登录加新用例），全部用例 `e2e-all-1.txt` 64 passed（15.9 分钟）。
  - 2026-11-01 补：表单里也显示对比，与表格同一格相同的箭头、文字、颜色和显示方式（只读、可编辑的字段都显示，写在输入框下面）；核对出的其他不同一并改成与表格一致（悬停的错误提示、界面规则的单元格样式和行样式、行的标记、数值右对齐、布尔字段只读时的复选框），判断都放进 `marks.ts`，表格和表单调用同一个函数。分支 `batch10/form-compare`，报告 `.reports/form-compare-20261101/报告.md`；`pnpm exec vitest run` 47 个文件 625 passed（`vitest-1.txt`，新增 4 条：单价"都显示"、"只显示差值"、金额"只显示百分比"各一例和界面规则的样式），`pnpm typecheck` 通过（`typecheck-3.txt`）；浏览器用例 `frontend/tests/e2e/form-compare-1101.spec.ts` 没有运行，待合并后运行。
