import { defineConfig } from 'vitest/config';

// 单元和契约测试：只跑 tests/ 下的 *.test.ts，在 Node 中运行，不加载 vite.config.ts 的页面构建插件。
export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node'
  }
});
