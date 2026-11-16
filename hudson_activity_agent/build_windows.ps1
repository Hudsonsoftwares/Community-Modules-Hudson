# Builds dist\HudsonActivity.exe (single file, no console window).
# Usage (from this folder):  powershell -ExecutionPolicy Bypass -File build_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller

.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name HudsonActivity `
    --hidden-import pystray._win32 `
    run_agent.py

Write-Host "Built: $PSScriptRoot\dist\HudsonActivity.exe"
