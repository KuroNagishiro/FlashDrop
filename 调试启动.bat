@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0main.py"
  goto done
)

where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0main.py"
  goto done
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0main.py"
  goto done
)

echo 未找到可用的 Python 3，请先运行 安装环境.bat。

:done
echo.
echo FlashDrop 已退出（代码 %errorlevel%）。
pause
