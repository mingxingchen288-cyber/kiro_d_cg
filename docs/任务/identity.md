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
- 状态与证据：进行中。2026-10-29，导入账号（ID-08、`AccountImporter`）属于迁移，暂停。
  - 模拟验证：通过。命令为在 `backend` 目录执行 `uv run pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/identity`，identity 全部测试 49 个通过、0 个失败（`.reports/modules/identity/pytest-3.txt`）。本卡对应的测试：`test_accounts.py`（admin 初始化执行两次第二次不改数据、账号名重复、账号列表、`DirectoryReader` 契约测试）、`test_passwords.py`、`test_login.py::test_bcrypt_hash_upgraded_after_successful_login_only`。
  - 真实验证：测试在 `tests/identity/test_oracle.py`（`-m oracle`）。
  - 2026-10-29：BCrypt 校验改用 `bcrypt==5.0.0` 包（删掉纯 Python 实现 `_bcrypt.py`），校验一次 `$2a$10$` 哈希从 8.478 秒降到约 0.06 秒；密码仍只取前 72 字节（与旧系统一致）。`-m "not oracle and not redis" tests/identity` 52 个通过；`-m "oracle or redis" tests/identity` 14 个通过，含 `test_bcrypt_upgraded_on_oracle`。
  - 上线后再补：两个请求同时新建同名账号时，唯一约束的报错没有转成 422。
  - 契约缺口见 `.reports/modules/identity/contract-gaps.md`。

### T-ID-2 登录、会话与认证

- 归属与目标：实现 ID-01–ID-03、ID-09、ID-10 和 `Authenticator`，以及 C09 第 2 节的登录、选角色、注销和 `/api/me`。
- 前置输入：开始前 T-ID-1。验收前 Redis 可用。
- 负责范围：identity 的会话存储（Redis）、认证和登录相关路由。
- 交付物：上述接口和 `Authenticator`。
- 接入责任：T-AS-4 接入中间件和 realtime 的握手；frontend-shell 使用登录接口（T-AS-7）。
- 验收标准：模拟验证：账号不存在、密码错误、账号停用都返回 LOGIN_FAILED；单角色自动选定；写请求缺 CSRF 令牌返回 CSRF_FAILED；用可控时钟验证 120 分钟无操作后返回 SESSION_REQUIRED、中途有用户请求则顺延，`touch=False` 不顺延；通过 `Authenticator` 的契约测试（C08 第 14 节）；真实验证：会话在 Redis 上按时过期。
- 状态与证据：进行中。2026-10-29：
  - 模拟验证：通过，命令同 T-ID-1，49 个通过。本卡对应的测试：`test_login.py`（三种登录失败、单角色自动选定、多角色选择和选错角色、缺 CSRF 令牌、E19 的 120 分钟、注销）、`test_authenticator.py`（`Authenticator` 契约测试，被测实现为 `IdentityService`）、`test_router.py`（login、role、logout、`/api/me` 的菜单、后台请求不顺延）。
  - 真实验证：测试已写好，没有运行，因为本机没有 Redis。测试在 `tests/identity/test_redis.py`，共 4 个（`-m redis`）。
  - 接口位置：路由是 `identity/router.py` 的 `identity_router`；会话存储是 `identity/sessions.py`，包括 `MemorySessions` 和 `RedisSessions`。

### T-ID-3 账号管理与会话撤销

- 归属与目标：实现 ID-05，以及 C09 第 2 节的 `/api/admin/accounts`、`/api/admin/departments`。
- 前置输入：开始前 T-ID-2。
- 负责范围：identity 的账号管理路由。
- 交付物：账号的列表、新建、修改、停用、改密码；部门列表；停用或撤销角色后发布 `session.revoked`。
- 接入责任：frontend-admin 使用（T-AS-7）；realtime 推送撤销事件（T-AS-4）。
- 验收标准（模拟验证）：停用账号后该账号的下一次请求返回 SESSION_REQUIRED，撤销其选定的角色后返回 SESSION_ROLE_REVOKED，各发布一条 `session.revoked`；非管理员调用返回 PERMISSION_DENIED。
- 状态与证据：待联调。2026-10-29：
  - 模拟验证：通过，命令同 T-ID-1，49 个通过。本卡对应的测试：
    - `test_admin.py`：停用账号、撤销选定的角色（各发布一条 `session.revoked`）、新建、账号名重复、分配的角色必须存在、管理员改密码、部门；
    - `test_router.py`：`/api/admin/accounts`、`/api/admin/departments`、非管理员返回 PERMISSION_DENIED。
  - 另外做了旧系统有、C09 没有的能力：部门的新建、修改、删除，账号列表按角色筛选，改自己的密码。见 `.reports/modules/identity/contract-gaps.md` 第 2–4 条。
  - 接入 assembly、realtime 后进行真实联调。
