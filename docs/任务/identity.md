# identity 任务

模块说明：[identity](../模块/identity.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。

相关业务例子：E19（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-ID-1 账号数据、密码与导入

- 归属与目标：实现 ID-04、ID-06–ID-08，以及 `DirectoryReader`、`AccountImporter`。
- 前置输入：开始前 T-CT-1、T-CT-3。验收前 T-DB-1、T-DB-2。
- 负责范围：`backend/src/cost_platform/identity/` 的账号存储；表 `PF_USER`、`PF_USER_ROLE`、`PF_DEPARTMENT` 的迁移脚本。
- 交付物：账号读写；Argon2 哈希和 BCrypt 校验；admin 初始化函数；账号导入。
- 接入责任：T-AS-4 在启动时调用 admin 初始化；approval 使用 `DirectoryReader`（T-AS-6）；migration 使用 `AccountImporter`（T-AS-8）。
- 验收标准：模拟验证和真实验证（d_cg）都通过：BCrypt 账号登录成功后哈希改为 Argon2，失败时不改；admin 初始化执行两次，第二次不改任何数据；导入时已存在的账号不覆盖（角色分配也不改），列入报告，报告的计数和标识按 C08 第 1 节；通过 `DirectoryReader`、`AccountImporter` 的契约测试；账号名重复返回 VALIDATION_FAILED。
- 状态与证据：进行中。链路 0 已先交付最小部分，见 T-AS-9（[assembly](assembly.md)）；本卡的验收照常进行。

### T-ID-2 登录、会话与认证

- 归属与目标：实现 ID-01–ID-03、ID-09、ID-10 和 `Authenticator`，以及 C09 第 2 节的登录、选角色、注销和 `/api/me`。
- 前置输入：开始前 T-ID-1。验收前 Redis 可用。
- 负责范围：identity 的会话存储（Redis）、认证和登录相关路由。
- 交付物：上述接口和 `Authenticator`。
- 接入责任：T-AS-4 接入中间件和 realtime 的握手；frontend-shell 使用登录接口（T-AS-7）。
- 验收标准：模拟验证：账号不存在、密码错误、账号停用都返回 LOGIN_FAILED；单角色自动选定；写请求缺 CSRF 令牌返回 CSRF_FAILED；用可控时钟验证 120 分钟无操作后返回 SESSION_REQUIRED、中途有用户请求则顺延，`touch=False` 不顺延；通过 `Authenticator` 的契约测试（C08 第 14 节）；真实验证：会话在 Redis 上按时过期。
- 状态与证据：进行中。链路 0 已先交付最小部分，见 T-AS-9（[assembly](assembly.md)）；本卡的验收照常进行。

### T-ID-3 账号管理与会话撤销

- 归属与目标：实现 ID-05，以及 C09 第 2 节的 `/api/admin/accounts`、`/api/admin/departments`。
- 前置输入：开始前 T-ID-2。
- 负责范围：identity 的账号管理路由。
- 交付物：账号的列表、新建、修改、停用、改密码；部门列表；停用或撤销角色后发布 `session.revoked`。
- 接入责任：frontend-admin 使用（T-AS-7）；realtime 推送撤销事件（T-AS-4）。
- 验收标准（模拟验证）：停用账号后该账号的下一次请求返回 SESSION_REQUIRED，撤销其选定的角色后返回 SESSION_ROLE_REVOKED，各发布一条 `session.revoked`；非管理员调用返回 PERMISSION_DENIED。
- 状态与证据：未开始。
