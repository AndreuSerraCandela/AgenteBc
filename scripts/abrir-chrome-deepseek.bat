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

echo.
echo Abriendo Chrome para DeepSeek (puerto 9222)...
echo Si Chrome con CDP ya estaba abierto, puedes usar esa ventana.
echo Perfil: %PROFILE%
echo.
echo 1. Inicia sesion en https://chat.deepseek.com
echo 2. Deja esta ventana de Chrome abierta
echo 3. Lanza el diagnostico en AgenteBc
echo.

start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%PROFILE%" https://chat.deepseek.com

endlocal
