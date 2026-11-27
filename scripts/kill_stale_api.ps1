# Kill stale uvicorn workers still listening on API ports (Windows).
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
        Log "Stopped PID=$procId listening on port $port" "Yellow"
        $killed++
      } catch {
        taskkill /PID $procId /F 2>$null | Out-Null
        if (-not $?) {
          Log "Port $port PID=$procId already gone (stale netstat)" "DarkGray"
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
      Log "Stopped DiffGate API process PID=$($_.ProcessId)" "Yellow"
      $killed++
    }
  }
}

if (-not $Quiet) {
  if ($killed -gt 0) { Log "Done. Stopped $killed process(es)." "Green" }
  else { Log "No stale DiffGate API process found." "Green" }
}