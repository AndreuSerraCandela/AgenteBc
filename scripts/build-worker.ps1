# Build del instalador AgenteBc Worker (PyInstaller + Inno Setup).
# Requisitos: pip install -e ".[desktop,build,windows-auth]"

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Instalando dependencias de build..."
python -m pip install -e ".[desktop,build,windows-auth]" -q
$Version = python -c "from agentebc import __version__; print(__version__)"

Write-Host "Generando icono..."
python scripts/generate-icon.py

Write-Host "PyInstaller -> dist\AgenteBcWorker.exe"
python -m PyInstaller packaging/agentebc-worker.spec --noconfirm --clean

$isccCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$issPath = Join-Path $Root "packaging\agentebc-worker.iss"
if ($iscc) {
    Write-Host "Compilando instalador Worker con Inno Setup..."
    & $iscc $issPath
    $installer = "AgenteBcWorker-$Version-setup.exe"
    New-Item -ItemType Directory -Force -Path "packaging\releases" | Out-Null
    Copy-Item "packaging\Output\$installer" "packaging\releases\$installer" -Force
    $hash = (Get-FileHash "packaging\releases\$installer" -Algorithm SHA256).Hash.ToLower()
    Write-Host "SHA256: $hash"
} else {
    Write-Host "Inno Setup no encontrado. Instala Inno Setup 6 o compila packaging\agentebc-worker.iss manualmente."
}

Write-Host ""
Write-Host "Ejecutable: dist\AgenteBcWorker.exe"
Write-Host "Instalador: packaging\releases\AgenteBcWorker-$Version-setup.exe"
Write-Host "Publicar (no git):"
Write-Host "  python scripts/publish_release.py --product worker packaging/releases/AgenteBcWorker-$Version-setup.exe"
