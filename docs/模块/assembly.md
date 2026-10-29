# assembly

状态：已确认。上级：[架构与组装](../架构与组装.md)。

## 1. 职责

- 负责：后端组装根和命令行入口；HTTP 中间件；注册管道阶段；启动初始化和后台任务；前端的 `main.ts` 和构建配置；依赖规则检查；系统时钟和编号生成；按批次联调；端到端测试。
- 不负责：任何业务规则，它们都在各业务模块中。

## 2. 所有权

| 类别 | 内容 |
|---|---|
| 代码 | `backend/src/cost_platform/assembly/`、`frontend/src/main.ts`、`frontend/src/assembly/` |
| 配置 | `backend/pyproject.toml`、`.importlinter`、前端的 `vite.config.ts`、`vitest.config.ts`、`package.json`、dependency-cruiser 配置；根目录的 `.env.example`、`.env.test`、`.env.prod` |
| 测试 | `backend/tests/e2e/`、`frontend/tests/e2e/` |

## 3. 对外契约

按[架构第 6 节](../架构与组装.md)组装，挂载 `POST /api/commands`、`GET /health`。

- AS-01：`PLATFORM_BACKEND=memory` 时全部使用 contracts 的替代实现；`oracle` 时使用真实实现。
- AS-02：请求中间件：调用 `Authenticator`（请求带 `X-Background-Request: 1` 时传 `touch=False`）→ 调用 `ConfigSnapshotReader` → 生成执行上下文（[C04](../契约/C04-执行上下文.md)）→ 交给路由。写请求的 Origin 不在 `PLATFORM_ALLOWED_ORIGINS` 中时返回 403 ORIGIN_REJECTED；错误按 [C03](../契约/C03-错误.md) 输出；每个响应带 `X-Config-Version`。
- AS-03：按架构第 7 节的顺序注册管道阶段。
- AS-04：启动顺序：config 的 CF-10 → identity 的 ID-06 → config 的 CF-13 预热 → 启动投递重试、配置恢复和 Redis 订阅三个后台任务。预热完成前，`/health` 返回 503 `{"status": "starting"}`，业务请求返回 503 CONFIG_UNAVAILABLE；完成后 `/health` 返回 200。
- AS-05：命令行 `platform` 只有 `db` 和 `migrate` 两类子命令。
- AS-06：前端 `main.ts` 创建 HTTP 客户端、实时客户端（断线自动重连），并用 rules-core 交付的 `createCalcWorkerClient` 创建计算客户端，加载外壳，再注册各前端模块。前端服务的响应带 COOP 和 COEP 头，供 rules-core 的 WASM 使用。
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
