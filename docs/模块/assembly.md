# assembly

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：后端插件清单、启动注册表和命令行入口；HTTP 中间件和执行上下文；启动和停止各插件的后台任务；前端的 `main.ts` 和构建配置；依赖规则检查；系统时钟和编号生成；按批次联调；端到端测试。
- 不负责：任何业务规则，它们都在各业务模块中。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `backend/src/cost_platform/assembly/`、`frontend/src/main.ts`、`frontend/src/assembly/` |
| 配置 | `backend/pyproject.toml`、`.importlinter`、前端的 `vite.config.ts`、`vitest.config.ts`、`package.json`、dependency-cruiser 配置；根目录的 `.env.example`、`.env.test`、`.env.prod` |
| 测试 | `backend/tests/e2e/`、`frontend/tests/e2e/` |

## 3. 对外契约

按[架构第 6 节](../架构与组装.md)组装，挂载 `POST /api/commands`、`GET /health`。

- AS-01：组装用插件清单（[架构 6.1](../架构与组装.md)）：运行时只有 Oracle + Redis 一份插件清单（`oracle_plugins`），不再用 `PLATFORM_BACKEND`。内存组合用于 assembly 的模拟验证（`backend/tests/assembly`，用 contracts 的替代实现，经 `build_app(插件清单)` 组装），不是运行模式。
- AS-02：请求中间件：调用 `Authenticator`（请求带 `X-Background-Request: 1` 时传 `touch=False`）→ 调用 `ConfigSnapshotReader` → 生成执行上下文（[C04](../契约/C04-执行上下文.md)）→ 交给路由。写请求的 Origin 不在 `PLATFORM_ALLOWED_ORIGINS` 中时返回 403 ORIGIN_REJECTED；错误按 [C03](../契约/C03-错误.md) 输出；每个响应带 `X-Config-Version`。
- AS-03：管道阶段由各模块的插件注册，执行先后由 orchestration 的 `STAGE_ORDER` 决定（架构第 7 节），assembly 不排阶段。
- AS-04：启动时在后台任务中按注册表 setup 的先后依次执行各插件的 start，HTTP 服务不等它们完成就开始应答；全部 start 完成后进入就绪。现在的先后：config（导入基础配置 → CF-10 → CF-13 预热 → 配置恢复任务）→ identity 的 ID-06 → realtime 的 Redis 订阅 → delivery 的投递重试。就绪前，`/health` 返回 503 `{"status": "starting"}`，其他 HTTP 请求不进入路由，返回 503 CONFIG_UNAVAILABLE（C03 的错误响应体），响应不带 `X-Config-Version`；就绪后 `/health` 返回 200。某个插件的 start 失败时记 ERROR 日志（含插件名），平台保持未就绪（CF-13），`/health` 返回 503 `{"status": "failed"}`。关闭时先取消还没结束的启动任务，再按相反顺序调用 stop：只 stop 已经 start 成功的插件，以及没有 start、只有 stop 的插件（例如 db-core 释放连接池）。`/ws` 不经过 HTTP 中间件；就绪前 realtime 的订阅还没有启动。
- AS-05：命令行 `platform` 只有 `db` 和 `migrate` 两类子命令。
- AS-06：前端 `main.ts` 创建 HTTP 客户端、实时客户端（断线自动重连），并用 rules-core 交付的 `createCalcWorkerClient` 创建计算客户端，加载外壳，再注册各前端模块。前端服务的响应带 COOP 和 COEP 头，供 rules-core 的 WASM 使用：开发时由 Vite 开发服务器加（`vite.config.ts`）；生产环境由后端在 `/` 下提供 `frontend/dist` 中的构建产物，与 `/api`、`/ws` 同源，这些响应带两个头，前端路由的路径返回 `index.html`（`assembly/app.py` 的 `FrontendFiles`，T-AS-7）。构建产物以页面的 origin 作为后端地址，`VITE_SERVICE_BASE_URL` 只给开发服务器用。
- AS-07：import-linter 和 dependency-cruiser 检查[架构第 3 节](../架构与组装.md)的依赖规则，违反时构建失败。
- AS-08：提供系统时钟和编号生成的真实实现。
- AS-09：前端只读取仓库根目录的环境文件。`vite.config.ts` 的 `envDir` 和其中调用的 `loadEnv()` 都指向仓库根目录，`frontend/` 下不放环境文件，以免出现两处读取位置。保留 Vite 默认的 `VITE_` 前缀：不修改 `envPrefix`，调用 `loadEnv()` 时也不传空前缀。这样只有 `VITE_` 开头的变量进入浏览器和构建产物，根目录 `.env` 中数据库、Redis 等 `PLATFORM_*` 变量不会暴露。各文件的用途如下：
  - 根目录 `.env` 不进版本库，放密钥和本机配置，包括 AG Grid 授权 `VITE_AG_GRID_LICENSE_KEY`（frontend-shell 的 FS-05）。后端也只读这个文件。
  - 根目录 `.env.test`、`.env.prod` 进版本库，只放前端的公开配置。`.env.test` 供 `--mode test` 使用（开发服务器、`build:test` 和 vitest），`.env.prod` 供 `--mode prod` 使用（`build`）。Vite 读取时这两个文件优先于 `.env`，所以其中不能出现 `VITE_AG_GRID_LICENSE_KEY`，即使写成空值也会把 `.env` 中的授权覆盖掉。
  - 本机要覆盖公开配置时，写在 `.env.test.local`、`.env.prod.local` 中，这两个文件不进版本库。
  - `frontend/vitest.config.ts` 独立于 `vite.config.ts`，同样把 `envDir` 设为仓库根目录。

## 4. 依赖

全部模块。

## 5. 内部流程

按[架构第 11 节](../架构与组装.md)的批次 A–E 依次接入真实实现。每批先运行各模块的契约测试，再运行本批的联调用例；通过后才进入下一批。

## 6. 接入方式

本模块就是接入点。联调中发现的问题，按契约判定由提供方或使用方修改（架构第 8 节）。

## 7. 验收边界

- 开始开发的前置条件：contracts 完成。组装代码可以先用替代实现跑通。
- 本模块完成：批次 A–E 全部通过；C06 7.8、7.10 两个审批样例从浏览器到数据库端到端通过；依赖规则检查通过。
- 每批的结果分别记为"模拟验证"或"真实联调"，不能互相代替。
