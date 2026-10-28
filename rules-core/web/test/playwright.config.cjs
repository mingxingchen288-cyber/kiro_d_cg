// rules-core 浏览器验证：本机 Chrome（channel: 'chrome'），不下载浏览器。
// 运行：$env:NODE_PATH='D:\chonggou\kiro_d_cg\frontend\node_modules'; pnpm --dir D:\chonggou\kiro_d_cg\frontend exec playwright test -c D:\chonggou\kiro_d_cg\rules-core\web\test\playwright.config.cjs
const path = require('node:path')

const port = Number(process.env.RC_TEST_PORT || 4791)

module.exports = {
  testDir: __dirname,
  testMatch: '*.spec.cjs',
  outputDir: path.resolve(__dirname, '..', 'test-results'),
  timeout: 120000,
  workers: 1,
  reporter: [['list']],
  use: { channel: 'chrome', headless: true, baseURL: `http://127.0.0.1:${port}` },
  webServer: {
    command: `node "${path.join(__dirname, 'server.cjs')}"`,
    url: `http://127.0.0.1:${port}/health`,
    reuseExistingServer: false,
    timeout: 30000,
  },
}
