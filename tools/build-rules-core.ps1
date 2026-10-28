<#
.SYNOPSIS
  构建 rules-core 的两个产物：Python 包（maturin）和 wasm32-wasip1（RC-07，模块说明第 5 节）。

.DESCRIPTION
  两个产物都用 rules-core/Cargo.lock（--locked，不允许改动锁文件）。
  - Python 包：rules-core/dist/python/cost_rules_core-*.whl
  - WASM 与前端脚本：rules-core/dist/web/（rules_core.wasm、index.js、worker.js、client.js、*.d.ts）
  WASM 依赖的 QuickJS 是 C 代码，需要 wasi-sdk（默认 %USERPROFILE%\.local\wasi-sdk\wasi-sdk-34.0）。
  构建时间、产物大小写到 -MetricsOut 指定的 JSON 文件。

.EXAMPLE
  pwsh -NoProfile -File tools/build-rules-core.ps1
  pwsh -NoProfile -File tools/build-rules-core.ps1 -Target wasm
#>
param(
    [ValidateSet('all', 'python', 'wasm')]
    [string]$Target = 'all',
    [string]$WasiSdk = (Join-Path $env:USERPROFILE '.local\wasi-sdk\wasi-sdk-34.0'),
    [string]$Python = 'E:\devtoolandvpn\Python313\python.exe',
    [string]$MetricsOut = ''
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$rc = Join-Path $repo 'rules-core'
$dist = Join-Path $rc 'dist'
$lock = Join-Path $rc 'Cargo.lock'
$metrics = [ordered]@{ cargoLockSha256Before = (Get-FileHash -Algorithm SHA256 $lock).Hash.ToLower() }

function Invoke-Step([string]$name, [scriptblock]$body) {
    Write-Host "== $name"
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $body
    if ($LASTEXITCODE -ne 0) { throw "$name 失败，退出码 $LASTEXITCODE" }
    $sw.Stop()
    $metrics["${name}Seconds"] = [math]::Round($sw.Elapsed.TotalSeconds, 1)
}

if ($Target -in 'all', 'python') {
    $out = Join-Path $dist 'python'
    if (Test-Path $out) { Remove-Item -Recurse -Force $out }
    Invoke-Step 'python' {
        & uvx --from 'maturin==1.15.0' maturin build --release --locked `
            -m (Join-Path $rc 'bindings\python\Cargo.toml') -i $Python --out $out
    }
    $wheel = Get-ChildItem $out -Filter '*.whl' | Select-Object -First 1
    $metrics.pythonWheel = $wheel.FullName
    $metrics.pythonWheelBytes = $wheel.Length
}

if ($Target -in 'all', 'wasm') {
    $env:WASI_SDK = $WasiSdk
    $env:LIBCLANG_PATH = Join-Path $WasiSdk 'bin'
    $resource = Get-ChildItem (Join-Path $WasiSdk 'lib\clang') -Directory | Select-Object -First 1
    # libclang.dll 找不到自己的头文件目录（stddef.h），显式给出；bindgen 按 shell 规则拆分参数，路径用正斜杠
    $env:BINDGEN_EXTRA_CLANG_ARGS_wasm32_wasip1 = "-isystem $((Join-Path $resource.FullName 'include').Replace('\', '/'))"
    Invoke-Step 'wasm' {
        Push-Location $rc
        try { & cargo build --release --locked -p cost-rules-core-wasm --target wasm32-wasip1 }
        finally { Pop-Location }
    }
    $web = Join-Path $dist 'web'
    New-Item -ItemType Directory -Force -Path $web | Out-Null
    Copy-Item (Join-Path $rc 'target\wasm32-wasip1\release\rules_core_wasm.wasm') (Join-Path $web 'rules_core.wasm') -Force
    Copy-Item (Join-Path $rc 'web\src\*') $web -Force
    $wasm = Get-Item (Join-Path $web 'rules_core.wasm')
    $metrics.wasm = $wasm.FullName
    $metrics.wasmBytes = $wasm.Length
}

$metrics.cargoLockSha256After = (Get-FileHash -Algorithm SHA256 $lock).Hash.ToLower()
if ($metrics.cargoLockSha256After -ne $metrics.cargoLockSha256Before) { throw 'Cargo.lock 在构建中被改动' }
$json = $metrics | ConvertTo-Json
$json
if ($MetricsOut) { $json | Set-Content -Encoding utf8 $MetricsOut }
