# assembly 任务

模块说明：[assembly](../模块/assembly.md)。状态和证据的写法见[工程约定第 4 节](../工程约定.md)。本模块的任务通过验收即为完成。

相关业务例子：E01–E30（[业务例子](../业务例子.md)）。测试先行、真实约束证据和完成前复核见[工程约定](../工程约定.md)第 5–7 节。

### T-AS-1 后端工程骨架（第 0 组）

- 归属与目标：建立后端工程，实现 AS-07 的后端部分。
- 前置输入：无，可以最先开始。
- 负责范围：`backend/pyproject.toml`、`backend/.importlinter`、`backend/THIRD_PARTY_NOTICES.md`、`backend/src/cost_platform/` 下各模块的空包、`backend/tests/` 的目录、`.env.example`。
- 交付物：能安装和运行测试的工程；依赖规则检查配置；`.env.example` 增加 `PLATFORM_SESSION_IDLE_MINUTES=120`、`PLATFORM_LOCK_WAIT_SECONDS=5`、`PLATFORM_REQUEST_WAIT_SECONDS=5`。
- 接入责任：供全部后端模块使用。
- 验收标准：`uv sync`、`uv run pytest`、`uv run lint-imports` 都成功；故意让一个业务模块导入另一个业务模块时，`lint-imports` 失败。
- 状态与证据：完成。复核：`.reports/review/T-AS-1.md`（第一次，不通过）、`.reports/review/T-AS-1-2.md`（第二次，不通过）、`.reports/review/T-AS-1-3.md`（第三次，唯一的阻塞项是第二次修正说明未提交，已在 65dc9e6 补提交，复核者已核对过这段内容）。2026-10-26：`uv sync` 成功；`uv run pytest` 13 通过、0 失败；`uv run lint-imports` 2 条规则全部保持；临时让 approval 导入 pipeline、让 contracts 导入 config，`lint-imports` 分别报告规则被破坏并以退出码 1 结束，探针文件已删除。原始输出在 `.reports/T-AS-1/`。说明：import-linter 按系统编码（GBK）读取 `.importlinter`，所以该文件只用 ASCII 字符。`contracts/` 和 `adapters/` 中的旧草稿留给 T-CT-1 重写和删除。复核后修正（2026-10-26）：复核记录 `.reports/review/T-AS-1.md`（结论 NEEDS_CHANGES）。`.env.example` 的 `PLATFORM_DB_DSN` 改为占位值 `<host>:1521/<service>`（原值已在 git 历史中）；`.importlinter` 的 layers 规则改为以 `cost_platform` 为容器并开启 `exhaustive`，清单外的模块也会报错；新增 `tests/unit/test_import_rules.py`，在 pytest 中运行依赖规则，违反时 `uv run pytest` 失败；构建后端固定为 `setuptools==84.2.1`；approval 包说明删去"排队"。`platform` 命令入口指向的 `cost_platform.assembly.cli` 由 T-AS-2 交付，目前运行会报 ModuleNotFoundError。结果：`uv run lint-imports --no-cache` 2 条规则保持（`.reports/T-AS-1/lint-imports-2.txt`）；`uv run pytest -q tests/unit` 14 个通过；加入一个导入 config 的清单外模块后依赖规则测试失败，提示 not listed as layers（`.reports/T-AS-1/probe-outside-module.txt`），探针文件已删除。第二次复核（`.reports/review/T-AS-1-2.md`）后修正：上一次修正误把本条原文覆盖，已从 git 历史恢复并把修正说明接在后面；新增 `test_every_source_directory_is_a_package`，没有 `__init__.py` 的源码目录（依赖检查会跳过它们）让测试失败；`.importlinter` 增加 root-package 规则，禁止根包 `cost_platform/__init__.py` 导入平台模块。结果：`uv run lint-imports --no-cache` 3 条规则保持；根包导入 config、在 approval 下建没有 `__init__.py` 的目录并导入 pipeline，两种情况下依赖规则测试都失败，探针文件已删除（`.reports/T-AS-1/probe-root-and-namespace.txt`，内含命令和探针内容）；完整 `uv run pytest -v` 195 个通过（`.reports/T-AS-1/pytest-2.txt`）。第三次复核的两个低级别问题不阻塞，没有处理：只剩 `__pycache__` 的目录也会让目录检查失败（失败信息给出路径，删除即可）；`probe-outside-module.txt` 没有写命令和探针内容（结论已被第二次复核复现）。真实 DSN 和 AG Grid 授权已进入 git 历史，是否改写历史由用户决定。

### T-AS-2 后端组装根与中间件

- 归属与目标：实现 AS-01–AS-05、AS-08。
- 前置输入：开始前 T-AS-1、T-CT-3。
- 负责范围：`backend/src/cost_platform/assembly/`。
- 交付物：`create_app(settings)`；请求中间件；请求体和响应的统一处理（请求体经 contracts 的 `parse_wire` 解析，响应经 `dump_wire` 输出，满足 C01 第 1 节；路由不直接用契约类型声明请求体和 `response_model`）；阶段注册；启动初始化和后台任务的调度；命令行入口 `platform`；系统时钟和编号生成；`GET /health`。
- 接入责任：本任务只用 contracts 的替代实现组装；各模块的真实实现在 T-AS-4–T-AS-6 中接入。
- 验收标准（模拟验证，`PLATFORM_BACKEND=memory`）：没有会话的请求返回 401；写请求缺 CSRF 令牌返回 403；跨站 Origin 返回 ORIGIN_REJECTED；每个响应带 `X-Config-Version`；带 `X-Background-Request: 1` 的请求以 `touch=False` 认证；阶段按架构第 7 节的顺序调用；`platform --help` 只列出 `db` 和 `migrate`；用 snake_case 字段名或字符串形式的整数提交命令被拒绝，响应中可选字段没有值时不出现；预热完成前 `/health` 返回 503、业务请求返回 CONFIG_UNAVAILABLE，完成后 `/health` 返回 200；系统时钟和编号生成通过 `Clock`、`IdGenerator` 的契约测试（C08 第 14 节）。
- 状态与证据：未开始。

### T-AS-3 前端组装

- 归属与目标：实现 AS-06、AS-09 和 AS-07 的前端部分。
- 前置输入：开始前 T-FS-1、T-CT-4。验收前 T-RC-2。
- 负责范围：`frontend/src/main.ts`、`frontend/src/assembly/`、`vite.config.ts`、`vitest.config.ts`、`package.json`、dependency-cruiser 配置；根目录的 `.env.test`、`.env.prod`，以及 `.gitignore`、`.env.example` 中与前端有关的部分。
- 交付物：HTTP 客户端（C09、C03，带 CSRF，可以把请求标为后台请求；错误体用 T-CT-4 的解析函数检查）；实时客户端（C10，断线自动重连）；用 rules-core 交付的 `createCalcWorkerClient` 创建计算客户端（不另写 Worker 代码）；模块注册（C11）；开发服务器带 COOP、COEP 响应头。前端环境文件迁到根目录（AS-09），按以下顺序做，不能只改读取路径：
  1. 把 `frontend/.env`、`frontend/.env.test`、`frontend/.env.prod` 中仍在使用的变量（`VITE_BASE_URL`、`VITE_APP_TITLE`、`VITE_SERVICE_BASE_URL` 等）迁到根目录的 `.env.test`、`.env.prod`。逐个变量确认使用方，没有使用方的不迁移，迁移记录写明每个变量的去向。
  2. 修改 `vite.config.ts`，让 `envDir` 和 `loadEnv()` 都指向仓库根目录；`vitest.config.ts` 的 `envDir` 也指向根目录。`.env.test`、`.env.prod` 中不写 `VITE_AG_GRID_LICENSE_KEY`。
  3. 删除 `frontend/` 下的三个环境文件。`.gitignore` 中 `frontend/.env*` 的三条例外改为根目录的 `.env.test`、`.env.prod`；`.env.example` 保留 `VITE_AG_GRID_LICENSE_KEY`。
- 接入责任：前端各模块经 `ShellApi` 使用这些客户端；T-AS-7 与真实后端联调。
- 验收标准：用模拟实现时外壳和四个模块都能注册和打开；`ShellApi.calc` 能用 rules-core 的产物完成一次求值；一个前端模块导入另一个前端模块时 dependency-cruiser 报错。环境文件迁移前后分别按 `--mode test` 和 `--mode prod` 构建，两次产物中 `VITE_` 变量的取值相同，只有 `VITE_AG_GRID_LICENSE_KEY` 不同（迁移后取根目录 `.env` 中的值）。产物中没有 `PLATFORM_` 开头的变量名，也没有根目录 `.env` 中数据库、Redis 连接信息的值；检查脚本只输出是否命中，不输出这些值。根目录 `.env` 填了授权时，产物调用了 `setLicenseKey`。
- 状态与证据：未开始。

### T-AS-4 批次 A 联调

- 归属与目标：真实联调[架构](../架构与组装.md) 10.1、10.6、10.7。
- 前置输入：开始前 T-AS-9、T-AS-2；T-DB-1、T-DB-2、T-ID-1–T-ID-3、T-CF-1–T-CF-4、T-RT-1 为待联调；Redis 可用。
- 负责范围：在组装根中接入 db-core、identity、config、realtime 的真实实现；`backend/tests/e2e/` 中本批的用例。
- 交付物：接线代码；联调用例和结果记录。
- 接入责任：本任务负责接线和联调；发现的问题按架构第 8 节交提供方或使用方修改。
- 验收标准（真实联调，经 HTTP）：admin / admin123.. 能登录；保存一个页面配置后，已连接的 WebSocket 收到 `config.changed`，`X-Config-Version` 变大；停用账号后其 WebSocket 被关闭，下一次请求返回 401；两个后端进程时事件也能送达。
- 状态与证据：未开始。

### T-AS-5 批次 B 联调

- 归属与目标：真实联调架构 10.2、10.8、10.9。
- 前置输入：开始前 T-AS-4 完成；T-DB-3、T-AZ-1、T-RC-2、T-WP-1–T-WP-4、T-OP-1、T-DL-1、T-DL-2、T-QE-1–T-QE-3 为待联调。
- 负责范围：接入本批模块的真实实现，注册管道阶段，挂载路由，启动投递重试任务；本批的用例。
- 交付物：接线代码；联调用例和结果记录。
- 接入责任：同 T-AS-4。
- 验收标准（真实联调）：成本核算页面的保存（改一格、新增和删除明细、删除主表）结果正确；SQL 条数与 WP-10 一致；规则拒绝时整笔回滚；通知在提交后送达，发送失败不影响业务；列表和导出符合行权限。
- 状态与证据：未开始。

### T-AS-6 批次 C 联调

- 归属与目标：真实联调架构 10.3–10.5。
- 前置输入：开始前 T-AS-5 完成；T-AP-1–T-AP-3、T-OP-2 为待联调；C06 7.4、7.5、7.7 三个审批流已保存。
- 负责范围：接入 approval，注册其阶段，把 `FreezeReader` 接给 queries-export；本批的用例。
- 交付物：接线代码；联调用例和结果记录。
- 接入责任：同 T-AS-4。
- 验收标准（真实联调）：两个场景从保存触发到最终批准都正确，样例二只更新勾选的成本单；最终批准中任一步失败整体回滚；可冻结业务的保存多 1 条冻结查询；或签两人同时处理、审批提交与普通保存同时进行，结果都正确；两个命令同时为同一张单据发起审批时只有一个成功，另一个返回 FROZEN_BY_APPROVAL；重复批准不重复执行。
- 状态与证据：未开始。

### T-AS-7 批次 D 联调

- 归属与目标：从浏览器到数据库端到端验证架构 10.1–10.9。
- 前置输入：开始前 T-AS-6、T-AS-3 完成；全部前端任务为待联调。
- 负责范围：前端连接真实后端；生产环境由 FastAPI 以静态文件提供前端，与 `/api`、`/ws` 同源，响应带 COOP、COEP；`frontend/tests/e2e/` 的 Playwright 用例。
- 交付物：上述配置；端到端用例和结果记录。
- 接入责任：同 T-AS-4。
- 验收标准（真实联调）：在浏览器中完成两个审批场景；保存后不整页刷新，数据与数据库一致；同一单据的前端预览与后端计算按 C01 一致；管理员保存配置后，已打开的页面无需刷新即生效；复制一张成本单时只勾选部分明细行和字段，保存后数据库中的新单据只含这些行，未勾选的字段为空，计算字段为后端重算的值；停用账号后浏览器立即回到登录页。
- 状态与证据：未开始。

### T-AS-8 批次 E 联调

- 归属与目标：用真实旧数据验证迁移与切换（架构 10.10）。
- 前置输入：开始前 T-AS-7 完成；T-MG-1–T-MG-4 为待联调；用户确认三份清单。
- 负责范围：接入 migration 用到的导入接口；执行迁移、对账和切换演练。
- 交付物：演练记录。
- 接入责任：同 T-AS-4。
- 验收标准（真实联调）：迁移后页面能打开、能保存；对账没有未解释的差异；切换和回退按手册演练通过。
- 状态与证据：未开始。

### T-AS-9 最小真实链路（批次 0）

- 归属与目标：尽早跑通业务例子 E01，从浏览器到 Oracle 再回读。
- 前置输入：开始前 T-AS-1、T-AS-2、T-AS-3、T-FS-1、T-CT-1、T-CT-4，以及下列任务先交付的最小部分（这些部分在各任务中照样要通过其验收，只是先做）：
  - T-DB-1 的连接和事务，T-DB-3 只复制 `T_COST_PINGGU`；
  - T-ID-1、T-ID-2 中 admin 的登录和会话；
  - T-CF-1 中成本核算页主表的实体和页面配置（手工写一份），T-CF-4 的快照读取；
  - T-WP-1 的判重，T-WP-2 中主表单字段修改的加锁、合并和写入；
  - T-QE-1 的列表；
  - T-FS-2 的登录页，T-FP-2 中主表表格和单元格编辑，T-FP-3 中保存和局部刷新。
- 负责范围：组装根中接入以上真实实现；`backend/tests/e2e/test_e01.py`、`frontend/tests/e2e/e01.spec.ts`。不实现上述模块本身。
- 交付物：E01 的端到端用例和原始输出。
- 接入责任：本任务负责接线和联调；发现的问题按架构第 8 节交提供方修改。
- 验收标准（真实联调）：E01 全部满足；保存后数据库回读的值与页面显示相同；把 MEMO 改回原值再保存，数据库恢复原值。E01 中"4 条 SQL"由 T-WP-4 用 SQL 追踪核对。
- 状态与证据：进行中，正向流程已跑通，待独立复核。真实联调（d_cg）：`uv run pytest`（含 `tests/e2e/test_e01.py`）453 passed，`lint-imports` 3 kept；`pnpm exec playwright test`（`frontend/tests/e2e/e01.spec.ts`，本机 Chrome）1 passed；运行后只读查询 200680 的 MEMO 已恢复为空，PF_COMMAND 记有每次保存的审计差异。原始输出和过程在 `.reports/chain0/`（task_plan.md、progress.md）。手写配置由旧系统成本核算主表的列元数据生成（`.reports/chain0/gen_seed.py`），与旧系统不同的三处：MEMO 改为可编辑（E01 要改它）、页面开启审计、DOCID 固定在左侧。独立复核通过（`.reports/review/T-AS-9.md`，没有必须修改的问题）。已知限制，交给对应任务：链路 0 没有接计算，改了带动虚拟列的字段（例如汇率 FMRATE）保存后，页面局部刷新的计算列是旧值，刷新页面才对（T-WP-2、T-AS-5）；多行保存时每行单独加锁读取（T-WP-2）；连接池探活每个命令多一条 `SELECT 1 FROM DUAL`（T-WP-4 定计数口径）。
