# Sample Data Generator v4 (superset) - Windows PowerShell launcher.
#   Right-click > Run with PowerShell, or:  powershell -ExecutionPolicy Bypass -File run.ps1
param([int]$Port = 8504)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "==> Sample Data Generator v4 (superset)"

$py = $null
foreach ($c in @("py", "python")) {
  if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break }
}
if (-not $py) {
  Write-Host "ERROR: Python 3 not found. Install from https://www.python.org/downloads/"
  Read-Host "Press Enter to exit"; exit 1
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "==> Creating virtual environment (.venv)..."
  if ($py -eq "py") { & py -3 -m venv .venv } else { & $py -m venv .venv }
}
$venvPy = ".\.venv\Scripts\python.exe"

Write-Host "==> Installing dependencies..."
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r requirements.txt

$cfgDir = Join-Path $env:USERPROFILE ".streamlit"
$cfg = Join-Path $cfgDir "credentials.toml"
if (-not (Test-Path $cfg)) {
  New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
  "[general]`r`nemail = `"`"" | Set-Content -Path $cfg -Encoding ascii
}

Write-Host "==> Starting at http://localhost:$Port  (press Ctrl+C to stop)"
& $venvPy -m streamlit run app.py --server.port $Port
