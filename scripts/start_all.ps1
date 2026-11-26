# 一键启动 DiffGate 本地全套：API + 前端 +（可选）Celery Worker + ngrok
# 用法:
#   .\scripts\start_all.ps1
#   .\scripts\start_all.ps1 -SkipNgrok
#   .\scripts\start_all.ps1 -WithWorker
#   .\scripts\start_all.ps1 -InstallNgrok

param(
  [int]$ApiPort = 8000,
  [switch]$SkipNgrok,
  [switch]$SkipWeb,
  [switch]$WithWorker,
  [switch]$InstallNgrok
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Get-DotEnvValue([string]$name) {
  $envFile = Join-Path $root ".env"
  if (-not (Test-Path $envFile)) { return "" }
  foreach ($line in Get-Content $envFile) {
    if ($line -match "^\s*#") { continue }
    if ($line -match "^\s*$name\s*=\s*(.*)\s*$") {
      return $Matches[1].Trim().Trim('"').Trim("'")
    }
  }
  return ""
}

function Test-ApiHealth {
  param([int]$Port)
  try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
    return $r.status -eq "ok"
  } catch {
    return $false
  }
}

function Wait-ApiHealth {
  param([int]$Port, [int]$Seconds = 45)
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-ApiHealth -Port $Port) { return $true }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Start-ServiceWindow {
  param(
    [string]$Title,
    [string]$WorkDir,
    [string]$Command
  )
  $cmd = @"
`$host.UI.RawUI.WindowTitle = '$Title'
Set-Location '$WorkDir'
$Command
"@
  Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-NoProfile", "-Command", $cmd)
}

Write-Host "`n=== DiffGate 一键启动 ===" -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $root ".venv\Scripts\python.exe"))) {
  Write-Host "未找到 .venv，请先运行: .\scripts\setup_local.ps1" -ForegroundColor Red
  exit 1
}

if (-not (Test-Path (Join-Path $root ".env"))) {
  Write-Host "未找到 .env，请先运行: .\scripts\setup_local.ps1" -ForegroundColor Red
  exit 1
}

& "$PSScriptRoot\kill_stale_api.ps1" -Quiet

Write-Host "启动 API（端口 $ApiPort）..." -ForegroundColor Green
$apiCmd = @"
`$env:PYTHONPATH = '$root'
& '$root\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 0.0.0.0 --port $ApiPort
"@
Start-ServiceWindow -Title "DiffGate API ($ApiPort)" -WorkDir $root -Command $apiCmd

if (-not (Wait-ApiHealth -Port $ApiPort)) {
  Write-Host "API 在 ${ApiPort} 未就绪，请查看 DiffGate API 窗口日志。" -ForegroundColor Red
  exit 1
}
Write-Host "API 就绪: http://127.0.0.1:$ApiPort/health" -ForegroundColor Green

if (-not $SkipWeb) {
  Write-Host "启动前端 Vite（5173）..." -ForegroundColor Green
  $webCmd = @"
if (-not (Test-Path node_modules)) { npm install }
npm run dev
"@
  Start-ServiceWindow -Title "DiffGate Web (5173)" -WorkDir (Join-Path $root "web") -Command $webCmd
}

$eager = (Get-DotEnvValue "CELERY_ALWAYS_EAGER").ToLower()
$needWorker = $WithWorker -or ($eager -in @("false", "0", "no"))
if ($needWorker) {
  Write-Host "启动 Celery Worker（CELERY_ALWAYS_EAGER=false）..." -ForegroundColor Green
  $workerCmd = @"
`$env:PYTHONPATH = '$root'
& '$root\.venv\Scripts\celery.exe' -A app.celery_app.celery worker --loglevel=info --pool=solo
"@
  if (-not (Test-Path (Join-Path $root ".venv\Scripts\celery.exe"))) {
    Write-Host "跳过 Worker：未安装 celery（极简模式通常不需要）" -ForegroundColor Yellow
  } else {
    Start-ServiceWindow -Title "DiffGate Worker" -WorkDir $root -Command $workerCmd
  }
}

if (-not $SkipNgrok) {
  Write-Host "配置 Webhook / 启动 ngrok..." -ForegroundColor Green
  & "$PSScriptRoot\setup_webhook_ngrok.ps1" -Port $ApiPort -InstallNgrok:$InstallNgrok
}

$public = Get-DotEnvValue "WEBHOOK_PUBLIC_BASE_URL"
Write-Host "`n--- 本机地址 ---" -ForegroundColor Cyan
Write-Host "  API:     http://127.0.0.1:$ApiPort"
Write-Host "  Docs:    http://127.0.0.1:$ApiPort/docs"
if (-not $SkipWeb) {
  Write-Host "  Web UI:  http://127.0.0.1:5173"
}
if ($public) {
  Write-Host "  Webhook: $public/api/v1/webhooks/github"
  Write-Host "           $public/api/v1/webhooks/gitlab"
}
Write-Host "`n各服务在独立 PowerShell 窗口中运行，关闭对应窗口即可停止该服务。" -ForegroundColor DarkGray
Write-Host "仅停止 API 端口: .\scripts\kill_stale_api.ps1`n" -ForegroundColor DarkGray