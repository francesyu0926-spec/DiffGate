$root = Split-Path $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = $root

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

$env:PIP_REQUIRE_HASHES = "0"
.\.venv\Scripts\pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.local.example" ".env"
    Write-Host "已生成 .env（本地无 Docker 配置）" -ForegroundColor Green
}

New-Item -ItemType Directory -Force -Path "$root\data" | Out-Null
Write-Host "依赖已安装。运行: .\scripts\run_local.ps1" -ForegroundColor Cyan