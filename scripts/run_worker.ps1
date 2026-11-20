$root = Split-Path $PSScriptRoot
$env:PYTHONPATH = $root
Set-Location $root
celery -A app.celery_app.celery worker --loglevel=info --pool=solo