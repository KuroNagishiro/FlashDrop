@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 1) 项目自带的虚拟环境（由 安装环境.bat 生成）
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
  exit /b 0
)

rem 2) 系统 Python：PATH 里可能有好几个，逐个验证 tkinter
for /f "delims=" %%i in ('where python 2^>nul') do (
  "%%i" -c "import tkinter" >nul 2>nul
  if not errorlevel 1 (
    set "PY=%%i"
    goto use_py
  )
)

rem 3) py 启动器
py -3 -c "import tkinter" >nul 2>nul
if not errorlevel 1 (
  start "" pyw -3 "%~dp0main.py"
  exit /b 0
)

echo.
echo 未找到可用的 Python 3（需要 3.9+，且带 tkinter）。
echo 请双击运行 安装环境.bat，它会准备一个只属于本项目的 Python。
echo.
pause
exit /b 1

:use_py
set "PYW=%PY:python.exe=pythonw.exe%"
if exist "%PYW%" (
  start "" "%PYW%" "%~dp0main.py"
) else (
  start "" "%PY%" "%~dp0main.py"
)
exit /b 0
