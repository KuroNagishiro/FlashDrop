"""FlashDrop 桌面端界面（tkinter，纯标准库，零第三方依赖）。

横向双栏：左栏发送（连接 / 文件 / 文字），右栏接收（文件列表 / 日志）。
窗口尺寸按内容与屏幕工作区自适应，底部状态栏恒定可见，默认不需要滚动。
"""
from __future__ import annotations

import ctypes
import math
import os
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import config, protocol as P
from .discovery import Discovery, Peer
from .engine import Engine

# ---------------------------------------------------------------- 主题
BG = "#F1F4FA"          # 页面底色
CARD = "#FFFFFF"        # 卡片
BORDER = "#E5EAF4"      # 描边
TEXT = "#111827"        # 主文字
MUTED = "#6B7280"       # 次要文字
SUBTLE = "#8B95A7"      # 更弱
PRIMARY = "#2F6BFF"     # 品牌蓝
PRIMARY_2 = "#6D5BFF"   # 渐变终点
PRIMARY_DARK = "#1E4FD8"
SOFT = "#EAF1FF"        # 淡蓝底
SOFT_HOVER = "#DCE8FF"
GHOST = "#EDF1F8"
GHOST_HOVER = "#E1E7F2"
GREEN = "#12B76A"
RED = "#E5342B"
WARN = "#B45309"
WARN_BG = "#FFF7ED"
SOFT_BG = "#F7F9FD"
HEAD_H = 96
FOOT_H = 74
FONT = "Microsoft YaHei UI"
MONO = "Consolas"


def _setup_dpi() -> float:
    """让进程感知系统 DPI，返回缩放系数（1.0 = 100%）。

    必须在 tk.Tk() 之前调用；本模块在 main.py 创建窗口前就被 import。
    """
    if sys.platform != "win32":
        return 1.0
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 90)  # LOGPIXELSY
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return max(1.0, (dpi or 96) / 96.0)
    except Exception:
        return 1.0


DPI_SCALE = _setup_dpi()


def f(size: int, bold: bool = False, mono: bool = False):
    return (MONO if mono else FONT, size, "bold" if bold else "normal")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def work_area():
    """返回屏幕工作区 (x, y, 宽, 高)，已排除任务栏。"""
    if sys.platform != "win32":
        return 0, 0, 1920, 1080

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    try:
        r = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
            return r.left, r.top, r.right - r.left, r.bottom - r.top
    except Exception:
        pass
    return 0, 0, 1920, 1040


# ---------------------------------------------------------------- 绘图工具
def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _mix(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    a, b = _rgb(c1), _rgb(c2)
    return "#%02x%02x%02x" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """在 Canvas 上画圆角矩形（多段弧线 + smooth）。"""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts: list[float] = []
    corners = ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0),
               (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180))
    for cx, cy, start in corners:
        for step in range(0, 91, 15):
            ang = math.radians(start + step)
            pts += [cx + r * math.cos(ang), cy + r * math.sin(ang)]
    kw.setdefault("outline", "")
    return canvas.create_polygon(pts, smooth=True, **kw)


def _bg_of(widget) -> str:
    try:
        return str(widget.cget("bg"))
    except Exception:
        return BG


def text_w(text: str, font) -> int:
    try:
        return tkfont.Font(font=font).measure(text)
    except Exception:
        return max(40, len(text) * 8)


# ---------------------------------------------------------------- 控件
class Button(tk.Canvas):
    """圆角按钮（Canvas 自绘，保留 hover / disabled 状态）。"""

    KINDS = {
        "primary": (PRIMARY, "#FFFFFF", PRIMARY_DARK),
        "soft": (SOFT, PRIMARY, SOFT_HOVER),
        "ghost": (GHOST, TEXT, GHOST_HOVER),
    }

    def __init__(self, parent, text, command=None, kind="ghost", height=38,
                 radius=11, font=None, padx=18, width=None):
        super().__init__(parent, bg=_bg_of(parent), highlightthickness=0, bd=0,
                         height=height, width=width or 1, cursor="hand2")
        self._text = text
        self._cmd = command
        self._radius = radius
        self._font = font or f(10)
        self._padx = padx
        self._fill, self._fg, self._hover = self.KINDS[kind]
        self._hovering = False
        self._enabled = True
        if width is None:
            super().configure(width=text_w(text, self._font) + padx * 2)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self._draw()

    # --- 状态 ---
    def set_text(self, text: str) -> None:
        self._text = text
        self.configure(width=text_w(text, self._font) + self._padx * 2)
        self._draw()

    def get_text(self) -> str:
        return self._text

    def set_state(self, state: str) -> None:
        self._enabled = state != "disabled"
        try:
            self.configure(cursor="hand2" if self._enabled else "arrow")
        except Exception:
            pass
        self._draw()

    # --- 事件 ---
    def _on_enter(self, _e=None):
        self._hovering = True
        self._draw()

    def _on_leave(self, _e=None):
        self._hovering = False
        self._draw()

    def _on_click(self, _e=None):
        if self._enabled and self._cmd:
            self._cmd()

    # --- 绘制 ---
    def _draw(self) -> None:
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 2:
            w = int(self.cget("width"))
        if h <= 2:
            h = int(self.cget("height"))
        self.delete("all")
        if not self._enabled:
            fill, fg = "#EDF1F7", "#A9B1C1"
        else:
            fill = self._hover if self._hovering else self._fill
            fg = self._fg
        round_rect(self, 1, 1, max(3, w - 1), max(3, h - 1), self._radius,
                   fill=fill, outline="")
        self.create_text(w / 2, h / 2 + 1, text=self._text, fill=fg, font=self._font)


class Card(tk.Frame):
    """白色圆角卡片；内容放在 .body，标题栏放在 .head。"""

    def __init__(self, parent, title: str = "", dot=PRIMARY,
                 padx=16, pady=14, radius=16):
        super().__init__(parent, bg=BG)
        self._radius = radius
        self._padx = padx
        self._pady = pady
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=CARD)
        self._win = self.canvas.create_window(padx, pady, window=self.body, anchor="nw")
        self._rect = None
        self.head = None
        if title:
            self.head = tk.Frame(self.body, bg=CARD)
            self.head.pack(fill="x", pady=(0, 10))
            mark = tk.Canvas(self.head, width=5, height=15, bg=CARD,
                             highlightthickness=0, bd=0)
            round_rect(mark, 0, 0, 5, 15, 2.5, fill=dot, outline="")
            mark.pack(side="left", padx=(0, 8))
            tk.Label(self.head, text=title, bg=CARD, fg=TEXT,
                     font=f(11, True)).pack(side="left")
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)

    def _on_body(self, _e=None):
        need = max(self.body.winfo_reqheight(), 8) + self._pady * 2
        if abs(int(self.canvas.cget("height")) - need) > 1:
            self.canvas.configure(height=need)
        self._draw()

    def _on_canvas(self, event):
        self.canvas.itemconfig(self._win,
                               width=max(20, event.width - self._padx * 2))
        self._draw()

    def _draw(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 4 or h <= 4:
            return
        if self._rect is not None:
            self.canvas.delete(self._rect)
        self._rect = round_rect(self.canvas, 1, 1, w - 1, h - 1, self._radius,
                                fill=CARD, outline=BORDER)
        self.canvas.tag_lower(self._rect)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = config.load()
        self.selected: list[str] = []
        self.peers: list[Peer] = []
        self.current: Peer | None = None
        self.busy = False
        self.last_send: tuple | None = None
        self.row_paths: dict[str, Path] = {}

        root.title("FlashDrop · 局域网互传")
        root.configure(bg=BG)
        try:
            root.tk.call("tk", "scaling", 1.3333 * DPI_SCALE)
        except Exception:
            pass
        self._geometry()
        try:
            base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) \
                else config.ROOT
            ico = base / "assets" / "flashdrop.ico"
            if ico.exists():
                root.iconbitmap(str(ico))
        except Exception:
            pass

        self._style()
        self._build()
        self._bind_wheel(self.content)
        self.discovery = Discovery(
            self.cfg["id"], self.cfg["name"], "windows",
            on_change=lambda: self.ui(self.refresh_peers),
            on_log=self.log,
        )
        self.engine = Engine(
            self.cfg["name"], config.inbox,
            callbacks={
                "on_log": self.log,
                "on_progress": lambda d, t: self.ui(lambda: self.progress(d, t)),
                "on_received_text": lambda t, s: self.ui(lambda: self.on_text(t, s)),
                "on_received_files": lambda c, t, s: self.ui(lambda: self.on_files(c, t, s)),
            },
        )
        self._start_services()
        self.refresh_received()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(80, self._fit_window)

    # ---------- 窗口尺寸：按内容与工作区自适应 ----------
    def _geometry(self) -> None:
        wx, wy, ww, wh = work_area()
        w = min(940, max(720, ww - 80))
        h = min(820, max(520, wh - 90))
        x = wx + max(0, (ww - w) // 2)
        y = wy + max(0, (wh - h) // 2 - 10)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(760, 480)

    def _fit_window(self) -> None:
        """让窗口高度刚好容纳双栏内容，避免出现竖向滚动。"""
        try:
            self.root.update_idletasks()
            wx, wy, ww, wh = work_area()
            w = self.root.winfo_width()
            need = (self.content.winfo_reqheight()
                    + HEAD_H + FOOT_H + 10)
            h = min(max(need, 560), wh - 70)
            if abs(h - self.root.winfo_height()) > 4:
                x = wx + max(0, (ww - w) // 2)
                y = wy + max(0, (wh - h) // 2 - 8)
                self.root.geometry(f"{w}x{h}+{x}+{y}")
                self.root.update_idletasks()
        except Exception:
            pass
        self._sync_scroll()

    def _sync_scroll(self) -> None:
        total = self.content.winfo_reqheight()
        view = self.canvas.winfo_height()
        need = total > view + 6
        if need and not self.vsb.winfo_ismapped():
            self.vsb.pack(side="right", fill="y", padx=(0, 6), pady=6,
                          before=self.canvas)
        elif not need and self.vsb.winfo_ismapped():
            self.vsb.pack_forget()
            self.canvas.yview_moveto(0)

    # ---------- 控件样式 ----------
    def _style(self) -> None:
        s = ttk.Style(self.root)
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure("TCombobox", fieldbackground=SOFT_BG, background=SOFT_BG,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    arrowcolor=PRIMARY, borderwidth=1, padding=(10, 7), font=f(10))
        s.map("TCombobox", fieldbackground=[("readonly", SOFT_BG)],
              bordercolor=[("focus", PRIMARY)], foreground=[("readonly", TEXT)])
        s.configure("FD.Horizontal.TProgressbar", troughcolor="#E7EDF9",
                    background=PRIMARY, lightcolor=PRIMARY, darkcolor=PRIMARY,
                    borderwidth=0, thickness=6)
        s.configure("FD.Vertical.TScrollbar", background="#CFD8E6",
                    troughcolor=BG, borderwidth=0, arrowsize=12)
        s.configure("FD.Treeview", background=CARD, fieldbackground=CARD,
                    foreground=TEXT, borderwidth=0,
                    rowheight=int(32 * DPI_SCALE), font=f(9))
        s.configure("FD.Treeview.Heading", background=SOFT_BG, foreground=SUBTLE,
                    relief="flat", borderwidth=0, font=f(9, True), padding=(8, 8))
        s.map("FD.Treeview", background=[("selected", SOFT_HOVER)],
              foreground=[("selected", TEXT)])

    # ---------- 线程安全 ----------
    def ui(self, fn) -> None:
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def log(self, msg: str) -> None:
        self.ui(lambda: self._append_log(msg))

    def _append_log(self, msg: str) -> None:
        self.logbox.configure(state="normal")
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")
        while float(self.logbox.index("end-1c").split(".")[0]) > 60:
            self.logbox.delete("1.0", "2.0")
        self.logbox.configure(state="disabled")

    # ---------- 界面 ----------
    def _build(self) -> None:
        # ============ 渐变头部 ============
        self.head = tk.Canvas(self.root, height=HEAD_H, bg=PRIMARY,
                              highlightthickness=0, bd=0)
        self.head.pack(fill="x", side="top")
        self.head.bind("<Configure>", self._paint_head)

        # ============ 固定底部状态栏 ============
        foot = tk.Frame(self.root, bg=CARD, height=FOOT_H)
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        self.bar = ttk.Progressbar(foot, mode="determinate", maximum=100,
                                   style="FD.Horizontal.TProgressbar")
        self.bar.pack(fill="x", padx=22, pady=(13, 9))
        frow = tk.Frame(foot, bg=CARD)
        frow.pack(fill="x", padx=22)
        self.dot = tk.Canvas(frow, width=10, height=10, bg=CARD,
                             highlightthickness=0, bd=0)
        self.dot.create_oval(1, 1, 9, 9, fill=GREEN, outline="")
        self.dot.pack(side="left", padx=(0, 7))
        self.status = tk.Label(frow, text="就绪 · 等待对端", bg=CARD, fg=TEXT,
                               font=f(10, True), anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.retry_btn = Button(frow, "重试上一次发送", self.retry,
                                kind="soft", height=30, padx=14, font=f(9, True))
        self.retry_btn.pack(side="right")
        self.retry_btn.pack_forget()

        # ============ 滚动容器（默认不出现滚动条）============
        holder = tk.Frame(self.root, bg=BG)
        holder.pack(fill="both", expand=True, side="top")
        self.canvas = tk.Canvas(holder, bg=BG, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview,
                                 style="FD.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=BG)
        self.win_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.content.bind("<Configure>",
                          lambda _e: self.canvas.configure(
                              scrollregion=self.canvas.bbox("all")))

        # ============ 双栏 ============
        body = tk.Frame(self.content, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=16)
        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))

        self._build_left(left)
        self._build_right(right)

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self.win_id, width=event.width)
        self._sync_scroll()

    def _paint_head(self, _event=None) -> None:
        c = self.head
        c.delete("all")
        w = max(c.winfo_width(), 480)
        for i in range(0, HEAD_H, 2):
            c.create_rectangle(0, i, w, i + 2, outline="",
                               fill=_mix(PRIMARY, PRIMARY_2, i / HEAD_H))
        c.create_text(26, 40, text="FlashDrop", anchor="w",
                      fill="#FFFFFF", font=f(21, True))
        c.create_text(27, 70, text="局域网极速互传 · 打开即可接收", anchor="w",
                      fill="#CFE0FF", font=f(9))

        bw, bh = 128, 30
        x2 = w - 24
        x1, y1 = x2 - bw, 28
        round_rect(c, x1, y1, x2, y1 + bh, 15,
                   fill=_mix(PRIMARY, "#FFFFFF", 0.18), outline="")
        c.create_oval(x1 + 13, y1 + 11, x1 + 21, y1 + 19,
                      fill="#5CE3A0", outline="")
        c.create_text(x1 + 28, y1 + bh / 2 + 1, text="接收中", anchor="w",
                      fill="#FFFFFF", font=f(9, True))
        ips = "、".join(config.local_ips()[:2]) or "未获取"
        c.create_text(x2, 72, text=f"{self.cfg['name']}　·　{ips}", anchor="e",
                      fill="#CFE0FF", font=f(9))

    # ---------- 左栏：发送 ----------
    def _build_left(self, parent) -> None:
        # 连接
        c1 = Card(parent, "连接", dot=GREEN)
        c1.pack(fill="x", pady=(0, 14))
        self.button(c1.head, "手填 IP", self.manual_ip, kind="ghost",
                    height=26, px=12, font=f(9)).pack(side="right")
        self.peer_state = tk.Label(c1.head, text="正在寻找对端…", bg=CARD, fg=SUBTLE,
                                   font=f(9))
        self.peer_state.pack(side="right", padx=8)

        row = tk.Frame(c1.body, bg=CARD)
        row.pack(fill="x", pady=(0, 8))
        self.peer_var = tk.StringVar()
        self.peer_box = ttk.Combobox(row, textvariable=self.peer_var, state="readonly",
                                     font=f(10), width=26)
        self.peer_box.pack(side="left", fill="x", expand=True)
        self.peer_box.bind("<<ComboboxSelected>>", self.on_peer_chosen)
        tk.Label(c1.body, text="⚠ 仅家庭私有 WiFi：同网段设备均可投递，内容不加密",
                 bg=CARD, fg=WARN, font=f(8), anchor="w").pack(fill="x")

        # 发送文件
        c2 = Card(parent, "发送文件 / 文件夹")
        c2.pack(fill="x", pady=(0, 14))
        srow = tk.Frame(c2.body, bg=CARD)
        srow.pack(fill="x", pady=(0, 8))
        self.button(srow, "选文件", self.pick_files, kind="soft",
                    height=30, px=14, font=f(9, True)).pack(side="left")
        self.button(srow, "选文件夹", self.pick_dir, kind="soft",
                    height=30, px=14, font=f(9, True)).pack(side="left", padx=7)
        self.button(srow, "清空", self.clear_files, kind="ghost",
                    height=30, px=14, font=f(9)).pack(side="left")

        self.listbox = tk.Listbox(c2.body, height=3, relief="flat", bd=0,
                                  bg=SOFT_BG, fg=TEXT, font=f(9),
                                  highlightbackground=BORDER, highlightthickness=1,
                                  activestyle="none", selectbackground=SOFT_HOVER,
                                  selectforeground=TEXT, justify="left")
        self.listbox.pack(fill="x", pady=(0, 9))
        self._refresh_list()

        self.send_file_btn = self.button(c2.body, "发送到 …", self.send_files,
                                         kind="primary", height=42, font=f(10, True))
        self.send_file_btn.pack(fill="x")

        # 发送文字
        c3 = Card(parent, "发送文字")
        c3.pack(fill="x")
        tk.Label(c3.head, text="收到后自动写入剪贴板", bg=CARD, fg=SUBTLE,
                 font=f(9)).pack(side="right")
        self.textbox = tk.Text(c3.body, height=3, relief="flat", bd=0, bg=SOFT_BG,
                               fg=TEXT, font=f(10), wrap="word", padx=9, pady=7,
                               highlightbackground=BORDER, highlightthickness=1,
                               insertbackground=PRIMARY)
        self.textbox.pack(fill="x", pady=(0, 9))
        self.send_text_btn = self.button(c3.body, "发送文字到 …", self.send_text,
                                         kind="primary", height=42, font=f(10, True))
        self.send_text_btn.pack(fill="x")

    # ---------- 右栏：接收 ----------
    def _build_right(self, parent) -> None:
        c4 = Card(parent, "已接收文件", dot=GREEN)
        c4.pack(fill="x", pady=(0, 14))
        self.received_count = tk.Label(c4.head, text="0 个", bg=SOFT, fg=PRIMARY,
                                       font=f(9, True), padx=9, pady=2)
        self.received_count.pack(side="right")
        self.button(c4.head, "刷新", self.refresh_received, kind="ghost",
                    height=26, px=12, font=f(9)).pack(side="right", padx=7)

        table = tk.Frame(c4.body, bg=CARD, highlightbackground=BORDER,
                         highlightthickness=1)
        table.pack(fill="x", pady=(0, 10))
        self.tree = ttk.Treeview(table, columns=("name", "size", "time"),
                                 show="headings", height=8, style="FD.Treeview",
                                 selectmode="browse")
        for key, title, width, anchor in (
                ("name", "文件名", 250, "w"),
                ("size", "大小", 86, "e"),
                ("time", "接收时间", 108, "center")):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=int(width * DPI_SCALE), anchor=anchor,
                             stretch=(key == "name"))
        self.tree.tag_configure("odd", background=SOFT_BG)
        self.tvsc = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview,
                                  style="FD.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=self.tvsc.set)
        self.tvsc.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="x", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())
        self.tree.bind("<Return>", lambda _e: self.open_selected())
        self.empty_label = tk.Label(table, text="还没有收到文件　·　收件目录 downloads/",
                                    bg=CARD, fg=SUBTLE, font=f(9), pady=66)
        self.empty_label.pack(fill="x")
        self.tree.pack_forget()
        self.tvsc.pack_forget()

        brow = tk.Frame(c4.body, bg=CARD)
        brow.pack(fill="x")
        self.button(brow, "打开接收文件夹 ↗", self.open_inbox, kind="soft",
                    height=34, px=16, font=f(9, True)).pack(side="left")
        tk.Label(brow, text="双击文件即可打开", bg=CARD, fg=SUBTLE,
                 font=f(9)).pack(side="left", padx=10)

        c5 = Card(parent, "运行日志", dot="#A9B4C6")
        c5.pack(fill="x")
        self.logbox = tk.Text(c5.body, height=5, relief="flat", bd=0, bg=SOFT_BG,
                              fg=MUTED, font=f(9, mono=True), wrap="word",
                              padx=9, pady=7, highlightbackground=BORDER,
                              highlightthickness=1)
        self.logbox.pack(fill="x")
        self.logbox.configure(state="disabled")

    def button(self, parent, text, command, kind="ghost", height=34,
               px=16, font=None, width=None):
        return Button(parent, text, command, kind=kind, height=height,
                      radius=10, font=font, padx=px, width=width)

    def _bind_wheel(self, widget) -> None:
        skip = (tk.Text, tk.Listbox, ttk.Treeview)
        for child in widget.winfo_children():
            if not isinstance(child, skip):
                child.bind("<MouseWheel>", self._wheel, add="+")
                self._bind_wheel(child)

    def _wheel(self, event) -> None:
        step = -3 if event.delta > 0 else 3
        try:
            self.canvas.yview_scroll(step, "units")
        except Exception:
            pass

    def jump_to_received(self) -> None:
        self.root.update_idletasks()
        self.canvas.yview_moveto(0)

    # ---------- 服务 ----------
    def _start_services(self) -> None:
        for name, fn in (("TCP 接收", self.engine.start), ("自动发现", self.discovery.start)):
            try:
                fn()
            except Exception as e:
                self.set_status(f"{name}启动失败：{e}", error=True)
                self._append_log(f"{name}启动失败：{e}")
        self._append_log(f"收件目录：{config.inbox()}")
        self._append_log("等待对端…（两端都要打开 FlashDrop）")

    # ---------- 接收文件列表 ----------
    def received_items(self) -> list[tuple[Path, int, float]]:
        base = config.inbox()
        out: list[tuple[Path, int, float]] = []
        try:
            for p in base.rglob("*"):
                try:
                    if p.is_file():
                        st = p.stat()
                        out.append((p, st.st_size, st.st_mtime))
                except OSError:
                    continue
        except OSError:
            pass
        out.sort(key=lambda x: x[2], reverse=True)
        return out[:300]

    def refresh_received(self) -> None:
        base = config.inbox()
        items = self.received_items()
        self.tree.delete(*self.tree.get_children())
        self.row_paths.clear()
        for i, (p, size, mtime) in enumerate(items):
            try:
                rel = p.relative_to(base).as_posix()
            except ValueError:
                rel = p.name
            stamp = datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
            iid = self.tree.insert("", "end", values=(rel, human(size), stamp),
                                   tags=("odd",) if i % 2 else ())
            self.row_paths[iid] = p
        n = len(items)
        self.received_count.configure(text=f"{n} 个")
        if n:
            self.empty_label.pack_forget()
            self.tvsc.pack(side="right", fill="y")
            self.tree.pack(side="left", fill="x", expand=True)
        else:
            self.tree.pack_forget()
            self.tvsc.pack_forget()
            self.empty_label.pack(fill="x")
        self.root.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_scroll()

    def open_selected(self) -> None:
        sel = self.tree.selection() or (self.tree.focus(),)
        path = self.row_paths.get(sel[0] if sel else "")
        if path is None:
            self.refresh_received()
            return
        if not path.exists():
            self.set_status("文件已不在收件目录中", error=True)
            self.refresh_received()
            return
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            try:
                subprocess.Popen(["explorer", str(path)])
            except Exception as e:
                messagebox.showerror("无法打开", str(e), parent=self.root)

    def open_inbox(self) -> None:
        folder = config.inbox()
        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]
        except Exception:
            try:
                subprocess.Popen(["explorer", str(folder)])
            except Exception as e:
                messagebox.showerror("无法打开", str(e), parent=self.root)
        self.set_status(f"已打开收件目录：{folder}")

    # ---------- 对端 ----------
    def refresh_peers(self) -> None:
        self.peers = self.discovery.peers()
        labels = [p.label() for p in self.peers]
        self.peer_box.configure(values=labels)
        if not self.peers:
            self.current = None
            self.peer_var.set("")
            self.peer_state.configure(text="未发现对端 · 请打开手机 App，或点「手填 IP」")
        else:
            keep = self.cfg.get("last_peer_id", "")
            chosen = next((p for p in self.peers if p.id == keep), None)
            if chosen is None and len(self.peers) == 1:
                chosen = self.peers[0]          # 单对端：自动选中，不问
            if chosen is None:
                chosen = self.peers[0]
            self.current = chosen
            self.cfg["last_peer_id"] = chosen.id
            config.save(self.cfg)
            self.peer_var.set(chosen.label())
            self.peer_state.configure(text=f"已发现 {len(self.peers)} 个")
        self._update_buttons()

    def on_peer_chosen(self, _event=None) -> None:
        idx = self.peer_box.current()
        if 0 <= idx < len(self.peers):
            self.current = self.peers[idx]
            self.cfg["last_peer_id"] = self.current.id
            config.save(self.cfg)
            self._update_buttons()

    def _update_buttons(self) -> None:
        name = self.current.name if self.current else "…"
        self.send_file_btn.set_text(f"发送到 {name}")
        self.send_text_btn.set_text(f"发送文字到 {name}")

    def manual_ip(self) -> None:
        ip = simpledialog.askstring("手填 IP", "输入对端的局域网 IP（例如 192.168.1.23）：",
                                    parent=self.root)
        if ip and ip.strip():
            self.discovery.ping(ip.strip())

    # ---------- 选择文件 ----------
    def pick_files(self) -> None:
        files = filedialog.askopenfilenames(title="选择要发送的文件")
        self.selected.extend(files)
        self._refresh_list()

    def pick_dir(self) -> None:
        d = filedialog.askdirectory(title="选择要发送的文件夹")
        if d:
            self.selected.append(d)
        self._refresh_list()

    def clear_files(self) -> None:
        self.selected.clear()
        self._refresh_list()

    def _refresh_list(self) -> None:
        if not hasattr(self, "listbox"):
            return
        self.listbox.delete(0, "end")
        if not self.selected:
            self.listbox.insert("end", "　还没选择文件")
            self.listbox.itemconfigure(0, foreground=SUBTLE)
            return
        for p in self.selected:
            self.listbox.insert("end", "  " + str(p))

    # ---------- 发送 ----------
    def _require_peer(self) -> bool:
        if self.current is None:
            messagebox.showwarning("没有对端", "请先打开手机 App，或点「手填 IP」。",
                                   parent=self.root)
            return False
        return True

    def _run(self, kind: str, payload) -> None:
        if self.busy or not self._require_peer():
            return
        peer = self.current
        self.busy = True
        self.retry_btn.pack_forget()
        self.send_file_btn.set_state("disabled")
        self.send_text_btn.set_state("disabled")
        self.bar.configure(value=0)
        self.set_status(f"正在发送到 {peer.name} …")

        def work():
            if kind == "files":
                ok, msg = self.engine.send_files(payload, peer.ip, peer.tcp)
            else:
                ok, msg = self.engine.send_text(payload, peer.ip, peer.tcp)
            self.last_send = (kind, payload) if not ok else None
            self.ui(lambda: self._send_done(ok, msg))

        threading.Thread(target=work, daemon=True, name="fd-send").start()

    def _send_done(self, ok: bool, msg: str) -> None:
        self.busy = False
        self.send_file_btn.set_state("normal")
        self.send_text_btn.set_state("normal")
        self.set_status(("已送达 · " if ok else "发送失败 · ") + msg, error=not ok)
        if ok:
            self.bar.configure(value=100)
            self.selected.clear()
            self._refresh_list()
            self.textbox.delete("1.0", "end")
        else:
            self._append_log("发送失败：" + msg)
            self.retry_btn.pack(side="right")

    def retry(self) -> None:
        if self.last_send:
            self._run(*self.last_send)

    def send_files(self) -> None:
        if not self.selected:
            messagebox.showinfo("还没选文件", "先点「选文件」或「选文件夹」。",
                                parent=self.root)
            return
        self._run("files", list(self.selected))

    def send_text(self) -> None:
        text = self.textbox.get("1.0", "end").rstrip("\n")
        if not text.strip():
            messagebox.showinfo("文字是空的", "把要发的文字粘贴进文本框。",
                                parent=self.root)
            return
        self._run("text", text)

    # ---------- 接收 ----------
    def progress(self, done: int, total: int) -> None:
        if total > 0:
            self.bar.configure(value=min(100, done * 100 / total))
            self.status.configure(
                text=f"发送中 {done / 1048576:.1f} / {total / 1048576:.1f} MB",
                fg=PRIMARY)
            self.dot.itemconfigure(1, fill=PRIMARY)

    def on_text(self, text: str, sender: str) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update_idletasks()
            extra = "，已写入剪贴板"
        except Exception:
            extra = ""
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", text)
        self.set_status(f"收到 {sender} 的文字{extra}")
        self._append_log(f"收到文字：{text[:60]}{'…' if len(text) > 60 else ''}")

    def on_files(self, count: int, targets: list[Path], sender: str) -> None:
        self.set_status(f"已收到 {sender} 的 {count} 项，保存在 downloads/")
        self._append_log(f"收到 {count} 项，存于 {config.inbox()}")
        for t in targets:
            self._append_log("  " + t.name)
        self.refresh_received()

    def set_status(self, msg: str, error: bool = False) -> None:
        msg = msg.lstrip("● ")
        good = ("就绪" in msg or "已收到" in msg or "已送达" in msg
                or "已打开" in msg)
        color = RED if error else (GREEN if good else PRIMARY)
        self.status.configure(text=msg, fg=TEXT)
        self.dot.itemconfigure(1, fill=color)

    def close(self) -> None:
        try:
            config.save(self.cfg)
            self.discovery.stop()
            self.engine.stop()
        finally:
            self.root.destroy()
