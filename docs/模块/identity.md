# identity

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：登录、选角色、注销、`/api/me`；会话和 CSRF 校验；账号管理（新建、修改、停用、改密码、分配角色、部门）；启动时初始化 admin；导入旧账号；会话撤销事件。
- 不负责：角色的定义和权限（config 的角色配置）；权限判断（authz）；账号管理界面（frontend-admin）。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `backend/src/cost_platform/identity/` |
| 数据 | 表 `PF_USER`（账号、密码哈希、部门、启用状态）、`PF_USER_ROLE`（账号与角色编码的分配）、`PF_DEPARTMENT` |
| 状态 | Redis 键 `{ns}:session:{sid}`（会话，带过期时间）、`{ns}:user:{uid}:ver`（账号版本） |

## 3. 对外契约

提供 `Authenticator`、`DirectoryReader`、`AccountImporter`（[C08](../契约/C08-后端端口.md)），以及 [C09 第 2 节](../契约/C09-HTTP接口.md)的接口。

- ID-01：登录失败一律返回 401 LOGIN_FAILED，包括账号不存在、密码错误、账号停用和没有密码哈希。登录成功时新建会话，写 HttpOnly Cookie `cp_session`，返回 `csrfToken`；账号只有一个角色时自动选定。
- ID-02：平台只使用会话选定的一个角色。选择不属于该账号的角色，返回 403 PERMISSION_DENIED。
- ID-03：写请求的 `X-CSRF-Token` 必须与会话匹配，否则返回 403 CSRF_FAILED。
- ID-04：密码用 Argon2 哈希。旧账号的 BCrypt 哈希在登录成功时改写为 Argon2；登录失败时不改。
- ID-05：停用账号或撤销角色在一个事务内完成；提交后账号版本加一，旧会话立即失效（SESSION_REQUIRED 或 SESSION_ROLE_REVOKED），并发布 `session.revoked`（[C10](../契约/C10-实时事件.md)）。
- ID-06：启动时如果没有 admin 账号，创建 admin / admin123..，启用，并分配 `ADMIN` 角色；已存在时不改任何内容。
- ID-07：账号名唯一，重复时返回 422 VALIDATION_FAILED。
- ID-08：`AccountImporter` 导入旧账号（含 BCrypt 哈希）、角色分配和部门；已存在的账号不覆盖，列入报告。
- ID-09：`/api/me` 返回的菜单取自配置快照的 `menus()`，config 已去掉当前角色不能访问的页面。
- ID-10：会话在 2 小时内没有有效操作即过期；有有效操作时，从这次操作起重新计时。有效操作只指用户自己的写入和查询请求；带 `X-Background-Request: 1` 的请求（C09 第 1 节）和 WebSocket 的握手、心跳都不算，这些情况以 `touch=False` 检查会话。时长取 `.env` 的 `PLATFORM_SESSION_IDLE_MINUTES`，默认 120。

## 4. 依赖

| 契约 | 提供方 | 用途 |
|---|---|---|
| `UnitOfWork` | db-core | 账号数据的读写 |
| `RealtimePublisher` | realtime | 发布会话撤销事件 |
| 配置快照的菜单和角色（C08 `ConfigSnapshot`） | config | `/api/me` 的菜单；分配角色时核对角色存在 |

## 5. 内部流程

认证：读 Cookie 中的会话标识 → 一次 Redis 读取会话和账号版本 → 版本不一致即失效 → 写请求再核对 CSRF 令牌 → `touch` 为 True 时顺延过期时间 → 返回 `Identity`（[C04](../契约/C04-执行上下文.md)）。

## 6. 接入方式

- assembly 的中间件和 realtime 的握手调用 `Authenticator`；approval 调用 `DirectoryReader`；migration 调用 `AccountImporter`。
- assembly 在启动时调用 ID-06。
- frontend-shell 和 frontend-admin 调用 C09 第 2 节的接口。
- 真实联调：批次 A。

## 7. 验收边界

- 开始开发的前置条件：contracts 完成。
- 本模块完成（模拟验证）：登录、选角色、注销、CSRF 校验、会话失效、Argon2 与 BCrypt 升级、admin 初始化重复执行不改数据。
- 联调后才能确认：在 Redis 和 Oracle 上停用账号后，已打开的浏览器立即回到登录页（批次 A、D）。

