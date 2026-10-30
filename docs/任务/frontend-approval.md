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
