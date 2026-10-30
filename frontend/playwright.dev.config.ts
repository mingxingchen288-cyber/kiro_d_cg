/**
 * 端到端测试（frontend/tests/e2e/）的开发方式：Vite 开发服务器 + 后端，见 tests/e2e/playwright-base.ts。
 * 运行：`pnpm test:e2e:dev`；只跑相关的：`pnpm test:e2e:dev --grep <标题>`、`--only-changed`；重跑失败的：`--last-failed`。
 */
import { e2eConfig } from './tests/e2e/playwright-base';

export default e2eConfig('dev');
