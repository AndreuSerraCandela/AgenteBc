# Entorno de desarrollo para probar el worker (sin compilar exe).
# Uso: .\scripts\run-worker-dev.ps1
#      .\scripts\run-worker-dev.ps1 -NoWindow   # solo HTTP, puerto 8766

param(
    [switch]$NoWindow,
    [int]$Port = 8766
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Instalando agente-bc (worker, desktop, windows-auth)..."
python -m pip install -e '.[desktop,windows-auth,sql]' -q

Write-Host "Comprobando navegadores Playwright (solo chromium si falta)..."
python -m playwright install chromium 2>$null

$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
    $env:AGENTEBC_ENV_FILE = $EnvFile
    Write-Host "Usando .env del proyecto: $EnvFile"
} else {
    Write-Host "AVISO: No hay .env en la raíz. Crea uno desde .env.example"
}

if ($NoWindow) {
    python -m agentebc_worker.cli serve --host 127.0.0.1 --port $Port
} else {
    python -m agentebc_worker.desktop --port $Port
}
