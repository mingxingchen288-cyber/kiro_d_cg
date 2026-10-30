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
- 验收标准（模拟验证，内存组合：`backend/tests/assembly` 用 `build_app` 组装 contracts 的替代实现；2026-10-29 起不再用 `PLATFORM_BACKEND`）：没有会话的请求返回 401；写请求缺 CSRF 令牌返回 403；跨站 Origin 返回 ORIGIN_REJECTED；每个响应带 `X-Config-Version`；带 `X-Background-Request: 1` 的请求以 `touch=False` 认证；阶段按架构第 7 节的顺序调用；`platform --help` 只列出 `db` 和 `migrate`；用 snake_case 字段名或字符串形式的整数提交命令被拒绝，响应中可选字段没有值时不出现；预热完成前 `/health` 返回 503、业务请求返回 CONFIG_UNAVAILABLE，完成后 `/health` 返回 200；系统时钟和编号生成通过 `Clock`、`IdGenerator` 的契约测试（C08 第 14 节）。
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
- 状态与证据：进行中（AS-09、AS-07 的前端部分已完成；AS-06 没有在本任务中改动，见下文）。证据目录 `.reports/batch1-20261029/frontend-env/`（过程见 task_plan.md、progress.md、findings.md）。
  - AS-09（提交 9628f7b，2026-10-30）：`frontend/.env`、`.env.test`、`.env.prod` 中有使用方的 15 个变量迁到根目录 `.env.test`、`.env.prod`，取值不变；没有使用方的 7 个不迁移（每个变量的去向见 findings.md）。`vite.config.ts` 的 `envDir` 和 `loadEnv()` 都指向仓库根目录，`vitest.config.ts` 的 `envDir` 也指向根目录，`envPrefix` 不变；`frontend/` 下的三个环境文件已删除；`.gitignore` 放行根目录 `.env.test`、`.env.prod`。迁移前后按 `--mode test`、`--mode prod` 各构建一次（`dist-before-*`、`dist-after-*`），`check-dist.cjs` 去掉哈希和构建时间后比较：两种模式下 36 个文件中 35 个相同，唯一不同是入口 chunk 中授权由 `void 0` 变为根目录 `.env` 的值并调用 `setLicenseKey`；产物中没有 `PLATFORM_`，也没有数据库、Redis 连接信息的值（`check-dist.txt`，只输出是否命中）。
  - AS-07 前端（提交 034a446）：dependency-cruiser 18.7.0，配置 `frontend/.dependency-cruiser.cjs`，`pnpm lint:deps` 检查，`pnpm build`、`pnpm build:test` 先检查再构建。规则：前端模块之间不互相导入（类型导入也算）；page、config、approval、admin 在 src 中只导入本模块和 contracts；外壳代码不导入这四个模块；contracts 不依赖任何模块；只用 `rules-core/dist/web`，只有 assembly 和过渡的 `src/service/calc.ts` 导入它。7 个探针（admin 导入 page、page 导入 shell 的类型、config 导入外壳的 store、contracts 导入 approval、layouts 导入 admin、page 导入 rules-core 产物、导入 rules-core 源码）都让 `pnpm lint:deps` 失败（`probe-deps.txt`）；放入 admin 导入 page 的探针后 `pnpm build:test` 退出码 1（`probe-build.txt`）。已知违反 2 条，记在 `frontend/.dependency-cruiser-known-violations.json`，`--ignore-known` 跳过并在输出中给出条数：frontend-shell 的过渡视图 `src/views/page/[pageCode].vue` 导入 frontend-page 的 `src/modules/page/index.ts` 和 `src/modules/page/renderers/PageRoute.vue`（`lint-deps.txt` 中 `--no-ignore-known` 的输出）。外壳启动时已注册 frontend-page，按 `store/modules/route/index.ts` 的 `initAuthRoute`，同名的 elegant 路由被模块的路由代替，这个视图运行时不再使用（按代码判断，没有单独在浏览器中核对）；删除它要改 elegant 路由的生成和类型，属于 frontend-shell；删除后从豁免文件中去掉。模块发现用 `import.meta.glob`（`modules/shell/discover.ts`），不在检查范围内。
  - 结果（2026-10-30）：`pnpm typecheck` 退出码 0（`typecheck-2.txt`）；`pnpm test` 29 个文件 495 个通过（`vitest-2.txt`）；`pnpm lint:deps` 通过（`lint-deps.txt`）。
  - FS-05 授权的浏览器核对：开发服务器（9529，代理到后端 8081）和后端提供的构建产物（8081）上用本机 Chrome 打开成本核算页（`open-cost-page.cjs`；`ag-grid-dev-9529.json`、`ag-grid-dev-9529.png`，`static-8081.json`、`static-8081.png`）：表格的 3 个水印元素都带 `ag-hidden`，没有显示；控制台每个表格打印一次 AG Grid 授权错误 "Trial Period Expired. Your trial only license for AG Grid and AG Charts Enterprise expired on 30 May 2026."。授权已从根目录 `.env` 读到并传给 `setLicenseKey`，但这个授权是试用授权、已过期，要换成有效的授权，代码改不了。
  - 没做：AS-06 的客户端现在由外壳的 `src/modules/shell/app.ts` 创建、`discover.ts` 发现并注册模块，没有放进 `main.ts`、`src/assembly/`；"用模拟实现时外壳和四个模块都能注册和打开"没有在本任务中核对；独立复核。

### T-AS-4 批次 A 联调

- 归属与目标：真实联调[架构](../架构与组装.md) 10.1、10.6、10.7。
- 前置输入：开始前 T-AS-9、T-AS-2；T-DB-1、T-DB-2、T-ID-1–T-ID-3、T-CF-1–T-CF-4、T-RT-1 为待联调；Redis 可用。
- 负责范围：在组装根中接入 db-core、identity、config、realtime 的真实实现；`backend/tests/e2e/` 中本批的用例。
- 交付物：接线代码；联调用例和结果记录。
- 接入责任：本任务负责接线和联调；发现的问题按架构第 8 节交提供方或使用方修改。
- 验收标准（真实联调，经 HTTP）：admin / admin123.. 能登录；保存一个页面配置后，已连接的 WebSocket 收到 `config.changed`，`X-Config-Version` 变大；停用账号后其 WebSocket 被关闭，下一次请求返回 401；两个后端进程时事件也能送达。
- 状态与证据：真实联调通过，待独立复核（2026-10-30，G5，分支 batch2/acceptance）。证据目录 `.reports/batch2-20261030/g5-acceptance/`（task_plan.md、progress.md、findings.md）。
  - 用例 `backend/tests/e2e/test_batch_a.py`（3 个，标 oracle、redis）。`tests/e2e/servers.py` 按 `.env` 启动两个 uvicorn 进程（`create_app`，与生产启动相同；端口 `E2E_BACKEND_PORTS` 默认 8086、8087，共用 Redis 命名空间 `E2E_REDIS_NAMESPACE`，默认 `cost-platform-e2e`），用 httpx 和 websockets 经真实的 HTTP、WebSocket 访问，结束时停掉进程；环境变量只传给子进程。
  - 命令：在 `backend` 目录、`E2E_REDIS_NAMESPACE=cost-platform-wt-acceptance`（只在这条命令里设）执行 `uv run --with <rules-core wheel> pytest -q -p no:cacheprovider -m oracle tests/e2e/test_batch_a.py`，3 passed（`as4-pytest-2.txt`）。第一次运行 3 个都在等 `/health` 时超时（`as4-pytest-1.txt`）：后端已就绪，但 httpx 读到本机注册表的系统代理，连 127.0.0.1 也走代理；改为 `trust_env=False`、websockets `proxy=None` 后通过。
  - 登录：admin / admin123.. 在两个进程上都登录成功，自动选定 ADMIN，`/api/me` 有菜单。
  - 配置保存：A（8086）上 `PUT /api/config/items/page/COST_PINGGU` 把主表 MEMO 列宽改为 321，A、B（8087）上订阅了 COST_PINGGU 的 WebSocket 收到同一条 `config.changed`（eventId 相同，version 为新代号），A、B 的 `X-Config-Version` 都大于改前，B 的页面视图中 MEMO 宽 321；再保存回原内容，两边都收到下一条 `config.changed`，B 的列宽恢复，配置项内容与改前相同。
  - 停用账号：chengben01 分别在 A、B 登录并连 `/ws`；admin 在 A 停用它，两个连接都先收到 `session.revoked`（`accountDisabled`），再以 4401 关闭；chengben01 在 A、B 上的 `/api/me` 都返回 401 SESSION_REQUIRED。恢复启用后 chengben01 能在 B 重新登录，账号的姓名、部门、角色与改前相同。
  - 恢复核对（只读，`q03-as4-恢复核对.out.txt`）：page.COST_PINGGU 版本 5→7、内容长度 2259 与改前相同、不含 MEMO；chengben01 enabled=1、部门 14、角色 COST_ACCOUNTANT。没有改代码。
  - 复跑（2026-10-30，T-AS-5 把两个后端进程移到 `tests/e2e/conftest.py`、整个测试会话共用之后）：`test_batch_a.py`、`test_batch_b.py`、`test_batch_c.py` 一起运行 13 passed（`e2e-backend-all-1.txt`）；`uv run --refresh-package cost-rules-core --with <wheel> pytest -q -p no:cacheprovider -m "not oracle and not redis"` 1188 passed（`pytest-unit-1.txt`），`uv run lint-imports --no-cache` 5 kept（`lint-imports-1.txt`）。最终只读核对见 `q12-最终核对.out.txt`。

### T-AS-5 批次 B 联调

- 归属与目标：真实联调架构 10.2、10.8、10.9。
- 前置输入：开始前 T-AS-4 完成；T-DB-3、T-AZ-1、T-RC-2、T-WP-1–T-WP-4、T-OP-1、T-DL-1、T-DL-2、T-QE-1–T-QE-3 为待联调。
- 负责范围：接入本批模块的真实实现，注册管道阶段，挂载路由，启动投递重试任务；本批的用例。
- 交付物：接线代码；联调用例和结果记录。
- 接入责任：同 T-AS-4。
- 验收标准（真实联调）：成本核算页面的保存（改一格、新增和删除明细、删除主表）结果正确；SQL 条数与 WP-10 一致；规则拒绝时整笔回滚；通知在提交后送达，发送失败不影响业务；列表和导出符合行权限。
- 状态与证据：真实联调通过，其中 SQL 条数有一项待用户决定（见下），待独立复核（2026-10-30，G5）。证据目录 `.reports/batch2-20261030/g5-acceptance/`。
  - 用例 `backend/tests/e2e/test_batch_b.py`（6 个，标 oracle、redis），后端为 `tests/e2e/conftest.py` 启动的两个 uvicorn 进程（同 T-AS-4）；"发送失败"一条在测试进程内用 `create_app` 组装。测试产生的审批、投递、站内通知、命令记录由 `tests/e2e/dcg.py` 的 `Cleanup` 在结束时删掉，业务数据改了再改回或自己建、自己删。
  - 命令：同 T-AS-4，换成 `tests/e2e/test_batch_b.py`，加 `-rP` 输出语句：6 passed（`as5-pytest-4.txt`，含三次保存的全部 SQL）。第一次运行 5 passed、1 failed（`as5-pytest-1.txt`）：SQL 条数比预期多 1 条读取列定义（见下）；这次失败在第一步之后，2550 的主表备注留成"G5 联调备注"，已用 `restore_memo.py` 经平台改回原值并删掉那次的命令记录，用例加了失败时改回的 fixture `restore_2550`。
  - 改一格（成本单 2550）：主表 MEMO 改了再改回，其余列和明细不变；原辅料 206324 预胶化淀粉每片含量 15→16，每批数量 16、每批成本 200，主表 TOTAL_FL 等于辅料合计 ÷1.13（有原料时）按 8 位小数四舍五入，TOTAL_COST 等于 TOTAL_YL+TOTAL_FL+TOTAL_BC，其他明细行不变，命令结果的值与数据库相同；改回 15 后主表、明细全部列与改前相同。
  - 新增和删除明细、删除主表：admin 新建成本单（主表 + 聚维酮K30、预胶化淀粉两行，单价与物料清单执行价相同，不进入审批），`idMap` 覆盖 3 个临时编号，每批数量、每批成本、TOTAL_FL 937.5（没有原料不除以 1.13）正确；一次保存新增玉米淀粉、删除预胶化淀粉后剩两行，TOTAL_FL 1685；删除主表后主表和明细都不存在，结果中这一行 `deleted`。
  - SQL 条数（命令审查 WP-17 读取，计数口径同 T-WP-4 的 SqlTracer）：改主表一个字段 6 条 = WP-10 的 4 条 + 冻结查询 1 条 + 读取列定义 1 条；提交相同的值 3 条 = 2 条 + 冻结查询 1 条（结果 unchanged，回滚，没有命令记录）；改一条明细并重算汇总 9 条 = 6 条（插入命令记录、锁主表行、一条 UNION ALL 读两个明细实体、改明细、改主表、完成命令记录）+ 冻结查询 1 条 + 读取列定义 1 条 + 审批流 COST_TO_GOODS 对这一行的入口条件 1 条。读取列定义是 db-core 的 SchemaInspector 取列的小数位（WP-15），每个进程每张表只读一次，进程启动后第一次写这张表的命令才有，之后的命令没有。
  - 待用户决定：改原辅料、包材的行时，COST_TO_GOODS 的入口条件（`SELECT 1 FROM DUAL WHERE (…)`）对每个改动的行执行 1 条（approval AP-01：operations 选中的行逐行代入）。WP-10 的"改一条明细并重算汇总 6 条，可冻结业务另加 1 条"没有计这一条，所以这种保存在已启动的进程上是 8 条。条件是 SQL 片段，平台不解析它，不能事先判断"只改每片含量不会成立"而跳过。场景见汇报。
  - 规则拒绝：一次保存改主表备注、206323 备注，并把 206324 每片含量改成 0，返回 422 RULE_REJECTED，details 为"每片含量必填且必须大于0"（206324、PER_HL）；主表和明细都不变，PF_COMMAND 没有这次的记录，命令审查记为 rejected。
  - 通知：chengben01 在 B 把 206323 单价 75→90，进入审批 COST_TO_GOODS；连在 A 上的 admin 的 WebSocket 收到 `notification`（"您有来自于成本核算页面，业务单据为2550的审批"），这时 PF_DELIVERY 中这条为 sent、发送 1 次，审批为 pending，站内通知未读列表中有它；业务表单价仍是 75。随后 admin 驳回，冻结解除，单价不变。
  - 发送失败（模拟）：测试进程内把 `DeliveryStore.write_inbox` 换成对本测试的投递抛错，chengben01 提交审批照常返回 approvalSubmitted，审批 pending、冻结 2550 和物料清单 25 都已提交；投递记录为 failed、发送 1 次、last_error 为模拟的错误、有下次重试时间，没有站内通知。
  - 行权限：COST_ACCOUNTANT 临时加 `rows: "DOCID IN (2550, 2556)"`，chengben01 的列表 total 2（2550、2556），按主键取 2550、200680 只返回 2550，加载 200680 返回 404，默认导出（mode page）的 xlsx 只有这两行；admin 的列表仍是全部 700 行。改回后角色内容与改前相同，chengben01 又能看到全部。
  - 恢复核对（只读，`q05-as5-恢复核对.out.txt`）：审批只有 13、14，冻结记录 0，投递 4 条、站内通知 4 条（与改前相同）；T_COST_PINGGU 700 行；2550 主表和 14 行明细与改前相同；role.COST_ACCOUNTANT 版本 1→7、内容与改前相同；11:00 以后的 PF_COMMAND 为 0。没有改代码。

### T-AS-6 批次 C 联调

- 归属与目标：真实联调架构 10.3–10.5。
- 前置输入：开始前 T-AS-5 完成；T-AP-1–T-AP-3 为待联调；C06 7.8、7.9、7.10 三个审批流已保存。
- 负责范围：接入 approval，注册其阶段，把 `FreezeReader` 接给 queries-export；本批的用例。
- 交付物：接线代码；联调用例和结果记录。
- 接入责任：同 T-AS-4。
- 验收标准（真实联调）：两个场景从保存触发到最终批准都正确，样例二只更新勾选的成本单；最终批准中任一步失败整体回滚；可冻结业务的保存多 1 条冻结查询；或签两人同时处理、审批提交与普通保存同时进行，结果都正确；两个命令同时为同一张单据发起审批时只有一个成功，另一个返回 FROZEN_BY_APPROVAL；重复批准不重复执行。
- 状态与证据：样例一及其余各条真实联调通过；样例二没做（d_cg 没有它的配置，见下）。待独立复核（2026-10-30，G5）。证据目录 `.reports/batch2-20261030/g5-acceptance/`。
  - 用例 `backend/tests/e2e/test_batch_c.py`（4 个，标 oracle、redis），后端同 T-AS-5。用 d_cg 已发布的审批流 COST_TO_GOODS（C06 7.8 去掉第 2 级，或签，ADMIN 角色）和成本单 2550 的原辅料 206323 聚维酮K30（物料 25，单价 75 = 执行价 75）。或签的第二个审批人是测试临时建的 ADMIN 角色账号（随机密码，结束时连同角色分配删掉）；测试产生的审批、投递、站内通知、命令记录结束时删掉。
  - 命令：同 T-AS-4，换成 `-rP tests/e2e/test_batch_c.py`，4 passed（`as6-pytest-1.txt`）。
  - 从保存到最终批准（样例一）：chengben01 把单价 75→90，命令结果 approvalSubmitted，审批第 1 级 pending，冻结 T_COST_PINGGU 2550 和 T_COST_GOODS 25，业务表不变；详情的进度为"管理员审批 或签 系统管理员 待处理"，原辅料单价 75.00→90.00、金额 750.00→900.00，物料清单单价 75.00→90.00。通过后单价 90、每批成本 900、主表 TOTAL_FL 增加 150÷1.13，物料清单执行价 90、其他列不变，冻结记录删除，审批 approved/applied。最后单价改回 75（再走一次审批），2550 和物料清单 25 与改前相同。
  - 可冻结业务的冻结查询：冻结期间 admin 保存 2550 主表备注返回 409 FROZEN_BY_APPROVAL（details 指向本审批），这次命令 3 条 SQL：插入命令记录、锁主表行、查 PF_APPROVAL_FREEZE，第 3 条就是可冻结业务多出的 1 条；正常保存时的条数见 T-AS-5（每次都有这 1 条）。
  - 或签两人同时处理：admin（A）和测试审批人（B）各自读详情取指纹后同时通过，一个 200 生效，另一个 403 PERMISSION_DENIED"当前用户不是本级尚未处理的审批人"（这次 admin 生效）；处理记录只有 1 条 pass，数据只写一次。
  - 重复批准：生效的一方用同一请求键再提交通过，返回与第一次相同的结果，处理记录仍为 1 条，2550 和物料清单不再变化。
  - 最终批准中一步失败：测试另开连接 `SELECT … FOR UPDATE` 锁住 T_COST_GOODS 25，admin 通过时写物料清单执行价等锁 5 秒后返回 409 DOCUMENT_BUSY；审批仍为第 1 级 pending，两条冻结记录还在，没有处理记录、没有命令记录，单价和执行价都不变（审批处理阶段已写的处理记录、勾选和解冻一起回滚）。释放锁后驳回。
  - 审批提交与普通保存同时进行：chengben01 改单价和 admin 改主表备注同时提交，两个命令按 2550 主表行锁先后执行。这次先执行备注的保存（saved，备注写入），审批随后照常提交；另一种先后（先提交审批）时备注的保存返回 FROZEN_BY_APPROVAL，用例两种都核对，这次没有出现。驳回后改回备注。
  - 两个命令同时为同一张单据发起审批：chengben01 改 206323 单价、admin 改 206324 预胶化淀粉单价（12.5→13）同时提交，只有一个 approvalSubmitted（这次 chengben01），另一个 409 FROZEN_BY_APPROVAL，details 的 approvalId 为先提交的审批；2550 只有这一个 pending 的审批。驳回。
  - 样例二没做：C06 7.9（TECH_CUSTOMER_MATERIAL）要审批流配置、部门 1069 技术中心和该部门的账号，d_cg 的 PF_DEPARTMENT 只有 14 成本部，也没有这条审批流；C06 7.10（GOODS_TO_COST）要物料清单页 GOODS_PRICE_MANAGE、实体 COST_GOODS_PRICE、它的保存操作、菜单和角色权限，以及审批流本身，d_cg 都没有（表 T_COST_GOODS、T_COST_PINGGU_DTL_LQ 和视图 T_COST_GOODS_PRICE_V、V_COST_PINGGU_MATERIAL_LQ、V_COST_PINGGU_PACKAGE_LQ 已有，`q08-样例二所需对象.out.txt`）。按要求没有新建页面配置。"样例二只更新勾选的成本单"因此也没有验证。
  - 恢复核对（只读，`q06-as6-恢复核对.out.txt`）：本测试的审批都已删掉，冻结记录 0；账号只有 admin、chengben01；2550 主表、206323、206324 与改前相同，物料清单 25 为 75/75、68 为 12.5/12.5。核对时另有审批 23（成本单 200742，admin 11:32 提交、11:35 撤回）和它的 1 条投递、2 条命令记录，不是本测试产生的（`q07-审批23.out.txt`），没有动。没有改代码。

### T-AS-7 批次 D 联调

- 归属与目标：从浏览器到数据库端到端验证架构 10.1–10.9。
- 前置输入：开始前 T-AS-6、T-AS-3 完成；全部前端任务为待联调。
- 负责范围：前端连接真实后端；生产环境由 FastAPI 以静态文件提供前端，与 `/api`、`/ws` 同源，响应带 COOP、COEP；`frontend/tests/e2e/` 的 Playwright 用例。
- 交付物：上述配置；端到端用例和结果记录。
- 接入责任：同 T-AS-4。
- 验收标准（真实联调）：在浏览器中完成两个审批场景；保存后不整页刷新，数据与数据库一致；同一单据的前端预览与后端计算按 C01 一致；管理员保存配置后，已打开的页面无需刷新即生效；复制一张成本单时只勾选部分明细行和字段，保存后数据库中的新单据只含这些行，未勾选的字段为空，计算字段为后端重算的值；停用账号后浏览器立即回到登录页。
- 状态与证据：生产静态服务已完成并真实验证；端到端场景中样例一的审批和其余 5 条真实联调通过（2026-10-30，G5，见本条"端到端场景"），样例二没做（d_cg 没有配置）；待独立复核。证据目录 `.reports/batch1-20261029/frontend-env/`、`.reports/batch2-20261030/g5-acceptance/`。
  - 生产静态服务（提交 5323ef2，2026-10-30）：`assembly/app.py` 的 `create_app` 在 `frontend/dist` 有 `index.html` 时把它挂在 `/` 下（`FrontendFiles`，在各模块的路由之后），响应带 `Cross-Origin-Opener-Policy: same-origin`、`Cross-Origin-Embedder-Policy: require-corp`，找不到文件、又不在 `api`、`assets`、`ws`、`health` 下的路径返回 `index.html`。前端构建产物以页面的 origin 作为后端地址（`src/service/platform.ts`），WebSocket 为 `ws://<页面 origin>/ws`。后端加依赖 websockets 17.3：没有它 uvicorn 对 `/ws` 的握手返回 404（日志 "No supported WebSocket library detected"）。生产环境的 `PLATFORM_ALLOWED_ORIGINS` 要列出用户打开的后端地址（`.env.example` 已写明）。
  - 真实验证：`pnpm build` 后在 8081 启动后端（`PLATFORM_REDIS_NAMESPACE=cost-platform-wt-frontend-env`），`check-static-headers.ps1` 发真实 HTTP 请求（`static-headers.txt`）：`/`、`/page/COST_PINGGU`、入口 js、`worker-*.js`、`rules_core-*.wasm`、`favicon.svg` 都是 200，带 `same-origin` 和 `require-corp`，wasm 为 `application/wasm`，js 为 `text/javascript`；`/page/COST_PINGGU` 的内容与 `dist/index.html` 相同；`/health`、`/api/me` 不带这两个头，`/api/no-such-api`、`/assets/no-such-file.js` 为 404。本机 Chrome 打开 `http://127.0.0.1:8081/`，admin 登录后打开成本核算页（`static-8081.json`、`static-8081.png`）：`crossOriginIsolated` 为 true，主表 19 行，`WebSocket /ws` accepted；改成本单 2550 的备注（不保存，`static-8081-calc.png`）后，`/api/rules-packs/COST_PINGGU/2860`、`worker-*.js`、`rules_core-*.wasm` 都是 200，页面没有"本地预览失败/不可用"。模拟验证：`tests/assembly/test_app.py::test_frontend_files_are_served_with_cross_origin_isolation`。`uv run --with <rules-core wheel> pytest -q -p no:cacheprovider -m "not oracle and not redis"` 1177 passed（`pytest-1.txt`），`uv run lint-imports --no-cache` 5 kept（`lint-imports-1.txt`）。
  - 端到端用例（提交 fe2f472：端口可用 `E2E_BACKEND_PORT`、`E2E_FRONTEND_PORT` 改）：后端 8081、开发服务器 9529 上 `pnpm exec playwright test` 4 个中 2 个通过（E01、系统管理），2 个失败（`playwright-1.txt`、`playwright-2.txt`）。失败的是 `cost-detail.spec.ts` 的两个用例，在打开页面后找"原料/辅料"页签时失败，还没有写入：d_cg 中 admin 在成本核算页的个人配置是 `{"detailMode":"stack"}`（`read-personal.cjs` 只读查看），明细按"堆叠"显示，没有页签。这个个人配置不是本任务设置的，没有改回。
  - 没做：验收标准中的两个审批场景、保存后不整页刷新与数据库一致、前端预览与后端计算一致、配置保存后已打开的页面生效、复制成本单、停用账号回到登录页；独立复核。（2026-10-30 G5 已做，见下一项。）
  - 端到端场景（2026-10-30，G5，分支 batch2/acceptance）：样例一的审批场景和其余 5 条真实联调通过；样例二没做（同 T-AS-6，d_cg 没有配置）。待独立复核。证据目录 `.reports/batch2-20261030/g5-acceptance/`。
    - 用例 `frontend/tests/e2e/batch-d.spec.ts`（5 个），共用写法 `frontend/tests/e2e/support.ts`；结束时 `backend/tests/e2e/cleanup.py` 删掉本次运行的命令记录、投递、站内通知和审批记录（按浏览器收到的命令结果中的请求键、审批编号）。环境：后端 8086（`PLATFORM_REDIS_NAMESPACE=cost-platform-wt-acceptance`、`PLATFORM_ALLOWED_ORIGINS=http://localhost:9534`），开发服务器 9534（`VITE_SERVICE_BASE_URL=http://localhost:8086`），本机 Chrome；命令 `pnpm exec playwright test tests/e2e/batch-d.spec.ts`（`E2E_BACKEND_PORT=8086`、`E2E_FRONTEND_PORT=9534` 只在这条命令里设）。最后一次 5 passed（`as7-playwright-6.txt`）；过程中 `as7-playwright-2.txt`、`-3.txt` 的失败见下面的缺陷和 progress.md。
    - 缺陷 1（已修）：开发服务器的代理不转发 WebSocket。浏览器里经 `ws://localhost:9534/proxy-default/ws` 新建连接 8 秒没有打开，直连 8086 能打开；页面因此收不到 `config.changed`、`session.revoked` 和通知。`frontend/build/config/proxy.ts` 的代理项加 `ws: true` 后，经代理连上并收到 `pong`。构建产物由后端同源提供（上面的生产静态服务），不受影响。
    - 缺陷 2（已修，frontend-page，见 T-FP-5）：复制成本单时没勾的数值字段保存后为 0（例如"年需求量"），不是空：编辑缓冲不写为空的字段，后端按 WP-16 给新增行补默认值。改为复制出的行把为空的可写字段写成 null。
    - 保存后不整页刷新、数据与数据库一致：admin 把 2550 的 206324 每片含量 15→16，保存后 window 上的标记和主表表格的 DOM 元素都还在；页面上每片含量、每批数量、每批成本和主表 TOTAL_FL、TOTAL_COST、COST_PERBOX、JGF_BATCH 与后端重新读出的单据按页面视图的小数位显示相同。最后经接口改回 15，单据与改前相同。
    - 前端预览与后端计算：在页面加载前包一层 Worker，记下 rules-core 的求值结果；改 16 后页面按预览显示每批成本 200，保存后把命令结果中 2 行的 14 个计算字段与预览比较（`as7-playwright-6.txt` 中列出每个字段的预览值和后端值）。后端写入前按 WP-15 保留 8 位小数（例如 TOTAL_FL 预览 6439.3805309734513274336283184、后端 6439.38053097；SALEMONEY 预览 210861.74999999999999999999999、后端 210861.75000000），所以预览值先按 WP-15 处理再按 C01 第 3 节比较，14 个都一致；不先处理时，凡是预览有 8 位以上小数的字段都判为不一致（例如 SALEMONEY 的 210861.7499… 与 210861.75）。命令结果只给出 WP-15 处理后的值，后端求值的原始结果没有对外接口，所以没有做不处理的比较。
    - 配置保存后已打开的页面生效：chengben01 开着成本核算；admin 经接口保存页面配置，把主表"产品英文名"设为不显示，chengben01 的页面经 WebSocket 收到 `config.changed`，整张表找不到这一列，页面没有刷新；改回后这一列又出现，配置内容与改前相同。没有用列宽：页面配置的列宽是 `initialWidth`，已打开的表格不跟着变（FP-08、FP-09 的设计），看不出是否生效。改回后这一列出现在表格最右边，不在原来的第 4 列（AG Grid 把重新出现的列放在最后），刷新后回到原位置，没有改。
    - 复制成本单：admin 复制 2550，主表不勾"备注""年需求量"，原辅料只勾聚维酮K30、玉米淀粉两行、不勾"额外投料量""备注"，包材一行不勾；保存后新单据只有这两行原辅料、没有包材，备注和年需求量为空，额外投料量、明细备注为空，批量、包装规格、收率等勾了的字段与 2550 相同；每批数量 10、42.5，每批成本 750、935，TOTAL_FL 1685（没有原料不除以 1.13，2550 为 6428.31858407），为后端按新单据重算的值。最后经接口删掉新单据（单据和明细都不存在）。
    - 停用账号：chengben01 开着成本核算，admin 经接口停用它，chengben01 的页面不用任何操作就回到登录页；恢复启用后能重新登录，账号与改前相同。
    - 审批（样例一）：chengben01 把 206323 单价 75→90，预览每批成本 900，保存提示"已提交审批"，单价仍显示 75.00；双击单价弹出审批进度（审批编号为本次的审批），不进入编辑。admin 的页面经 WebSocket 收到链接为 `/approval/<编号>` 的通知，消息中心最上面一条是"…业务单据为2550的审批"；从菜单"待办"找到这一行点"处理"，详情中有 75.00 和 90.00，点"通过"提示"本级审批已提交"、状态"已通过"；chengben01 的页面收到"…已通过"的通知；单据中单价 90、每批成本 900。最后经接口把单价改回 75（再走一次审批），单据与改前相同。
    - 恢复核对（只读，`q11-as7-恢复核对.out.txt`）：本次运行没有留下审批、冻结、投递和命令记录（表中另有别组的审批 23、29 和 11:32–11:57 的命令记录）；2550、206323、206324、物料清单 25 与改前相同；page.COST_PINGGU 版本 15、内容长度 2259 与改前相同；COST_ACCOUNTANT 未变；chengben01 已启用；T_COST_PINGGU 仍为 700 行。
    - 修了代码：`frontend/build/config/proxy.ts`（缺陷 1）；`frontend/src/modules/page/edit-buffer.ts`、`copy.ts`（缺陷 2）。`pnpm typecheck` 通过；`pnpm test` 31 个文件 502 passed（`vitest-1.txt`）；`pnpm lint:deps` 通过（`lint-deps-1.txt`）。

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
- 状态与证据：进行中，正向流程已跑通，待独立复核。真实联调（d_cg）：`uv run pytest`（含 `tests/e2e/test_e01.py`）453 passed，`lint-imports` 3 kept；`pnpm exec playwright test`（`frontend/tests/e2e/e01.spec.ts`，本机 Chrome）1 passed；运行后只读查询 200680 的 MEMO 已恢复为空，PF_COMMAND 记有每次保存的审计差异。原始输出和过程在 `.reports/chain0/`（task_plan.md、progress.md）。手写配置由旧系统成本核算主表的列元数据生成（`.reports/chain0/gen_seed.py`），与旧系统不同的四处：MEMO 改为可编辑（用户 2026-10-28 确认，正式迁移同样处理，见 migration 的 MG-14）、页面开启审计、DOCID 固定在左侧、参与计算的 10 个输入字段（批量、包装规格、汇率等）暂时不可编辑。2026-10-28 起 d_cg 的 T_COST_PINGGU 按 DB-03 重建：只有页面显示的 43 列和 FORM 等 4 列，原 10 个虚拟列是普通列，计算接入（T-WP-2、T-AS-5）之前改这些输入会让计算列留着旧值，所以先不开放。2026-10-29 已按旧系统开放这 10 个字段（原辅料、包材的物料ID、每片含量、额外投料量、单价一并开放），17 条计算规则已配置（seed 的 `rule.R_*.json`，过程在 `.reports/editable-20261029/`）。独立复核通过（`.reports/review/T-AS-9.md`，没有必须修改的问题）。已知限制，交给对应任务：链路 0 没有接计算（T-WP-2、T-AS-5）；多行保存时每行单独加锁读取（T-WP-2）；连接池探活每个命令多一条 `SELECT 1 FROM DUAL`（T-WP-4 定计数口径）。链路 1（成本核算主从页的明细，2026-10-28，待独立复核）。真实联调（d_cg）：`.reports/chain0/run-tests.ps1 -n c1-1` 457 passed、`lint-imports` 3 kept（`.reports/chain0/pytest-all-c1-1.txt`、`lint-imports-c1-1.txt`），其中 `backend/tests/e2e/test_cost_detail.py` 4 个；`pnpm exec playwright test` 3 passed（E01 和 `frontend/tests/e2e/cost-detail.spec.ts` 2 个，`.reports/chain1/15-playwright-1.txt`）；`pnpm typecheck` 通过，eslint 0 个问题，`pnpm test` 72 passed。验收单据改用成本单 2550：200680 已不在 cmx 中、没有明细（`.reports/chain1/findings.md`）；改的是原辅料第一行 DTLID 206323 的备注和客户指定。运行后只读查询：200680 的主表 MEMO 为空，206323 的 MEMO 为空、CUSTOMER_SPECIFIED 为 0，明细表与 cmx 双向 MINUS 仍为 0，PF_COMMAND 记有每次保存的审计差异（`.reports/chain1/16-测试后核对.out.txt`）。过程记录在 `.reports/chain1/`。已知限制：明细的计算字段和新增、复制、删除没有开放；数值没有按 scale 显示（T-FP-2）。
