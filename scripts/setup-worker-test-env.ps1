# Prepara el entorno local para probar AgenteBc Worker (una vez o tras git pull).
# Uso: .\scripts\setup-worker-test-env.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "=== AgenteBc Worker - entorno de prueba ===" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python no está en PATH. Instala Python 3.11+."
}

Write-Host "[1/4] Instalando paquete y extras..."
python -m pip install -U pip -q
python -m pip install -e '.[desktop,windows-auth,sql,dev]' -q

Write-Host "[2/4] Navegador Playwright (chromium)..."
python -m playwright install chromium

$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) {
    $Example = Join-Path $Root ".env.example"
    if (Test-Path $Example) {
        Copy-Item $Example $EnvFile
        Write-Host "[3/4] Creado .env desde .env.example. Editalo antes de registrar en BC." -ForegroundColor Yellow
    } else {
        Write-Host "[3/4] AVISO: Falta .env" -ForegroundColor Yellow
    }
} else {
    Write-Host "[3/4] .env encontrado: $EnvFile"
}

$env:AGENTEBC_ENV_FILE = $EnvFile
Write-Host "[4/4] Validando configuración..."
python (Join-Path $Root "scripts\check_worker_env.py")
if ($LASTEXITCODE -ne 0) {
    Write-Host "Corrige .env y vuelve a ejecutar este script." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Listo. Para abrir el worker:" -ForegroundColor Green
Write-Host "  Doble clic: Probar-Worker.bat"
Write-Host "  O: .\scripts\run-worker-dev.ps1"
Write-Host "  Solo navegador: .\scripts\run-worker-dev.ps1 -NoWindow  -> http://127.0.0.1:8766"
