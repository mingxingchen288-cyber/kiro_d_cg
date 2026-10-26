# 前端复制来源

- 来源：`D:\chonggou\my-project\cost-web`，仓库 `D:\chonggou\my-project` 的提交 `a95c00c1819e3db54f52dff42a861bee1b36e30f`，加上复制时的未提交改动（按用户要求按当前状态复制）。
- 复制时间：2026-10-26 15:36。
- 未复制：`.git`、`node_modules`、`dist`、`playwright-report`、`test-results`、`.codex-*`、`*.log`。
- 与原样副本的差异：复制提交 036cc8a 中的 `package.json` 已去掉 `prepare` 脚本（`simple-git-hooks`）和 `simple-git-hooks` 配置，避免安装时改写本仓库的 git 钩子。
- 复制时 cost-web 下有 22 个未提交的文件：

| 文件 | 类型 |
|---|---|
| `src/layouts/modules/global-header/components/approval-notification-center.vue` | 修改 |
| `src/service/api/approval-runtime.ts` | 修改 |
| `src/service/api/dynamic.ts` | 修改 |
| `src/typings/api/metadata.d.ts` | 修改 |
| `src/typings/components.d.ts` | 修改 |
| `src/v3/components/approval/ApprovalActionGroup.vue` | 修改 |
| `src/v3/composables/meta-v3/types.ts` | 修改 |
| `src/v3/composables/meta-v3/usePageRules.ts` | 修改 |
| `src/v3/composables/meta-v3/useWorkingSetStore.ts` | 修改 |
| `src/views/_builtin/meta-config/panels/CellEditableDialog.vue` | 修改 |
| `src/views/_builtin/meta-config/panels/unified/sections/SectionApproval.vue` | 修改 |
| `src/views/_builtin/meta-config/panels/unified/sections/SectionBehavior.vue` | 修改 |
| `src/components/approval/ApprovalDecisionDialog.vue` | 未跟踪（新文件） |
| `src/components/approval/ApprovalObjectProgress.vue` | 未跟踪（新文件） |
| `src/components/approval/approval-errors.ts` | 未跟踪（新文件） |
| `src/components/approval/approval-object-columns.ts` | 未跟踪（新文件） |
| `src/service/api/approval-config.ts` | 未跟踪（新文件） |
| `src/views/_builtin/meta-config/panels/unified/sections/ApprovalActionParamsEditor.vue` | 未跟踪（新文件） |
| `src/views/_builtin/meta-config/panels/unified/sections/ApprovalApproverEditor.vue` | 未跟踪（新文件） |
| `src/views/_builtin/meta-config/panels/unified/sections/ApprovalConditionEditor.vue` | 未跟踪（新文件） |
| `src/views/_builtin/meta-config/panels/unified/sections/ApprovalConfigGrid.vue` | 未跟踪（新文件） |
| `src/views/_builtin/meta-config/panels/unified/sections/approval-config-columns.ts` | 未跟踪（新文件） |

之后按 T-FS-1 删除无效代码，删除内容见 git 历史。