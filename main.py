"""FlashDrop 桌面端入口。用「启动.bat」运行（pythonw，无控制台窗口）。"""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flashdrop.app import App  # noqa: E402


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
