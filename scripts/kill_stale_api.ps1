# 清理 Windows 上 uvicorn --reload 留下的孤儿 worker（仍占用 8000/8010）
param(
  [int[]]$Ports = @(8000, 8010),
  [switch]$Quiet
)

function Log([string]$msg, [string]$color = "Gray") {
  if (-not $Quiet) { Write-Host $msg -ForegroundColor $color }
}

$killed = 0

foreach ($port in $Ports) {
  for ($round = 0; $round -lt 3; $round++) {
    $pids = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique |
      Where-Object { $_ -gt 0 })
    if (-not $pids.Count) { break }
    foreach ($procId in $pids) {
      try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Log "已结束监听 ${port} 的进程 PID=$procId" "Yellow"
        $killed++
      } catch {
        taskkill /PID $procId /F 2>$null | Out-Null
        if (-not $?) {
          Log "端口 $port PID=$procId 已不存在（netstat 可能滞后）" "DarkGray"
        }
      }
    }
    Start-Sleep -Milliseconds 400
  }
}

Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object {
  $cmd = $_.CommandLine
  if (-not $cmd) { return }
  $diffGate = $cmd -match 'DiffGate'
  $uvicorn = $cmd -match 'uvicorn'
  $reloadChild = $cmd -match 'spawn_main|multiprocessing-fork'
  if ($diffGate -and ($uvicorn -or $reloadChild)) {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    if ($?) {
      Log "已结束 DiffGate API 相关进程 PID=$($_.ProcessId)" "Yellow"
      $killed++
    }
  }
}

if (-not $Quiet) {
  if ($killed -gt 0) { Log "清理完成，共 $killed 项。" "Green" }
  else { Log "未发现需清理的 DiffGate API 进程。" "Green" }
}