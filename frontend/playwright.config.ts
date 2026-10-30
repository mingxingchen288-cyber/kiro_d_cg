/**
 * 端到端测试（frontend/tests/e2e/）的回归方式：后端托管构建产物（T-AS-7），见 tests/e2e/playwright-base.ts。
 * 运行：`pnpm test:e2e`（先 `pnpm build:test`，测试模式构建）；开发时用 `pnpm test:e2e:dev`（playwright.dev.config.ts）。
 */
import { e2eConfig } from './tests/e2e/playwright-base';

export default e2eConfig('build');
