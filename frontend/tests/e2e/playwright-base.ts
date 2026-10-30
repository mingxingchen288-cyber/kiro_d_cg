/**
 * 端到端测试的 Playwright 配置，`playwright.config.ts`（回归）和 `playwright.dev.config.ts`（开发）共用。
 *
 * - build（回归）：先 `pnpm build`，后端 `create_app` 在 `/` 提供 `frontend/dist`（T-AS-7 的同源托管），页面和接口同源。
 *   运行：`pnpm test:e2e`（构建后跑全部用例）。
 * - dev（开发）：Vite 开发服务器（`--mode test`，`server.warmup` 预先转换页面组件），接口经 `/proxy-default` 代理到后端。
 *   运行：`pnpm test:e2e:dev`，只跑相关的加 `--grep <标题>` 或 `--only-changed`。
 * 两种方式都由 webServer 启动和停止服务（端口上已有服务时直接用它）。环境变量只经 webServer 的 `env` 给子进程，
 * 不写进终端：后端用独立的 Redis 命名空间，PLATFORM_ALLOWED_ORIGINS 只放这里的前端地址。
 * 端口默认后端 8090、开发服务器 9540；同时在别的 worktree 中跑时用 E2E_BACKEND_PORT、E2E_FRONTEND_PORT 改。
 *
 * 失败诊断：trace 只在失败时保留（`npx playwright show-trace <test-results 下的 trace.zip>`）；
 * 重跑失败的用 `--last-failed`，遇到第一个失败就停用 `-x`。
 */
import process from 'node:process';
import { type PlaywrightTestConfig, defineConfig } from '@playwright/test';
import type { E2EOptions } from './support';

export type E2EMode = 'build' | 'dev';
type WebServer = Exclude<NonNullable<PlaywrightTestConfig['webServer']>, unknown[]>;

const backendPort = process.env.E2E_BACKEND_PORT ?? '8090';
const devPort = process.env.E2E_FRONTEND_PORT ?? '9540';
const backendUrl = `http://127.0.0.1:${backendPort}`;
const devUrl = `http://127.0.0.1:${devPort}`;
/** 本机地址不走代理（本机装了系统代理）；只给 Playwright 自己的进程和 webServer 子进程 */
const noProxy = { NO_PROXY: '127.0.0.1,localhost', no_proxy: '127.0.0.1,localhost' };
Object.assign(process.env, noProxy);

/** rules-core 的 Python 包（wheel，不在 backend 的依赖里），assembly 的 rules-core 插件要用 */
const RULES_CORE_WHEEL = '../rules-core/dist/python/cost_rules_core-0.1.0-cp313-cp313-win_amd64.whl';

const backend: WebServer = {
  name: 'backend',
  command: `uv run --with ${RULES_CORE_WHEEL} uvicorn cost_platform.assembly.app:create_app --factory --host 127.0.0.1 --port ${backendPort}`,
  cwd: '../backend',
  url: `${backendUrl}/health`,
  env: {
    ...noProxy,
    PLATFORM_REDIS_NAMESPACE: process.env.E2E_REDIS_NAMESPACE ?? 'cost-platform-wt-e2e',
    PLATFORM_ALLOWED_ORIGINS: [
      backendUrl,
      `http://localhost:${backendPort}`,
      devUrl,
      `http://localhost:${devPort}`
    ].join(','),
    PYTHONIOENCODING: 'utf-8'
  },
  reuseExistingServer: true,
  timeout: 180_000
};

const vite: WebServer = {
  name: 'vite',
  command: `pnpm exec vite --mode test --host 127.0.0.1 --port ${devPort} --strictPort`,
  url: devUrl,
  env: { ...noProxy, VITE_SERVICE_BASE_URL: backendUrl },
  reuseExistingServer: true,
  timeout: 120_000
};

const SHARED_CONFIG = /@shared-config/;

/** 相对路径按配置文件（frontend 目录下）解析 */
export function e2eConfig(mode: E2EMode) {
  return defineConfig<E2EOptions>({
    testDir: 'tests/e2e',
    outputDir: `test-results/e2e-${mode}`,
    timeout: 90_000,
    expect: { timeout: 15_000 },
    workers: 4,
    fullyParallel: true,
    reporter: [['list']],
    use: {
      baseURL: mode === 'build' ? backendUrl : devUrl,
      apiPrefix: mode === 'build' ? '' : '/proxy-default',
      channel: 'chrome',
      headless: true,
      // 2026-10-30 试过 5000×1200：主表 43 列只渲染 26 列（columns.spec.ts），明细 18 列全部渲染；
      // 同一批用例 5000×1200 用 1.5 分钟、1600×900 用 1.3 分钟，所以仍用 1600×900，列不在视野内时 cell() 横向滚过去
      viewport: { width: 1600, height: 900 },
      actionTimeout: 15_000,
      navigationTimeout: 30_000,
      trace: 'retain-on-failure'
    },
    projects: [
      { name: 'setup', testMatch: /auth\.setup\.ts$/ },
      { name: 'e2e', testMatch: /\.spec\.ts$/, grepInvert: SHARED_CONFIG, dependencies: ['setup'] },
      // 改共用配置的用例（标签 @shared-config）：保存配置会发 config.changed，已打开的成本核算页重新读取页面视图，
      // 正打开的筛选框、编辑器会被关掉，所以等 e2e 项目跑完再跑；它们彼此之间用测试锁（同名锁不并发）
      { name: 'shared-config', testMatch: /\.spec\.ts$/, grep: SHARED_CONFIG, dependencies: ['e2e'] }
    ],
    webServer: mode === 'build' ? [backend] : [backend, vite]
  });
}
