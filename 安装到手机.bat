@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem adb 查找顺序：项目内 SDK -> PATH -> 开发机遗留路径
set "ADB="
if exist "%~dp0tools\android-sdk\platform-tools\adb.exe" set "ADB=%~dp0tools\android-sdk\platform-tools\adb.exe"
if not defined ADB if exist "%~dp0tools\platform-tools\adb.exe" set "ADB=%~dp0tools\platform-tools\adb.exe"
if not defined ADB (
  where adb >nul 2>nul && set "ADB=adb"
)
if not defined ADB if exist "I:\aaa\QtScrcpy-win-x64-v4.2.1\adb.exe" set "ADB=I:\aaa\QtScrcpy-win-x64-v4.2.1\adb.exe"

if not defined ADB (
  echo 未找到 adb。
  echo 请把 Android SDK 的 platform-tools 解压到 tools\platform-tools\，
  echo 或安装 adb 并加入 PATH，或设置环境变量 ADB 指向 adb.exe。
  pause
  exit /b 1
)

echo ============================================================
echo   FlashDrop 手机端安装 / 升级
echo   小米会弹「USB 安装提示」，脚本会自动点「继续安装」。
echo   如果手机处于锁屏，请先解锁再运行本脚本。
echo ============================================================
echo.
"%ADB%" push "%~dp0FlashDrop.apk" /sdcard/Download/FlashDrop.apk
echo.
"%PY%" "%~dp0tools\adb_install.py" --force
echo.
if errorlevel 1 (
  echo 安装未完成。请解锁手机后重跑本脚本；
  echo 或在手机上打开「文件管理 - 下载 - FlashDrop.apk」手动安装。
) else (
  echo 完成。两端连同一个 WiFi、都打开 FlashDrop 即可互传。
)
pause
