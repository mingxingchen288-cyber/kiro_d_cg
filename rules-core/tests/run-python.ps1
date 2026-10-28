# Python 包上的验证：backend/tests/rules_core（契约测试、样例集、性质测试），以及与浏览器结果的逐条比较。
# 用法：pwsh -NoProfile -File rules-core/tests/run-python.ps1 -Browser <browser-results.json> -Out <python-results.json>
param([string]$Browser = '', [string]$Out = '')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$wheel = Get-ChildItem (Join-Path $repo 'rules-core\dist\python') -Filter '*.whl' | Select-Object -First 1
Push-Location (Join-Path $repo 'backend')
try {
    & uv run --with $wheel.FullName pytest tests/rules_core -q -p no:cacheprovider
    $pytest = $LASTEXITCODE
    "PYTEST_EXIT=$pytest"
    $cross = 0
    if ($Browser) {
        & uv run --with $wheel.FullName python (Join-Path $repo 'rules-core\tests\cross_check.py') $Browser $Out
        $cross = $LASTEXITCODE
        "CROSS_CHECK_EXIT=$cross"
    }
}
finally { Pop-Location }
exit ([int]($pytest -ne 0 -or $cross -ne 0))
