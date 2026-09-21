# Build de AgenteBc Desktop para Windows.
# Requisitos: Python 3.11+, pip install -e ".[desktop,build]"

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Instalando dependencias de build..."
python -m pip install -e ".[desktop,build]"
$Version = python -c "from agentebc import __version__; print(__version__)"

Write-Host "Generando icono desde images/logo-app.png..."
python scripts/generate-icon.py

Write-Host "Generando ejecutable con PyInstaller..."
python -m PyInstaller packaging/agentebc-desktop.spec --noconfirm --clean

$isccCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    Write-Host "Compilando instalador con Inno Setup..."
    & $iscc "packaging\agentebc.iss"
    $installer = "AgenteBc-$Version-setup.exe"
    Copy-Item "packaging\Output\$installer" "packaging\releases\$installer" -Force
    $hash = (Get-FileHash "packaging\releases\$installer" -Algorithm SHA256).Hash.ToLower()
    Write-Host "SHA256: $hash"
} else {
    Write-Host "Inno Setup no encontrado. Instala Inno Setup 6 o abre packaging\agentebc.iss manualmente."
}

Write-Host ""
Write-Host "Ejecutable: dist\AgenteBc.exe"
Write-Host "Instalador: packaging\releases\AgenteBc-$Version-setup.exe"
Write-Host "Publica el instalador (sin git):"
Write-Host "  python scripts/publish_release.py packaging/releases/AgenteBc-$Version-setup.exe"
