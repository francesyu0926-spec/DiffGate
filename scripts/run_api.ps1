$root = Split-Path $PSScriptRoot
$env:PYTHONPATH = $root
Set-Location $root
.\.venv\Scripts\uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8000