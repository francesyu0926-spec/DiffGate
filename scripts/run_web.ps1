$root = Split-Path $PSScriptRoot
Set-Location "$root\web"
if (-not (Test-Path "node_modules")) {
  npm install
}
npm run dev