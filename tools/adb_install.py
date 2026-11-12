"""安装 FlashDrop.apk，并自动处理小米 / HyperOS 的「USB 安装提示」确认框。

用法：
    python tools/adb_install.py           立即尝试一次
    python tools/adb_install.py --wait    等待手机解锁后再安装（最多 10 分钟）

小米的确认框带 9 秒倒计时、到点自动「拒绝」，所以必须在弹框出现后
1 秒左右点「继续安装」。按钮坐标优先从 uiautomator 读取，读不到就用实测坐标兜底。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APK = ROOT / "FlashDrop.apk"


def find_adb() -> Path | None:
    """按优先级找 adb：环境变量 → PATH → 项目内 → 本机遗留路径。"""
    cands: list[Path] = []
    env = os.environ.get("ADB")
    if env:
        cands.append(Path(env))
    found = shutil.which("adb")
    if found:
        cands.append(Path(found))
    cands += [
        ROOT / "tools" / "android-sdk" / "platform-tools" / "adb.exe",
        ROOT / "tools" / "platform-tools" / "adb.exe",
        Path("I:/aaa/QtScrcpy-win-x64-v4.2.1/adb.exe"),   # 开发机遗留路径
    ]
    return next((p for p in cands if p.exists()), None)


ADB = find_adb()
FALLBACK_TAP = (347, 2365)   # 1200x2608 屏幕上「继续安装」的中心


def host(*args: str) -> str:
    if ADB is None:
        return ""
    return subprocess.run([str(ADB), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def shell(*args: str) -> str:
    if ADB is None:
        return ""
    return subprocess.run([str(ADB), "shell", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def installed() -> bool:
    return "com.flashdrop.app" in shell("pm", "list", "packages")


def unlocked() -> bool:
    vals = re.findall(r"isKeyguardShowing=(\w+)", shell("dumpsys", "window"))
    return bool(vals) and vals[-1] == "false"


def find_confirm_button() -> tuple[int, int] | None:
    shell("uiautomator", "dump", "/sdcard/fd_install_ui.xml")
    xml = shell("cat", "/sdcard/fd_install_ui.xml")
    for node in re.findall(r"<node[^>]*?/>", xml):
        t = re.search(r'text="([^"]*)"', node)
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if t and b and "继续安装" in t.group(1):
            x1, y1, x2, y2 = map(int, b.groups())
            return (x1 + x2) // 2, (y1 + y2) // 2
    return None


def attempt() -> tuple[bool, str]:
    p = subprocess.Popen(
        [str(ADB), "install", "-r", "-g", str(APK)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    time.sleep(1.2)
    pos = find_confirm_button() or FALLBACK_TAP
    for _ in range(3):
        shell("input", "tap", str(pos[0]), str(pos[1]))
        time.sleep(0.4)
    # uiautomator 读不到时用实测坐标再补一次
    if pos == FALLBACK_TAP:
        shell("input", "tap", "350", "2360")
    try:
        out, _ = p.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        p.kill()
        out, _ = p.communicate()
    out = out or ""
    if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in out:
        shell("pm", "uninstall", "com.flashdrop.app")
        out = host("install", "-r", "-g", str(APK))
    return installed(), out.strip()[-400:]


def main() -> int:
    if ADB is None:
        print("找不到 adb。请任选一种方式：")
        print("  1) 把 Android SDK 的 platform-tools 解压到 tools/platform-tools/")
        print("  2) 安装 adb 并加入 PATH")
        print("  3) 设置环境变量 ADB 指向 adb.exe")
        return 2
    if not APK.exists():
        print("找不到 FlashDrop.apk，请先运行 android\\构建APK.bat")
        return 1
    if installed() and "--force" not in sys.argv:
        print("已安装，跳过（需要强制重装加 --force）")
        return 0
    if "--wait" in sys.argv:
        print("等待手机解锁（最多 10 分钟）…", flush=True)
        deadline = time.time() + 600
        while time.time() < deadline:
            if unlocked():
                print("检测到已解锁，开始安装", flush=True)
                break
            time.sleep(2)
        else:
            print("TIMEOUT：手机一直处于锁屏，未安装。解锁后重跑本脚本即可。", flush=True)
            return 2
    for i in range(3):
        ok, out = attempt()
        if ok:
            print("INSTALL OK\n" + out, flush=True)
            shell("am", "start", "-n", "com.flashdrop.app/.MainActivity")
            return 0
        print(f"第 {i+1} 次未成功：{out}", flush=True)
        time.sleep(2)
    print("INSTALL FAILED：请解锁手机后重跑 安装到手机.bat", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
