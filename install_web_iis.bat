@echo off
title Instalar AgenteBc portal para IIS
color 0E

REM IMPORTANTE: IIS usa C:\Python\python.exe (ver web.config processPath).
REM Ejecuta este script en el servidor, en la carpeta del sitio AgenteBc.

set PY_IIS=C:\Python\python.exe

echo ========================================
echo    Instalacion IIS - AgenteBc (portal)
echo    Python: %PY_IIS%
echo ========================================
echo.

if not exist "%PY_IIS%" (
    echo ERROR: No existe %PY_IIS%
    echo Edita PY_IIS en este .bat para que coincida con processPath en web.config
    pause
    exit /b 1
)

if not exist "logs" mkdir logs
if not exist "releases" mkdir releases

echo Instalando dependencias web...
"%PY_IIS%" -m pip install -r requirements_web.txt
if %errorlevel% neq 0 (
    echo ERROR: Fallo la instalacion de requirements_web.txt
    pause
    exit /b 1
)

echo Instalando paquete agente-bc (sin Playwright ni desktop)...
"%PY_IIS%" -m pip install -e . --no-deps
if %errorlevel% neq 0 (
    echo ERROR: Fallo pip install -e .
    pause
    exit /b 1
)

echo.
echo Comprobando modulos...
"%PY_IIS%" -c "import flask, waitress; from agentebc.portal import create_portal_app; create_portal_app(); print('OK - portal listo')"
if %errorlevel% neq 0 (
    echo ERROR: Faltan modulos o no se puede importar el portal
    pause
    exit /b 1
)

echo.
echo Copia a releases\ estos ficheros si aun no estan:
echo   - latest.json
echo   - AgenteBc-x.y.z-setup.exe
echo.
echo Listo. Reinicia el sitio AgenteBc en IIS.
pause
