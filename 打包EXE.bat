@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================================
echo   打包 FlashDrop 桌面端为单文件 exe
echo   Python 与 PyInstaller 只装在 tools\packenv，不装全局
echo ============================================================
echo.
"%PY%" "%~dp0tools\build_exe.py"
echo.
if errorlevel 1 (
  echo 打包失败，请看上面的错误信息。
) else (
  echo 完成：%~dp0FlashDrop.exe
  echo 双击即可运行，无需 .venv。
)
pause
