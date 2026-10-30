# frontend-approval 任务

模块说明：[frontend-approval](../模块/frontend-approval.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E10–E15（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-FA-1 待办与审批详情

- 归属与目标：实现 FA-01–FA-09。
- 前置输入：开始前 T-CT-4，`ShellApi` 用模拟实现。
- 负责范围：`frontend/src/modules/approval/`。
- 交付物：待办列表（我审批的、我发起的）；审批详情、勾选、通过、驳回、撤回。
- 接入责任：T-AS-3 注册到外壳；T-AS-7 与真实后端联调。
- 验收标准：页面样式与旧系统审批详情一致（FA-06）；在 d_cg 上走通业务例子 E37、E39 的页面部分：E37 详情中原辅料三行的"触发审批"、物料清单一块 75→90、第 2 级会签两人分别通过；E39 中取消 2556 后这一行恢复为单价 75、金额 23.25，通过时 `checkedRows` 不含 2556。
- 状态与证据：待联调（模拟验证通过；在 d_cg 上走通 E37、E39 属于 T-AS-7 的真实联调，还没做；完成前的独立复核还没做）。
  - 交付（2026-10-29）：`frontend/src/modules/approval/`：`index.ts`（C11 `FrontendModule`，路由 `/approval`、`/approval/:approvalId`）、`detail-runtime.ts`（详情、勾选与 preview、通过、驳回、撤回、人工参数、409 重新确认）、`todo-runtime.ts`（待审批 / 我的发起）、`view-model.ts`（"A → B"、变化、触发审批、审批进度）、`events.ts`、`renderers/`（详情页、修改内容和受影响单据表格、审批进度表、待办页，样式对照旧系统 `ApprovalDetailDialog.vue`、`ApprovalPresentationGrid.vue`、`approval-notification-center.vue`）。FA-02 不另做界面（不显示排队）。
  - 模拟验证：`pnpm exec vitest run tests/approval` 5 个文件 13 个测试通过（E37 详情与两级会签、E39 取消 2556 后 preview 与通过的 `checkedRows`、表头全选不含记录已不存在的行、驳回、撤回、人工参数、409 重新确认、待办、C11 装载）；全量 `pnpm test` 22 个文件 458 个测试通过。`pnpm typecheck` 退出码 2：9 个错误都在其他模块（config、layouts、store/route），本模块和 `tests/approval` 0 个。输出：`.reports/modules/frontend-approval/vitest-approval-2.txt`、`vitest-all-2.txt`、`typecheck-4.txt`。
  - 浏览器渲染检查（模拟数据，不是联调）：用替代实现挂载详情页和待办页，勾选、preview、通过、页签切换的 DOM 结果记在 `.reports/modules/frontend-approval/progress.md`；检查用的临时入口已删除。
  - 契约缺口：`.reports/modules/frontend-approval/contract-gaps.md`（待办没有"我处理过的"、原单据不能定位单据、审批进度弹窗没有到详情的入口、详情没有处理记录、修改内容的列没有宽度）。
  - 上线后再补：请求结果不确定（网络中断）时暂停重复提交（旧系统 `ApprovalDetailDialog.vue` 的 `uncertain`）、preview 失败后的处理（现在只提示错误）。
  - 已撤回（2026-10-30，RA 组，`batch4/rules-approval`，C09 v11）：`steps[].status`、`members[].status` 增加 `withdrawn`，`view-model.ts` 的 `STEP_STATUS`、`MEMBER_STATUS` 显示"已撤回"（同旧系统 `ApprovalDetailDialog.vue` 的 `statusText` 中 CANCELED），`contracts/http.ts` 同步；frontend-page 的审批进度弹窗 `ApprovalProgressDialog.vue` 同样加上。`tests/approval/e37.test.ts` 加一例（审批 29 撤回后的进度：状态"已撤回"、审批人"角色：系统管理员（已撤回）"）。后端改动和浏览器核对见 approval 的 T-AP-3。

### T-FA-2 全部审批页签、审批记录、修改内容的列宽、原单据定位
- 归属与目标：FA-11～FA-15，C09 v14、C11 v3。即 T-FA-1 记下的 5 条契约缺口（`.reports/modules/frontend-approval/contract-gaps.md`，盘点 `.reports/inventory-20261030/甲-任务卡核对.md` 第四节 B1～B5），用户 2026-10-30 回复"其它无异议"同意按旧系统补。来源：旧系统 `approval-notification-center.vue` 第 47、105–108、141–158、243–245 行，`ApprovalDetailDialog.vue` 第 200–208、779–791 行，`ApprovalPresentationGrid.vue` 第 188 行。
- 前置输入：approval T-AP-9（`box=all`、`history`、`widths`）；frontend-page T-FP-15（`?record=` 定位）；frontend-shell T-FS-3（`ShellApi.bell`）。
- 负责范围：`todo-runtime.ts`（第三个页签、三个条数、`sourcePath`）、`view-model.ts`（`historyRows`、`columnWidth`）、`index.ts`（处理后 `bell.refresh`）、`renderers/ApprovalTodoPage.vue`、`ApprovalDetailPage.vue`、`ApprovalViewGrid.vue`、新文件 `ApprovalHistoryGrid.vue`；contracts 随 C09 v14 改 `http.ts`、`api.ts`、`fakes/samples.ts`，随 C11 v3 改 `shell.ts`、`fakes/shell.ts`。
- 交付物：待办"待审批 / 我的发起 / 全部审批"三个页签；详情底部"审批记录（N）"；修改内容按配置的列宽；"原单据"打开 `/page/{page}?record={来源单据号}`。
- 验收标准：模拟验证（`tests/approval/todo.test.ts`）：打开时读当前页签一页和另两个页签的条数、切到全部审批、原单据带 `record`、处理后调用 `bell.refresh`、审批记录的动作和说明文字。业务例子（浏览器、d_cg，正式用例 `frontend/tests/e2e/batch7-approval.spec.ts`，测试物料和测试成本单由 `data` 建、用例结束删除）：chengben01 改测试物料的单价提交审批，双击被冻结的单价弹出进度、"查看审批详情"进入详情（审批记录（1））；admin 的铃铛角标等于待我审批数，在待办中通过后少一个；详情"审批记录（2）"展开为提交、通过两行；"全部审批"里有这个已通过的审批；从它点"原单据"，成本核算只显示并选中这张单据、明细显示单价 90.00；选中后点"查看审批进度"，弹窗是这张单据的审批（已通过），能进审批详情。
- 状态与证据：模拟验证和浏览器业务例子通过，待独立复核（2026-10-31，AP 组，`batch7/approval-history`，本卡所在的提交；原始输出在 `.reports/batch7-20261030/ap-approval/`）。
  - 前端：`pnpm test` 38 个文件 557 个通过（`pnpm-test.txt`），`pnpm typecheck` 退出码 0（`typecheck.txt`），`pnpm lint:deps` 没有新违反（`lint-deps.txt`，2 条已知的违反是 `views/page/[pageCode].vue` 的过渡视图）。
  - 浏览器（`pnpm build:test` 后由后端 8092 托管）：`batch7-approval.spec.ts` setup 3 个加本用例共 4 个通过（`e2e-2.txt`，用例 23.2s）；第一次跑失败在角标的读法（NBadge 的数字是滚动动画，textContent 为"111"，改为读 `title`，`e2e-1.txt`）。
  - 与旧系统的差别：全部审批做成第三个页签（旧系统点"查看全部"切换）；审批记录的动作写中文、说明写成中文的处理结果（旧系统显示 APPLY 等代码和 DETAIL_MESSAGE）；铃铛里的通知只链接审批详情，没有"原单据"按钮。
