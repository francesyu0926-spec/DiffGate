# 单进程本地后端：SQLite + 文件缓存 + Celery 同步执行（无需 Docker / Redis / MySQL / Worker）
$root = Split-Path $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = $root

if (-not (Test-Path ".env")) {
    Write-Host "请先运行 .\scripts\setup_local.ps1 或复制 .env.local.example 为 .env"
    exit 1
}

.\.venv\Scripts\uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8010