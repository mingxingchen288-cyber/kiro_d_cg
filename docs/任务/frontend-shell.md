# frontend-shell 任务

模块说明：[frontend-shell](../模块/frontend-shell.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E19（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-FS-1 复制并清理旧前端（第 0 组）

- 归属与目标：建立 `frontend/` 工程，完成模块说明第 5 节的复制和清理。
- 前置输入：无，可以最先开始。
- 负责范围：`frontend/` 的初次建立；完成后 `package.json`、`vite.config.ts`、`src/main.ts` 交 assembly 维护。
- 交付物：`D:\chonggou\my-project\cost-web` 当前工作状态的副本（不含 `.git`、`node_modules`、`dist`、测试报告、日志和 `.codex-*` 等临时文件）；`frontend/SOURCE.md` 记录复制时的提交号和未提交文件清单；删除无效代码后的工程。
- 接入责任：T-CT-4、T-FS-2、T-AS-3 和其他前端任务在此基础上开发。
- 验收标准：`pnpm install`、`pnpm build` 和类型检查通过；knip 报告没有未被引用的文件、导出和依赖；只保留布局、主题、登录、路由、请求工具和它们用到的组件；外壳布局能打开，外观与旧系统相同。
- 状态与证据：未开始。

### T-FS-2 外壳与 ShellApi

- 归属与目标：实现 FS-01–FS-05 和 `ShellApi`（C11）。
- 前置输入：开始前 T-FS-1、T-CT-4。
- 负责范围：`frontend/src/modules/shell/`、`frontend/src/theme/`、`frontend/src/layouts/`。
- 交付物：登录页、选角色页、菜单、页签、站内通知入口；`ShellApi`。
- 接入责任：T-AS-3 加载外壳并注册其他模块；T-AS-7 与真实后端联调。
- 验收标准（模拟验证）：单角色跳过选角色页；收到 401 或 `session.revoked` 回到登录页；有未保存修改的页签关闭前确认；未读数只在打开时读取一次，之后随 `notification` 事件更新；与旧系统同一页面截图对比，外观一致。
- 状态与证据：未开始。
