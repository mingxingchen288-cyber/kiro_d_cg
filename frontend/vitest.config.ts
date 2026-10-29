import { URL, fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// 单元和契约测试：只跑 tests/ 下的 *.test.ts，在 Node 中运行，不加载 vite.config.ts 的页面构建插件。
// 环境文件同样从仓库根目录读取（assembly 的 AS-09），vitest 的模式是 test，读 .env 和 .env.test。
export default defineConfig({
  envDir: fileURLToPath(new URL('..', import.meta.url)),
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node'
  }
});
