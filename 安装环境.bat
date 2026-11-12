@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 所有东西都装在本项目目录内：不改系统 PATH、不装全局包、不写注册表
set "UV_CACHE_DIR=%~dp0tools\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%~dp0tools\python"
set "UV_PROJECT_ENVIRONMENT=%~dp0.venv"
set "UV_NO_MODIFY_PATH=1"

echo ============================================================
echo   FlashDrop 环境准备
echo   全部安装在本项目目录内，不修改系统环境
echo ============================================================
echo.

rem ---------- 0) 已经准备好了？ ----------
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -c "import tkinter" >nul 2>nul
  if not errorlevel 1 (
    echo [已就绪] .venv 可用，双击 启动.bat 即可运行。
    pause
    exit /b 0
  )
)

rem ---------- 1) 优先复用系统 Python（本项目零第三方依赖）----------
set "SYS_PY="
where python >nul 2>nul && set "SYS_PY=python"
if not defined SYS_PY (
  where py >nul 2>nul && set "SYS_PY=py -3"
)

if defined SYS_PY (
  %SYS_PY% -c "import sys,tkinter; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul
  if not errorlevel 1 (
    echo [1/2] 检测到系统 Python，正在创建 .venv ...
    %SYS_PY% -m venv "%~dp0.venv" >nul 2>nul
    if exist "%~dp0.venv\Scripts\python.exe" (
      "%~dp0.venv\Scripts\python.exe" -c "import tkinter,sys;print('  Python',sys.version.split()[0],'- tkinter OK')"
      if not errorlevel 1 goto ok
    )
    echo.
    echo [提示] 创建 .venv 失败，但系统 Python 可以直接运行本程序。
    echo        直接双击 启动.bat 即可，无需继续。
    pause
    exit /b 0
  )
  echo [1/2] 系统 Python 不可用（版本低于 3.9 或缺 tkinter），改用项目内置 Python。
)

rem ---------- 2) 用 uv 装一个只属于本项目的 Python ----------
if exist "%~dp0tools\uv.exe" goto have_uv
if exist "%~dp0tools\uv\uv.exe" (
  copy /Y "%~dp0tools\uv\uv.exe" "%~dp0tools\uv.exe" >nul
  goto have_uv
)

echo [1/3] 正在下载 uv（约 60MB，只需一次）...
curl -L --retry 2 --connect-timeout 20 -o "%~dp0tools\uv.zip" "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
if errorlevel 1 goto dl_fail
if not exist "%~dp0tools\uv.zip" goto dl_fail

tar -xf "%~dp0tools\uv.zip" -C "%~dp0tools" 2>nul
if not exist "%~dp0tools\uv.exe" (
  powershell -NoProfile -Command "Expand-Archive -Force -LiteralPath '%~dp0tools\uv.zip' -DestinationPath '%~dp0tools'"
)
if not exist "%~dp0tools\uv.exe" goto dl_fail
del /q "%~dp0tools\uv.zip" >nul 2>nul

:have_uv
echo [2/3] 安装项目私有 Python 3.13 ...
"%~dp0tools\uv.exe" python install --no-bin 3.13
if errorlevel 1 goto fail

echo [3/3] 创建 .venv ...
"%~dp0tools\uv.exe" venv --python 3.13 "%~dp0.venv"
if errorlevel 1 goto fail

"%~dp0.venv\Scripts\python.exe" -c "import tkinter,sys;print('  Python',sys.version.split()[0],'- tkinter OK')"
if errorlevel 1 goto fail

:ok
echo.
echo 完成。双击 启动.bat 运行；需要看日志用 调试启动.bat。
pause
exit /b 0

:dl_fail
echo.
echo 下载 uv 失败。请手动下载后在 tools\ 下解压出 uv.exe：
echo   https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip
echo 或者直接安装 Python 3.9+（勾选 tcl/tk），再运行本脚本。
pause
exit /b 1

:fail
echo.
echo 安装失败，请看上面的错误信息。
pause
exit /b 1
