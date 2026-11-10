# ==============================================================================
# Bracketman - Windows PowerShell Automated Setup Script
# Configures Python virtual environment, dependencies, and verifies localhost readiness.
# ==============================================================================

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Bracketman - Windows Localhost Deployment Setup        " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Locate Python executable (python or py launcher)
$PythonCmd = $null
if (Get-Command "python" -ErrorAction SilentlyContinue) {
    $PythonCmd = "python"
} elseif (Get-Command "py" -ErrorAction SilentlyContinue) {
    $PythonCmd = "py -3"
} else {
    Write-Host "❌ Python 3 not found in PATH." -ForegroundColor Red
    Write-Host "👉 Install Python 3.10+ from https://www.python.org/ or run:" -ForegroundColor Yellow
    Write-Host "   winget install Python.Python.3.12" -ForegroundColor Yellow
    Write-Host "   (Make sure 'Add Python to PATH' is checked during setup!)" -ForegroundColor Yellow
    Exit 1
}

$PyVer = & $PythonCmd.Split(" ")[0] ($PythonCmd.Split(" ")[1..($PythonCmd.Split(" ").Length-1)] + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"))
Write-Host "✔ Found Python $PyVer" -ForegroundColor Green

# 2. Create virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "📦 Creating virtual environment at .venv..." -ForegroundColor Cyan
    if ($PythonCmd -eq "python") {
        & python -m venv .venv
    } else {
        & py -3 -m venv .venv
    }
} else {
    Write-Host "✔ Existing .venv directory found." -ForegroundColor Green
}

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$VenvPip    = Join-Path $RepoRoot ".venv\Scripts\pip.exe"
$VenvPytest = Join-Path $RepoRoot ".venv\Scripts\pytest.exe"

# 3. Upgrade pip and install package
Write-Host "⬇ Installing Bracketman and dependencies..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip setuptools
& $VenvPip install -e ".[dev]"

# 4. Ensure runtime directories exist
New-Item -ItemType Directory -Force -Path "data\tournaments" | Out-Null
New-Item -ItemType Directory -Force -Path "output" | Out-Null
New-Item -ItemType Directory -Force -Path ".streamlit" | Out-Null

# 5. Check or generate example tournament
if (-not (Test-Path "data\example_tournament.xlsx")) {
    Write-Host "📝 Generating default synthetic tournament spreadsheet..." -ForegroundColor Cyan
    & $VenvPython scripts\generate_example_tournament.py
}

# 6. Run test suite
Write-Host "🧪 Running pytest suite to verify installation..." -ForegroundColor Cyan
& $VenvPytest -v

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "✔ Setup complete! Bracketman is ready to run on Windows." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start Bracketman:" -ForegroundColor Cyan
Write-Host "  Double-click 'run_bracketman.bat' in the project folder" -ForegroundColor Yellow
Write-Host "  OR run in PowerShell:" -ForegroundColor Yellow
Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host "  bracketman ui" -ForegroundColor Yellow
Write-Host ""
Write-Host "Browser will open automatically to: http://127.0.0.1:8503" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
