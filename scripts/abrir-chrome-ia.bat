@echo off
setlocal

set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
)

if not exist "%CHROME%" (
  echo No se encontro Google Chrome.
  pause
  exit /b 1
)

set "PROFILE=%LocalAppData%\AgenteBC-Chrome"
set "START_URL=https://www.google.com/ai"

if /I "%~1"=="deepseek" set "START_URL=https://chat.deepseek.com"
if /I "%~1"=="google" set "START_URL=https://www.google.com/ai"

echo.
echo Abriendo Chrome con depuracion remota (puerto 9222)...
echo Perfil: %PROFILE%
echo URL inicial: %START_URL%
echo.
echo 1. Inicia sesion manualmente si hace falta
echo 2. Deja esta ventana de Chrome abierta
echo 3. Lanza el diagnostico en AgenteBc
echo.

start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%PROFILE%" %START_URL%

endlocal
