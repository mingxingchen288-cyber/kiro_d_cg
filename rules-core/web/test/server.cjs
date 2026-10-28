// 浏览器验证用的静态服务器：根目录为 rules-core/，带 COOP、COEP 响应头（模块说明第 5 节）。
// 只监听 127.0.0.1，没有身份验证，只用于本机测试。
const http = require('node:http')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..', '..')
const port = Number(process.env.RC_TEST_PORT || 4791)
const types = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.wasm': 'application/wasm',
}

http
  .createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1')
    if (url.pathname === '/health') {
      res.end('ok')
      return
    }
    const file = path.join(root, decodeURIComponent(url.pathname))
    if (!file.startsWith(root + path.sep)) {
      res.writeHead(403)
      res.end()
      return
    }
    fs.readFile(file, (err, data) => {
      if (err) {
        res.writeHead(404)
        res.end()
        return
      }
      res.writeHead(200, {
        'Content-Type': types[path.extname(file)] || 'application/octet-stream',
        'Cross-Origin-Opener-Policy': 'same-origin',
        'Cross-Origin-Embedder-Policy': 'require-corp',
        'Cache-Control': 'no-store',
      })
      res.end(data)
    })
  })
  .listen(port, '127.0.0.1', () => console.log(`rules-core 测试服务器 http://127.0.0.1:${port}/`))
