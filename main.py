"""FlashDrop 桌面端入口。用「启动.bat」运行（pythonw，无控制台窗口）。"""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flashdrop.app import App  # noqa: E402


def make_root() -> tuple[tk.Tk, bool]:
    """优先使用带文件拖放能力的 Tk；tkinterdnd2 不可用时退回标准 Tk。"""
    try:
        from tkinterdnd2 import TkinterDnD
        return TkinterDnD.Tk(), True
    except Exception:
        return tk.Tk(), False


def main() -> None:
    root, dnd = make_root()
    App(root, dnd=dnd)
    root.mainloop()


if __name__ == "__main__":
    main()
