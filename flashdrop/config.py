"""配置持久化。所有文件都写在程序根目录，不写注册表、不写 AppData。"""
from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from pathlib import Path


def _app_root() -> Path:
    """打包成 exe 后 __file__ 指向临时解压目录，必须以 exe 所在目录为准。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = _app_root()
CONFIG_PATH = ROOT / "config.json"
INBOX = ROOT / "downloads"


def default_name() -> str:
    try:
        host = socket.gethostname()
    except Exception:
        host = "PC"
    return "电脑-" + host


def load() -> dict:
    cfg = {
        "id": str(uuid.uuid4()),
        "name": default_name(),
        "last_peer_id": "",
    }
    existed = CONFIG_PATH.exists()
    try:
        if existed:
            saved = json.loads(CONFIG_PATH.read_text("utf-8"))
            for k in cfg:
                if isinstance(saved.get(k), type(cfg[k])):
                    cfg[k] = saved[k]
    except Exception:
        pass
    INBOX.mkdir(parents=True, exist_ok=True)
    if not existed:
        save(cfg)  # 首次运行即固定设备 ID，避免异常退出后每次都变
    return cfg


def save(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8"
        )
    except OSError:
        pass


def inbox() -> Path:
    INBOX.mkdir(parents=True, exist_ok=True)
    return INBOX


def local_ips() -> list[str]:
    """枚举本机 IPv4，覆盖多网卡/虚拟网卡场景。"""
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                found.add(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        found.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(found)


def broadcast_addresses(ips: list[str]) -> list[str]:
    out = {"255.255.255.255"}
    for ip in ips:
        parts = ip.split(".")
        if len(parts) == 4:
            out.add(".".join(parts[:3]) + ".255")
    return sorted(out)
