# frontend-shell

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：复制旧 cost-web 的当前工作状态（包括未提交的文件）并删除无效代码；Soybean 布局和主题；登录页、选角色页；菜单（来自 `/api/me`）；页签缓存；路由守卫；站内通知入口和铃铛角标（待我审批数）；实现 `ShellApi`（[C11](../契约/C11-前端装载.md)）。
- 不负责：页面、配置、审批、管理各功能（frontend-page、frontend-config、frontend-approval、frontend-admin）；前端构建配置和模块注册（assembly）。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `frontend/src/modules/shell/`、`frontend/src/theme/`、`frontend/src/layouts/` |
| 状态 | 当前用户、选定角色、页签列表 |

## 3. 对外契约

提供 C11 的 `ShellApi`，调用 [C09 第 2 节](../契约/C09-HTTP接口.md)、第 7 节的站内通知接口，以及第 6 节待办列表的条数（铃铛角标，FS-06）。

- FS-01：外观沿用旧 `src/theme/settings.ts`：主题色 `#646cff`、圆角 6、顶栏高 28、chrome 样式页签高 33、侧栏宽 220（折叠 64）、浅色侧栏、内容区背景 `rgb(247,250,252)`、页签带缓存。
- FS-02：账号只有一个角色时跳过选角色页；收到 401 或 `session.revoked` 时回到登录页。
- FS-03：页签标记了未保存修改时，关闭前先确认。
- FS-04：站内通知：未读通知数打开时读取一次（后台请求，C09 第 1 节），之后按 `notification` 事件更新，不轮询，显示在"消息中心"抽屉里（"当前只显示未读的通知（N 条）"）。点击通知按 `link` 跳转。铃铛角标见 FS-06。
- FS-06：顶栏铃铛的角标是待我审批的审批数（C11 v3 `ShellApi.bell`，C09 v14 `GET /api/approvals?box=todo&startRow=0&endRow=0` 的 `total`，后台请求），不是未读通知数。依据：旧系统 `approval-notification-center.vue` 第 45、224 行铃铛显示 `unreadCount`，后端 `ApprovalNotificationService.summary` 第 49 行 `unreadCount = approvalCount`（盘点 `.reports/inventory-20261030/甲-任务卡核对.md` 第五节 U1），用户 2026-10-30 回复"其它无异议"同意按旧系统做。例如 admin 读了"成本单 2550 的审批"通知但还没审批，角标仍是 1；通过后变 0。什么时候重新读：会话就绪时；收到链接为 `/approval/…` 的站内通知时（有审批提交给我、进入我这一级）；frontend-approval 处理了审批后调用 `bell.refresh()` 时（旧系统处理完立即 `loadSummary`）；点开铃铛时（旧系统 `openDrawer`）；以及每 60 秒一次（旧系统第 63–66 行，同一角色的别人处理了审批、或审批流没配通知时也会跟着变）。读取失败时保留原来的数。代码在 `modules/shell/todo-count.ts`、`layouts/modules/global-header/components/inbox-bell.vue`。
- FS-07：`ShellApi.tabs.open` 的路径可以带查询参数（C11 v3，例如审批待办"原单据"的 `/page/COST_PINGGU?record=2550`）：页签仍按路径区分，标题按路径设置；已打开的页签换到这个地址，之后切回这个页签时用最近一次打开的地址（frontend-page 定位后会重新打开不带 `record` 的地址，切回时不再定位）。代码在 `modules/shell/app.ts`、`store/modules/tab/index.ts` 的 `setTabTitle`、`setTabFullPath`。
- FS-05：AG Grid 企业版授权从根目录 `.env` 的 `VITE_AG_GRID_LICENSE_KEY` 读取，不写进代码；为空时不调用 `setLicenseKey`。环境文件的读取位置由 assembly 的 AS-09 规定。

## 4. 依赖

契约 C09、C10、C11。

## 5. 内部流程

复制旧工程 → 删除无效代码 → 保留布局、主题、登录和菜单 → 改为调用新接口 → 实现 `ShellApi`。无效代码指新平台不用的代码：旧页面、旧接口调用、旧的元数据和计算代码，以及删除这些之后不再被引用的组件、工具函数、样式和依赖。

## 6. 接入方式

assembly 的 `main.ts` 加载外壳，再把其他前端模块注册进来。真实联调：批次 D。

## 7. 验收边界

- 开始开发的前置条件：复制与清理（T-FS-1）不依赖契约，可以最先开始；其余部分在 contracts 完成后开始。
- 本模块完成（模拟验证）：用 C09 的模拟实现完成登录、选角色、菜单、页签和通知；与旧系统同一页面截图对比，外观一致（同一角色、数据、浏览器和窗口尺寸）。
- 联调后才能确认：连接真实后端后的登录、会话失效和通知（批次 D）。

