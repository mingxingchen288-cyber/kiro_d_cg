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
- 状态与证据：进行中（模拟验证和真实验证通过，导入账号随迁移暂停；待独立复核）。2026-10-29，导入账号（ID-08、`AccountImporter`）属于迁移，暂停。
  - 模拟验证：通过。命令为在 `backend` 目录执行 `uv run pytest -q -p no:cacheprovider -m "not oracle and not redis" tests/identity`，identity 全部测试 49 个通过、0 个失败（`.reports/modules/identity/pytest-3.txt`）。本卡对应的测试：`test_accounts.py`（admin 初始化执行两次第二次不改数据、账号名重复、账号列表、`DirectoryReader` 契约测试）、`test_passwords.py`、`test_login.py::test_bcrypt_hash_upgraded_after_successful_login_only`。
  - 真实验证：测试在 `tests/identity/test_oracle.py`（`-m oracle`）。
  - 2026-10-29：BCrypt 校验改用 `bcrypt==5.0.0` 包（删掉纯 Python 实现 `_bcrypt.py`），校验一次 `$2a$10$` 哈希从 8.478 秒降到约 0.06 秒；密码仍只取前 72 字节（与旧系统一致）。`-m "not oracle and not redis" tests/identity` 52 个通过；`-m "oracle or redis" tests/identity` 14 个通过，含 `test_bcrypt_upgraded_on_oracle`。
  - 上线后再补：两个请求同时新建同名账号时，唯一约束的报错没有转成 422。
  - 契约缺口见 `.reports/modules/identity/contract-gaps.md`。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"。
    - 真实验证：`tests/identity/test_oracle.py`（第 28 行标 oracle，含 `test_bcrypt_upgraded_on_oracle`）在 d_cg 上通过，第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`。
    - 导入账号（`AccountImporter`）随migration 暂停（`.kiro/steering/交付方式.md`"先有功能，才谈迁移"）；两个请求同时新建同名账号的报错，本条已标上线后再补。
    - `.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-ID-2 登录、会话与认证

- 归属与目标：实现 ID-01–ID-03、ID-09、ID-10 和 `Authenticator`，以及 C09 第 2 节的登录、选角色、注销和 `/api/me`。
- 前置输入：开始前 T-ID-1。验收前 Redis 可用。
- 负责范围：identity 的会话存储（Redis）、认证和登录相关路由。
- 交付物：上述接口和 `Authenticator`。
- 接入责任：T-AS-4 接入中间件和 realtime 的握手；frontend-shell 使用登录接口（T-AS-7）。
- 验收标准：模拟验证：账号不存在、密码错误、账号停用都返回 LOGIN_FAILED；单角色自动选定；写请求缺 CSRF 令牌返回 CSRF_FAILED；用可控时钟验证 120 分钟无操作后返回 SESSION_REQUIRED、中途有用户请求则顺延，`touch=False` 不顺延；通过 `Authenticator` 的契约测试（C08 第 14 节）；真实验证：会话在 Redis 上按时过期。
- 状态与证据：进行中（模拟验证和真实验证通过，待独立复核）。2026-10-29：
  - 模拟验证：通过，命令同 T-ID-1，49 个通过。本卡对应的测试：`test_login.py`（三种登录失败、单角色自动选定、多角色选择和选错角色、缺 CSRF 令牌、E19 的 120 分钟、注销）、`test_authenticator.py`（`Authenticator` 契约测试，被测实现为 `IdentityService`）、`test_router.py`（login、role、logout、`/api/me` 的菜单、后台请求不顺延）。
  - 真实验证：测试已写好，没有运行，因为本机没有 Redis。测试在 `tests/identity/test_redis.py`，共 4 个（`-m redis`）。
  - 接口位置：路由是 `identity/router.py` 的 `identity_router`；会话存储是 `identity/sessions.py`，包括 `MemorySessions` 和 `RedisSessions`。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"进行中"改为"完成"：本条"测试已写好，没有运行"的 `tests/identity/test_redis.py`（第 20 行标 redis，4 个）在 Redis 上通过，第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`；浏览器端到端每次 setup 登录 admin、chengben01、jishu01 三个账号（`frontend/tests/e2e/auth.setup.ts:12`，第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-ID-3 账号管理与会话撤销

- 归属与目标：实现 ID-05，以及 C09 第 2 节的 `/api/admin/accounts`、`/api/admin/departments`。
- 前置输入：开始前 T-ID-2。
- 负责范围：identity 的账号管理路由。
- 交付物：账号的列表、新建、修改、停用、改密码；部门列表；停用或撤销角色后发布 `session.revoked`。
- 接入责任：frontend-admin 使用（T-AS-7）；realtime 推送撤销事件（T-AS-4）。
- 验收标准（模拟验证）：停用账号后该账号的下一次请求返回 SESSION_REQUIRED，撤销其选定的角色后返回 SESSION_ROLE_REVOKED，各发布一条 `session.revoked`；非管理员调用返回 PERMISSION_DENIED。
- 状态与证据：进行中（模拟验证和联调通过，待独立复核）。2026-10-29：
  - 模拟验证：通过，命令同 T-ID-1，49 个通过。本卡对应的测试：
    - `test_admin.py`：停用账号、撤销选定的角色（各发布一条 `session.revoked`）、新建、账号名重复、分配的角色必须存在、管理员改密码、部门；
    - `test_router.py`：`/api/admin/accounts`、`/api/admin/departments`、非管理员返回 PERMISSION_DENIED。
  - 另外做了旧系统有、C09 没有的能力：部门的新建、修改、删除，账号列表按角色筛选，改自己的密码。见 `.reports/modules/identity/contract-gaps.md` 第 2–4 条。
  - 接入 assembly、realtime 后进行真实联调。
  - 2026-10-31 核对（`.reports/inventory-20261030/甲-任务卡核对.md`）：状态由"待联调"改为"完成"：联调 `tests/e2e/test_batch_a.py`（停用后 WebSocket 先收 `session.revoked` 再以 4401 关闭、下一次请求 401）通过（第 7 批合并后 `-m "oracle or redis"` 196 passed、0 failed、0 skipped，`.reports/batch7-20261030/merge/pytest-real-1.txt`）；浏览器 `frontend/tests/e2e/basic-1029.spec.ts:200`"场景 2 部门和账号"、`batch-d.spec.ts:280`"停用账号后，浏览器立即回到登录页"通过（第 7 批合并后端到端 42 passed，`.reports/batch7-20261030/merge/e2e-6.txt`）。`.reports/review/` 中没有本卡的复核记录，状态里补写"待独立复核"；按用户规则（`.kiro/steering/测试范围.md`）不阻断完成。

### T-ID-4 改已有账号的账号名、账号和部门的高级查询、当前用户的部门名称（第 8 批 G4）

- 归属与目标：ID-09（部门名称）、ID-11、ID-12；C04 v2、C09 v15。盘点 `.reports/inventory-20261030/甲-任务卡核对.md` 第四节 B10、B11、B12，`乙-旧系统功能对照.md` 第 2.12、2.13 节；用户 2026-10-31 回复"开始"。
- 前置输入：T-ID-3。
- 负责范围：`identity/accounts.py`、`admin.py`、`router.py`、`service.py`、`sessions.py`，新文件 `identity/search.py`；`pipeline/entity_rules.py` 的 `currentDeptName` 一行（write-pipeline 的默认值，取执行上下文的部门名称）。
- 交付物：`PUT /api/admin/accounts/{userId}` 可带 `username` 改账号名，重名 422；`GET /api/admin/accounts`、`/api/admin/departments` 可带 `advanced`；登录响应、`/api/me` 的当前用户和执行上下文带部门名称，默认值"当前部门名称"保存时取它。
- 验收标准：模拟验证：韩群 HY221020 改成 HY221021 后新名字能登录、旧名字不能，已登录的会话换成新账号名；改成汪春龙的 HY090702 时 422、`field` 为 username、原名不变；按姓名包含"群"且部门为技术中心查出韩群，部门 IN（采购部、市场部）查出程苏慧、汪春龙，状态为停用查出朱文俊；部门名称包含"部"查出采购部、市场部；登录、`/api/me`、`authenticate` 都带"技术中心"，调到市场部后马上变，市场部改名后 `/api/me` 起用新名称；`currentDeptName` 默认值取"技术中心"。真实验证：d_cg 上改名、重名 422、按姓名和部门查人员、按名称查部门。
- 状态与证据：进行中（模拟、真实、浏览器业务例子通过，待独立复核）。2026-10-31，第 8 批 G4，分支 `batch8/admin-shell`，原始输出在 `.reports/batch8-20261031/g4-admin-shell/`：
  - 模拟：`tests/identity/test_rename_and_department_name.py` 5 个、`test_search.py` 4 个、`test_router.py::test_rename_account_search_and_department_name`、`tests/pipeline/test_default_dept_name.py`；后端模拟全部 1322 passed。
  - 真实：`tests/identity/test_oracle.py::test_rename_account_on_oracle`、`test_advanced_search_and_department_name_on_oracle`；`-m "oracle or redis" tests/identity` 16 passed（含 Redis 会话）。
  - 浏览器：`frontend/tests/e2e/batch8-admin-shell.spec.ts` 的"改已有账号的用户名"、"人员管理高级查询"、"部门管理高级查询"3 个 passed（`e2e-2.txt`）。"默认值'当前部门名称'"用例要临时改成本核算的实体配置，按 `共同约定.md` 第 3 节待主代理合并后运行。
  - 与旧系统的差别：改名后已登录的会话马上换成新账号名（新平台的会话按账号版本刷新）；旧系统 JWT 带旧账号名到重新登录为止。历史 `UPDATE_BY` 都不改，与旧系统相同。
