import process from 'node:process';
import { defineConfig } from '@playwright/test';

/**
 * 端到端测试（assembly 的 frontend/tests/e2e/）。使用本机安装的 Chrome，不下载浏览器。
 * 后端和前端开发服务器已在运行时直接使用；没有运行时由 webServer 启动。
 * 默认后端 8080、前端 9527；用环境变量 E2E_BACKEND_PORT、E2E_FRONTEND_PORT 改端口（例如在另一个 git worktree 中运行），
 * 改了后端端口时，前端开发服务器的代理也指向它。
 */
const backendPort = process.env.E2E_BACKEND_PORT ?? '8080';
const frontendPort = process.env.E2E_FRONTEND_PORT ?? '9527';

export default defineConfig({
  testDir: 'tests/e2e',
  testMatch: '**/*.spec.ts',
  timeout: 120_000,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${frontendPort}`,
    channel: 'chrome',
    headless: true,
    viewport: { width: 1600, height: 900 }
  },
  webServer: [
    {
      // assembly 的 rules-core 插件要用 rules-core 的 Python 包（wheel，不在 backend 的依赖里）
      command:
        'uv run --with ../rules-core/dist/python/cost_rules_core-0.1.0-cp313-cp313-win_amd64.whl ' +
        `uvicorn cost_platform.assembly.app:create_app --factory --host 127.0.0.1 --port ${backendPort}`,
      cwd: '../backend',
      url: `http://127.0.0.1:${backendPort}/health`,
      reuseExistingServer: true,
      timeout: 120_000
    },
    {
      command: `pnpm exec vite --mode test --port ${frontendPort} --open false`,
      url: `http://localhost:${frontendPort}`,
      env: process.env.E2E_BACKEND_PORT ? { VITE_SERVICE_BASE_URL: `http://localhost:${backendPort}` } : undefined,
      reuseExistingServer: true,
      timeout: 120_000
    }
  ]
});
