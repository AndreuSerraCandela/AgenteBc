@echo off
cd /d "%~dp0"
echo Abriendo worker en http://127.0.0.1:8766
start "" "http://127.0.0.1:8766"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-worker-dev.ps1" -NoWindow
pause
