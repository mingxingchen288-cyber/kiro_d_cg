# 在本机 Chrome 中经 createCalcWorkerClient 运行样例集（Playwright 用 frontend 已装的 @playwright/test，不下载浏览器）。
# 用法：pwsh -NoProfile -File rules-core/web/test/run-browser.ps1 -Out <browser-results.json>
param([string]$Out = '')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8
$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
$env:NODE_PATH = Join-Path $repo 'frontend\node_modules'
if ($Out) { $env:RC_BROWSER_OUT = $Out }
& pnpm --dir (Join-Path $repo 'frontend') exec playwright test -c (Join-Path $PSScriptRoot 'playwright.config.cjs')
exit $LASTEXITCODE
