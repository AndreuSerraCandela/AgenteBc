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
echo Cerrando Chrome si estaba abierto...
taskkill /IM chrome.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul
Pause
