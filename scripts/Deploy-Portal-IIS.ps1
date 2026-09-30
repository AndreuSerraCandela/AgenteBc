# Despliegue urgente del portal AgenteBc en IIS (agentebc.malla.es).
# Ejecutar EN EL SERVIDOR como administrador, desde la carpeta del sitio o del repo.
#
# Ejemplo:
#   cd C:\inetpub\wwwroot\AgenteBc
#   git pull
#   powershell -ExecutionPolicy Bypass -File scripts\Deploy-Portal-IIS.ps1

$ErrorActionPreference = "Stop"

$SiteRoot = $PSScriptRoot | Split-Path -Parent
if (-not (Test-Path (Join-Path $SiteRoot "wsgi.py"))) {
    $SiteRoot = "C:\inetpub\wwwroot\AgenteBc"
}
if (-not (Test-Path (Join-Path $SiteRoot "wsgi.py"))) {
    throw "No se encuentra wsgi.py. Indique la carpeta del sitio IIS."
}

Set-Location $SiteRoot
Write-Host "Sitio IIS: $SiteRoot"

$skillsDir = Join-Path $SiteRoot "data\skills-share"
$releasesDir = Join-Path $SiteRoot "data\releases"
$actionsDir = Join-Path $SiteRoot "data\actions"

foreach ($dir in @($skillsDir, $releasesDir, $actionsDir, (Join-Path $SiteRoot "logs"))) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Write-Host "Creado: $dir"
    }
}

$appPool = "AgenteBc"
$pools = @(
    "IIS AppPool\$appPool",
    "IIS_IUSRS",
    "NT AUTHORITY\IIS_IUSRS"
)
foreach ($dir in @($skillsDir, $actionsDir, $releasesDir)) {
    foreach ($identity in $pools) {
        icacls $dir /grant "${identity}:(OI)(CI)M" 2>$null | Out-Null
    }
    Write-Host "Permisos escritura: $dir"
}

$webConfig = Join-Path $SiteRoot "web.config"
if (Test-Path $webConfig) {
    $xml = [xml](Get-Content $webConfig -Raw)
    $ns = @{ hp = "http://schemas.microsoft.com/IIS/Settings" }
    $envVars = $xml.configuration.'system.webServer'.httpPlatform.environmentVariables.environmentVariable
    $names = @($envVars | ForEach-Object { $_.name })
    if ("AGENTEBC_WORKER_SKILLS_SHARE_DIR" -notin $names) {
        Write-Warning "web.config sin AGENTEBC_WORKER_SKILLS_SHARE_DIR. Copie web.config del repo y recicle el app pool."
    }
} else {
    Write-Warning "Falta web.config en $SiteRoot"
}

if (Get-Command git -ErrorAction SilentlyContinue) {
    git -C $SiteRoot pull 2>$null
}

Import-Module WebAdministration -ErrorAction SilentlyContinue
if (Get-Module WebAdministration) {
    Restart-WebAppPool -Name $appPool -ErrorAction SilentlyContinue
    Write-Host "App pool reciclado: $appPool"
} else {
    Write-Host "Recicle manualmente el app pool $appPool en IIS."
}

Write-Host ""
Write-Host "Comprobar: POST /api/skills/share (token) y carpeta $skillsDir"
