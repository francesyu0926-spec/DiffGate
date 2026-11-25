# 一键：生成 Secret → 启动 ngrok → 写入公网 URL → 打印 GitHub/GitLab 配置说明
param(
  [int]$Port = 8000,
  [switch]$SkipNgrok,
  [switch]$InstallNgrok
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$envFile = Join-Path $root ".env"

function New-WebhookSecret {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', 'x').Replace('/', 'y').Substring(0, 32)
}

function Set-DotEnvValue {
  param([string]$Name, [string]$Value)
  if (-not (Test-Path $envFile)) {
    if (Test-Path ".env.local.example") {
      Copy-Item ".env.local.example" $envFile
    } else {
      Copy-Item ".env.example" $envFile
    }
  }
  $lines = Get-Content $envFile
  $found = $false
  $out = foreach ($line in $lines) {
    if ($line -match "^\s*$Name\s*=") {
      $found = $true
      "$Name=$Value"
    } else {
      $line
    }
  }
  if (-not $found) {
    $out += "$Name=$Value"
  }
  Set-Content -Path $envFile -Value $out -Encoding utf8
}

function Get-DotEnvValue($name) {
  if (-not (Test-Path $envFile)) { return "" }
  foreach ($line in Get-Content $envFile) {
    if ($line -match "^\s*#") { continue }
    if ($line -match "^\s*$name\s*=\s*(.*)\s*$") {
      return $Matches[1].Trim().Trim('"').Trim("'")
    }
  }
  return ""
}

function Test-ApiListening {
  param([int]$p)
  try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:$p/health" -TimeoutSec 3
    return $r.status -eq "ok"
  } catch {
    return $false
  }
}

function Get-NgrokCommand {
  $bundled = Join-Path $root "tools\ngrok\ngrok.exe"
  if (Test-Path $bundled) { return $bundled }
  $cmd = Get-Command ngrok -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $local = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\ngrok.exe"
  if (Test-Path $local) { return $local }
  $pf = "${env:ProgramFiles}\ngrok\ngrok.exe"
  if (Test-Path $pf) { return $pf }
  return $null
}

function Get-NgrokPublicUrl {
  try {
    $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 2
    $https = $tunnels.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1
    if ($https) { return $https.public_url.TrimEnd('/') }
    $any = $tunnels.tunnels | Select-Object -First 1
    if ($any) { return $any.public_url.TrimEnd('/') }
  } catch {
    return $null
  }
  return $null
}

Write-Host "`n=== DiffGate Webhook + ngrok ===" -ForegroundColor Cyan

if (-not (Test-ApiListening -p $Port)) {
  Write-Host "API 未在端口 $Port 监听。请先运行: .\scripts\run_api.ps1" -ForegroundColor Yellow
  exit 1
}

$ghSecret = Get-DotEnvValue "WEBHOOK_SECRET_GITHUB"
$glSecret = Get-DotEnvValue "WEBHOOK_SECRET_GITLAB"
if (-not $ghSecret) {
  $ghSecret = New-WebhookSecret
  Set-DotEnvValue "WEBHOOK_SECRET_GITHUB" $ghSecret
  Write-Host "已生成 WEBHOOK_SECRET_GITHUB（写入 .env）" -ForegroundColor Green
}
if (-not $glSecret) {
  $glSecret = New-WebhookSecret
  Set-DotEnvValue "WEBHOOK_SECRET_GITLAB" $glSecret
  Write-Host "已生成 WEBHOOK_SECRET_GITLAB（写入 .env）" -ForegroundColor Green
}

if (-not $SkipNgrok) {
  $ngrokExe = Get-NgrokCommand
  if (-not $ngrokExe -and $InstallNgrok) {
    Write-Host "正在通过 winget 安装 ngrok..." -ForegroundColor Cyan
    try {
      winget install --id ngrok.ngrok -e --accept-source-agreements --accept-package-agreements
    } catch {
      Write-Host "winget 不可用或安装失败，请手动安装 ngrok。" -ForegroundColor Yellow
    }
    $ngrokExe = Get-NgrokCommand
  }
  $ngrokToken = $env:NGROK_AUTHTOKEN
  if (-not $ngrokToken) { $ngrokToken = Get-DotEnvValue "NGROK_AUTHTOKEN" }
  if ($ngrokExe -and $ngrokToken) {
    & $ngrokExe config add-authtoken $ngrokToken 2>$null | Out-Null
    Write-Host "已配置 ngrok authtoken" -ForegroundColor Green
  }
  if (-not $ngrokExe) {
    Write-Host @"

未找到 ngrok。请先安装并登录：
  winget install ngrok.ngrok
  ngrok config add-authtoken <你的 token>   # 见 https://dashboard.ngrok.com/get-started/your-authtoken

然后重新运行: .\scripts\setup_webhook_ngrok.ps1
或仅配置 Secret 后手动: ngrok http $Port
"@ -ForegroundColor Yellow
    $SkipNgrok = $true
  } else {
    $existing = Get-NgrokPublicUrl
    if (-not $existing) {
      Write-Host "启动 ngrok http $Port ..." -ForegroundColor Cyan
      Start-Process -FilePath $ngrokExe -ArgumentList "http", "$Port" -WindowStyle Minimized
      $deadline = (Get-Date).AddSeconds(20)
      while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $existing = Get-NgrokPublicUrl
        if ($existing) { break }
      }
    }
    if ($existing) {
      Set-DotEnvValue "WEBHOOK_PUBLIC_BASE_URL" $existing
      Write-Host "公网地址: $existing" -ForegroundColor Green
    } else {
      Write-Host "ngrok 未返回公网 URL，请确认 authtoken 是否已配置。" -ForegroundColor Yellow
    }
  }
}

$publicBase = Get-DotEnvValue "WEBHOOK_PUBLIC_BASE_URL"
if ($publicBase) {
  $githubUrl = "$publicBase/api/v1/webhooks/github"
  $gitlabUrl = "$publicBase/api/v1/webhooks/gitlab"
} else {
  $githubUrl = "https://<你的-ngrok-域名>/api/v1/webhooks/github"
  $gitlabUrl = "https://<你的-ngrok-域名>/api/v1/webhooks/gitlab"
}

Write-Host "`n--- 复制到 Git 平台 ---" -ForegroundColor Cyan
Write-Host "GitHub  Payload URL : $githubUrl"
Write-Host "GitHub  Secret      : $ghSecret"
Write-Host "GitHub  事件         : Push, Pull requests"
Write-Host ""
Write-Host "GitLab  URL         : $gitlabUrl"
Write-Host "GitLab  Secret token: $glSecret"
Write-Host "GitLab  事件         : Push, Merge request events"
Write-Host ""
Write-Host "仓库管理中确保：启用分析 + Webhook 开；私有仓需配置 Token/SSH。" -ForegroundColor Gray

Write-Host "`n--- 本地自检（GitHub ping）---" -ForegroundColor Cyan
Write-Host "若刚改过 .env 的 Secret，请重启 API 后再测。" -ForegroundColor Gray
& "$root\scripts\test_webhook_ping.ps1" -ApiBase "http://127.0.0.1:$Port"

if ($publicBase -or -not $SkipNgrok) {
  Write-Host "`n改 .env 后请重启: .\scripts\run_api.ps1" -ForegroundColor Yellow
  Write-Host "推代码后到「变更影响分析」查看新任务。" -ForegroundColor Green
}