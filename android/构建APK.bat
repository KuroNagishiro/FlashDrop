@echo off
setlocal
cd /d "%~dp0"
set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0build.py"
echo.
if errorlevel 1 (echo BUILD FAILED) else (echo APK: %~dp0..\FlashDrop.apk)
pause
