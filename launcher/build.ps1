# Builds dist\AeroArcana.exe (one file). Run from the launcher folder: powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& .\.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed --name AeroArcana --icon icon.ico `
  --add-data "ui;ui" --collect-submodules webview --collect-data certifi --hidden-import truststore main.py
