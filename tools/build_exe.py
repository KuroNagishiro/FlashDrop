"""把桌面端打包成单文件 FlashDrop.exe。

构建依赖（Python + PyInstaller）全部装在 tools/packenv，缓存也在 tools/，
不装全局包、不改 PATH、不写系统目录。exe 输出到项目根目录。
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
PACKENV = TOOLS / "packenv"
PYEXE = PACKENV / "Scripts" / "python.exe"
PYINSTALLER = PACKENV / "Scripts" / "pyinstaller.exe"
UV = TOOLS / "uv.exe"
ASSETS = ROOT / "assets"
ICO = ASSETS / "flashdrop.ico"
BUILD = ROOT / "build" / "exe"
OUT = ROOT / "FlashDrop.exe"

BLUE = (76, 108, 232)
LIGHT = (122, 150, 255)
WHITE = (255, 255, 255)
SIZE = 256


def env() -> dict:
    e = os.environ.copy()
    e["UV_CACHE_DIR"] = str(TOOLS / "uv-cache")
    e["UV_PYTHON_INSTALL_DIR"] = str(TOOLS / "python")
    e["UV_NO_MODIFY_PATH"] = "1"
    e["VIRTUAL_ENV"] = str(PACKENV)
    return e


def run(cmd: list[str], label: str, check: bool = True) -> subprocess.CompletedProcess:
    print(f"\n>>> {label}", flush=True)
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env())
    if p.stdout.strip():
        print(p.stdout.strip()[-3000:], flush=True)
    if check and p.returncode != 0:
        print((p.stderr or "").strip()[-5000:], file=sys.stderr, flush=True)
        raise SystemExit(f"[FAIL] {label} (exit {p.returncode})")
    return p


# ---------------------------------------------------------------- 图标
def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def make_icon() -> None:
    """纯标准库画一枚 256x256 图标：圆角蓝底 + 白色下箭头与托盘。"""
    if ICO.exists():
        print(">>> 图标已存在，跳过生成")
        return
    ASSETS.mkdir(parents=True, exist_ok=True)
    s, r = SIZE, 56
    rows = []
    for y in range(s):
        row = bytearray()
        for x in range(s):
            cx, cy = min(max(x, r), s - r), min(max(y, r), s - r)
            inside = (x - cx) ** 2 + (y - cy) ** 2 <= r * r
            if not inside:
                row.extend((0, 0, 0, 0))
                continue
            accent = (x - 0.85 * s) ** 2 + (y - 0.15 * s) ** 2 < (0.42 * s) ** 2
            col = LIGHT if accent else BLUE
            arrow = (
                (0.445 * s <= x <= 0.555 * s and 0.19 * s <= y <= 0.55 * s)
                or (0.50 * s <= y <= 0.75 * s
                    and abs(x - 0.5 * s) <= 0.20 * s * (0.75 * s - y) / (0.25 * s))
            )
            tray = (0.27 * s <= x <= 0.73 * s and 0.81 * s <= y <= 0.865 * s)
            row.extend((*(WHITE if (arrow or tray) else col), 255))
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + row for row in rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", s, s, 8, 6, 0, 0, 0))
           + _png_chunk(b"IDAT", zlib.compress(raw, 9))
           + _png_chunk(b"IEND", b""))
    # ICO：1 张图，宽高字节 0 表示 256，PNG 数据从偏移 22 开始
    ico = (struct.pack("<HHH", 0, 1, 1)
           + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
           + png)
    ICO.write_bytes(ico)
    print(f">>> 生成图标 {ICO} ({len(ico) // 1024} KB)")


# ---------------------------------------------------------------- 构建
def ensure_packenv() -> None:
    uv = UV if UV.exists() else "uv"
    if not PYEXE.exists():
        run([uv, "venv", "--python", "3.13", PACKENV], "1/4 创建打包专用虚拟环境")
    # 打包环境必须能 import 运行期依赖，否则 --collect-all 会静默跳过
    probe = subprocess.run(
        [PYEXE, "-c", "import PyInstaller,sys;print(PyInstaller.__version__)"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env())
    if probe.returncode != 0:
        run([uv, "pip", "install", "--python", PYEXE, "pyinstaller>=6.11"],
            "2/4 安装 PyInstaller（仅装入 tools/packenv）")
    else:
        print(f">>> PyInstaller 已就位 {probe.stdout.strip()}")
    dep = subprocess.run([PYEXE, "-c", "import tkinterdnd2"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env())
    if dep.returncode != 0:
        run([uv, "pip", "install", "--python", PYEXE, "tkinterdnd2>=0.4.0"],
            "2b/4 安装 tkinterdnd2（打包环境内，仅用于收集拖放库）")
    else:
        print(">>> tkinterdnd2 已就位")


def build() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    cmd = [
        PYINSTALLER, "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", "FlashDrop",
        "--icon", ICO,
        "--distpath", ROOT,
        "--workpath", BUILD / "work",
        "--specpath", BUILD,
        "--paths", ROOT,
        "--add-data", f"{ICO}{os.pathsep}assets",
        # 拖放依赖 tkdnd 的原生库与数据文件，必须整体带上
        "--collect-all", "tkinterdnd2",
        "--exclude-module", "tests",
        ROOT / "main.py",
    ]
    run(cmd, "3/4 PyInstaller 打包")
    if not OUT.exists():
        raise SystemExit("未生成 FlashDrop.exe")
    shutil.rmtree(BUILD / "work", ignore_errors=True)
    print(f"\nOK -> {OUT}  ({OUT.stat().st_size / 1024 / 1024:.1f} MB)", flush=True)
    print("双击即可运行；config.json 与 downloads/ 会生成在 exe 所在目录。", flush=True)


if __name__ == "__main__":
    make_icon()
    ensure_packenv()
    build()
