$root = Split-Path $PSScriptRoot
$env:PYTHONPATH = $root
Set-Location $root
& "$PSScriptRoot\kill_stale_api.ps1" -Quiet
# Windows 上 --reload 会 spawn 系统 Python 子进程，可能跑到旧代码；本地默认单进程无 reload
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000