# scripts/bootstrap_windows.ps1
# Bootstrap this repo for VS Code on Windows:
# - Creates .venv
# - Installs requirements.txt
# - Installs Playwright Chromium (if playwright is installed)
#
# Run:
#   powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1

$ErrorActionPreference = "Stop"

$VENV = ".venv"
$REQ  = "requirements.txt"

Write-Host "=== test-to-cal-v77 bootstrap (Windows) ===" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Host "Python not found. Install Python 3.11+ and ensure 'python' is on PATH." -ForegroundColor Red
  exit 1
}

# Create venv
if (-not (Test-Path $VENV)) {
  Write-Host "Creating virtual environment: $VENV" -ForegroundColor Yellow
  python -m venv $VENV
}

# Activate venv
$activate = Join-Path $VENV "Scripts\Activate.ps1"
if (-not (Test-Path $activate)) {
  Write-Host "Could not find venv activation script: $activate" -ForegroundColor Red
  exit 1
}
. $activate

Write-Host "Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip

if (Test-Path $REQ) {
  Write-Host "Installing dependencies from $REQ..." -ForegroundColor Yellow
  pip install -r $REQ
} else {
  Write-Host "No requirements.txt found. Skipping dependency install." -ForegroundColor DarkYellow
}

# Playwright browser install (Chromium) if playwright is installed
python -c "import playwright" 2>$null
if ($LASTEXITCODE -eq 0) {
  Write-Host "Installing Playwright browser (Chromium)..." -ForegroundColor Yellow
  python -m playwright install chromium
} else {
  Write-Host "Playwright not installed (skipping browser install)." -ForegroundColor DarkYellow
}

Write-Host "Bootstrap complete." -ForegroundColor Green
