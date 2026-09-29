# Build del ejecutable AgenteBc Worker (PyInstaller, sin instalador Inno).
# Requisitos: pip install -e ".[desktop,build,windows-auth]"

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Instalando dependencias de build..."
python -m pip install -e ".[desktop,build,windows-auth]" -q

Write-Host "Generando icono..."
python scripts/generate-icon.py

Write-Host "PyInstaller -> dist\AgenteBcWorker.exe"
python -m PyInstaller packaging/agentebc-worker.spec --noconfirm --clean

Write-Host ""
Write-Host "Listo: dist\AgenteBcWorker.exe"
Write-Host "Primera ejecución crea %LOCALAPPDATA%\AgenteBC\.env desde .env.example"
Write-Host "Copia ahí tu configuración (OData 7048, WEB 8080, credenciales)."
Write-Host "Playwright: en el PC destino puede hacer falta:"
Write-Host "  playwright install chromium"
Write-Host "  (o usar AGENTEBC_BROWSER_CHANNEL=chrome con Chrome instalado)"
