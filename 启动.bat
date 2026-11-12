@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 1) 项目自带的虚拟环境（由 安装环境.bat 生成）
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
  exit /b 0
)

rem 2) 系统 Python（3.9+ 且带 tkinter 即可，本项目零第三方依赖）
set "PYW="
set "PY="
where pythonw >nul 2>nul && set "PYW=pythonw"
where python  >nul 2>nul && set "PY=python"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)

if defined PY (
  %PY% -c "import tkinter" >nul 2>nul
  if not errorlevel 1 (
    if defined PYW (
      start "" %PYW% "%~dp0main.py"
    ) else (
      start "" %PY% "%~dp0main.py"
    )
    exit /b 0
  )
)

echo.
echo 未找到可用的 Python 3（需要 3.9+，且带 tkinter）。
echo 请双击运行 安装环境.bat，它会准备一个只属于本项目的 Python。
echo.
pause
exit /b 1
