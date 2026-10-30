import process from 'node:process';
import { URL, fileURLToPath } from 'node:url';
import { defineConfig, loadEnv, searchForWorkspaceRoot } from 'vite';
import { setupVitePlugins } from './build/plugins';
import { createViteProxy, getBuildTime } from './build/config';

/**
 * rules-core 交付的计算 Worker 和 WASM（rules-core 模块说明第 6 节），由 src/service/calc.ts 引用。
 * 构建时 Vite 把 worker.js（连同 index.js）和 rules_core.wasm 带哈希打进 dist/assets；
 * 这个目录在前端工程之外，开发服务器要放行，否则 worker.js、index.js、rules_core.wasm 返回 403。
 */
const rulesCoreWeb = fileURLToPath(new URL('../rules-core/dist/web', import.meta.url));

/**
 * 前端只读仓库根目录的环境文件（assembly 的 AS-09）：`.env`（不进版本库，含 AG Grid 授权）和 `.env.test`、`.env.prod`。
 * `envDir` 和 `loadEnv()` 都指向这里；保留 Vite 默认的 `VITE_` 前缀，根目录 `.env` 中的 `PLATFORM_*` 不进浏览器和产物。
 */
const repoRoot = fileURLToPath(new URL('..', import.meta.url));

export default defineConfig(configEnv => {
  const viteEnv = loadEnv(configEnv.mode, repoRoot) as unknown as Env.ImportMeta;

  const buildTime = getBuildTime();

  const enableProxy = configEnv.command === 'serve' && !configEnv.isPreview;

  return {
    envDir: repoRoot,
    base: viteEnv.VITE_BASE_URL,
    resolve: {
      alias: {
        '~': fileURLToPath(new URL('./', import.meta.url)),
        '@': fileURLToPath(new URL('./src', import.meta.url))
      }
    },
    css: {
      preprocessorOptions: {
        scss: {
          api: 'modern-compiler',
          additionalData: `@use "@/styles/scss/global.scss" as *;`
        }
      }
    },
    plugins: setupVitePlugins(viteEnv, buildTime),
    define: {
      BUILD_TIME: JSON.stringify(buildTime)
    },
    server: {
      host: '0.0.0.0',
      port: 9527,
      open: true,
      proxy: createViteProxy(viteEnv, enableProxy),
      // rules-core 的 WASM 要求页面跨源隔离（AS-06）；生产环境由后端提供前端静态文件，加同样的头（T-AS-7，assembly/app.py 的 FrontendFiles）
      headers: {
        'Cross-Origin-Opener-Policy': 'same-origin',
        'Cross-Origin-Embedder-Policy': 'require-corp'
      },
      fs: {
        // 设置 allow 会替换默认值，所以保留默认放行的前端工程目录
        allow: [searchForWorkspaceRoot(process.cwd()), rulesCoreWeb]
      },
      // 启动后预先转换登录页入口和通用页面的路由组件（连同它们的导入），第一次打开时少等逐个文件转换。
      // 预热全部 .vue 反而慢（与第一次打开登录页抢转换，2026-10-30 实测登录从 10s 变成 31s）
      warmup: {
        clientFiles: ['./src/main.ts', './src/modules/page/renderers/PageRoute.vue']
      }
    },
    preview: {
      port: 9725
    },
    build: {
      reportCompressedSize: false,
      sourcemap: viteEnv.VITE_SOURCE_MAP === 'Y',
      commonjsOptions: {
        ignoreTryCatch: false
      }
    }
  };
});
