// 样例集在浏览器（Chrome）中经 createCalcWorkerClient 运行（C07 第 6 节，T-RC-1、T-RC-2）。
// 结果写到 RC_BROWSER_OUT（默认 .reports/T-RC-2/browser-results.json），由 rules-core/tests/cross_check.py 与 Python 包逐条比较。
const fs = require('node:fs')
const path = require('node:path')
const { test, expect } = require('@playwright/test')

const rc = path.resolve(__dirname, '..', '..')
const out = process.env.RC_BROWSER_OUT || path.resolve(rc, '..', '.reports', 'T-RC-2', 'browser-results.json')
const casesDir = path.join(rc, 'fixtures', 'cases')
const cases = fs
  .readdirSync(casesDir)
  .filter((f) => f.endsWith('.json'))
  .sort()
  .map((f) => {
    const c = JSON.parse(fs.readFileSync(path.join(casesDir, f), 'utf8'))
    if (c.pack) c.packText = fs.readFileSync(path.join(rc, 'fixtures', c.pack), 'utf8')
    return c
  })

test.describe.configure({ mode: 'serial' })

let run = null

test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('/web/test/page.html')
  run = await page.evaluate(async (cases) => {
    const core = await import('/dist/web/index.js')
    const { createCalcWorkerClient } = await import('/dist/web/client.js')
    const t0 = performance.now()
    await core.init('/dist/web/rules_core.wasm')
    const initMs = performance.now() - t0
    const client = createCalcWorkerClient('/dist/web/rules_core.wasm')
    const enc = new TextEncoder()
    const meta = (c) => JSON.parse(c.packText)
    const results = []
    for (const c of cases) {
      const r = { name: c.name, kind: c.kind, problems: [] }
      if (c.kind === 'evaluate') {
        const m = meta(c)
        const handle = await client.load({ packId: m.packId, version: m.version, bytes: enc.encode(c.packText) })
        const request = JSON.stringify(c.request)
        const s = performance.now()
        r.result = await client.evaluate(handle, request)
        r.ms = performance.now() - s
        if (c.match === 'errorCode') {
          const got = JSON.parse(r.result)
          if (!(got.ok === false && got.error.code === c.expected.error.code)) r.problems.push(`期望 ${c.expected.error.code}，实际 ${r.result}`)
        } else {
          r.problems = core.compareJson(r.result, JSON.stringify(c.expected))
        }
      } else if (c.kind === 'packInvalid') {
        try {
          await client.load({ packId: 'CYC', version: Date.now(), bytes: enc.encode(c.packText) })
          r.problems.push('期望 PACK_INVALID，实际加载成功')
        } catch (e) {
          r.error = { code: e.code, message: e.message }
          if (e.code !== c.expected.code) r.problems.push(`错误码为 ${e.code}`)
          for (const w of c.expected.messageContains) if (!e.message.includes(w)) r.problems.push(`消息「${e.message}」不含 ${w}`)
        }
      } else if (c.kind === 'consistency') {
        r.verdicts = c.cases.map((x) => core.compareJson(JSON.stringify(x.a), JSON.stringify(x.b)).length === 0)
        c.cases.forEach((x, i) => { if (r.verdicts[i] !== x.consistent) r.problems.push(`${x.a} 与 ${x.b}：判定为 ${r.verdicts[i]}`) })
      }
      results.push(r)
    }
    // 求值耗时：成本核算单据 200726（11 条明细、17 条计算规则），同一句柄重复求值
    const cost = cases.find((c) => c.name === '成本核算-单据200726')
    const m = meta(cost)
    const handle = await client.load({ packId: m.packId, version: m.version, bytes: enc.encode(cost.packText) })
    const request = JSON.stringify(cost.request)
    const repeat = 200
    let s = performance.now()
    for (let i = 0; i < repeat; i++) await client.evaluate(handle, request)
    const workerAvgMs = (performance.now() - s) / repeat
    const direct = core.loadPack(enc.encode(cost.packText))
    s = performance.now()
    for (let i = 0; i < repeat; i++) core.evaluate(direct, request)
    const directAvgMs = (performance.now() - s) / repeat
    client.terminate()
    return {
      coreVersion: core.coreVersion(),
      userAgent: navigator.userAgent,
      crossOriginIsolated: self.crossOriginIsolated,
      timing: { initMs, repeat, workerAvgMs, directAvgMs, fixture: cost.name },
      results,
    }
  }, cases)
  run.pageErrors = errors
  fs.mkdirSync(path.dirname(out), { recursive: true })
  fs.writeFileSync(out, JSON.stringify(run, null, 2))
  await page.close()
})

test('页面跨源隔离（COOP、COEP）且没有页面错误', () => {
  expect(run.crossOriginIsolated).toBe(true)
  expect(run.pageErrors).toEqual([])
})

for (const c of cases) {
  test(`样例 ${c.name}`, () => {
    const r = run.results.find((x) => x.name === c.name)
    expect(r.problems).toEqual([])
  })
}
