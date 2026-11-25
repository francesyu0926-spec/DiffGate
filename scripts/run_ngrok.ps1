$root = Split-Path $PSScriptRoot -Parent
$ngrok = Join-Path $root "tools\ngrok\ngrok.exe"
if (-not (Test-Path $ngrok)) {
  Write-Host "未找到 tools\ngrok\ngrok.exe，请先运行 setup 或下载 ngrok。" -ForegroundColor Red
  exit 1
}
$port = if ($args[0]) { $args[0] } else { 8000 }  # 与 run_api.ps1 一致
Write-Host "隧道: ngrok http $port (Ctrl+C 结束)" -ForegroundColor Cyan
Set-Location $root
& $ngrok http $port