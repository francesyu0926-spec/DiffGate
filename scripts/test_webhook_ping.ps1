# 本地验证 GitHub Webhook 端点（模拟 ping 事件）
param(
  [string]$ApiBase = "http://127.0.0.1:8000",
  [string]$EnvFile = ".env"
)

$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Get-DotEnvValue($name) {
  if (-not (Test-Path $EnvFile)) { return "" }
  foreach ($line in Get-Content $EnvFile) {
    if ($line -match "^\s*#") { continue }
    if ($line -match "^\s*$name\s*=\s*(.*)\s*$") {
      return $Matches[1].Trim().Trim('"').Trim("'")
    }
  }
  return ""
}

$secret = Get-DotEnvValue "WEBHOOK_SECRET_GITHUB"
$body = "{}"
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
$headers = @{
  "Content-Type" = "application/json"
  "X-GitHub-Event" = "ping"
}
if ($secret) {
  $hmac = New-Object System.Security.Cryptography.HMACSHA256
  $hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($secret)
  $hash = ($hmac.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join ""
  $headers["X-Hub-Signature-256"] = "sha256=$hash"
}

$url = "$ApiBase/api/v1/webhooks/github"
try {
  $resp = Invoke-RestMethod -Uri $url -Method Post -Body $bytes -Headers $headers
  Write-Host "Webhook ping OK: $($resp | ConvertTo-Json -Compress)" -ForegroundColor Green
  exit 0
} catch {
  Write-Host "Webhook ping failed: $($_.Exception.Message)" -ForegroundColor Red
  if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message }
  exit 1
}