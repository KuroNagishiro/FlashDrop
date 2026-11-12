"""发现：UDP 子网广播 hello，不依赖 mDNS / Bonjour。

对应 ADR-0004：Windows 的 mDNS 服务发布不可靠，Android 17 的 NsdManager
另有本地网络权限复杂度；两端都是自家 App 且同子网，广播包足够。
发现只负责「找到对端」，不含任何授权含义。
"""
from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass, field

from . import config, protocol as P


@dataclass
class Peer:
    id: str
    name: str
    os: str
    ip: str
    tcp: int
    last_seen: float = field(default_factory=time.monotonic)
    manual: bool = False

    def label(self) -> str:
        return f"{self.name} ({self.ip})" if self.manual else self.name


class Discovery:
    def __init__(self, my_id: str, my_name: str, my_os: str,
                 on_change, on_log):
        self.my_id = my_id
        self.my_name = my_name
        self.my_os = my_os
        self.on_change = on_change
        self.on_log = on_log
        self._peers: dict[str, Peer] = {}
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def hello(self) -> bytes:
        return json.dumps({
            "p": P.HELLO_TAG, "v": P.VERSION,
            "id": self.my_id, "name": self.my_name,
            "os": self.my_os, "tcp": P.TCP_PORT, "bye": False,
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @property
    def bye(self) -> bytes:
        return json.dumps({
            "p": P.HELLO_TAG, "v": P.VERSION,
            "id": self.my_id, "name": self.my_name,
            "os": self.my_os, "tcp": P.TCP_PORT, "bye": True,
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def start(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            s.bind(("", P.UDP_PORT))
        except OSError as e:
            s.close()
            raise RuntimeError(f"无法监听 UDP {P.UDP_PORT}：{e}") from e
        s.settimeout(1.0)
        self._sock = s
        self._threads = [
            threading.Thread(target=self._recv_loop, daemon=True, name="fd-disc-recv"),
            threading.Thread(target=self._announce_loop, daemon=True, name="fd-disc-ann"),
            threading.Thread(target=self._sweep_loop, daemon=True, name="fd-disc-sweep"),
        ]
        for t in self._threads:
            t.start()

    def _destinations(self) -> list[str]:
        return config.broadcast_addresses(config.local_ips())

    def _announce(self, payload: bytes, dests: list[str] | None = None) -> None:
        if self._sock is None:
            return
        for addr in (dests if dests is not None else self._destinations()):
            try:
                self._sock.sendto(payload, (addr, P.UDP_PORT))
            except OSError:
                pass

    def _announce_loop(self) -> None:
        while not self._stop.is_set():
            self._announce(self.hello)
            self._stop.wait(P.DISCOVERY_INTERVAL)

    def _recv_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, (ip, _port) = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                msg = json.loads(data.decode("utf-8"))
                if msg.get("p") != P.HELLO_TAG or msg.get("v") != P.VERSION:
                    continue
                pid = msg.get("id", "")
                if not pid or pid == self.my_id:
                    continue
                with self._lock:
                    if msg.get("bye"):
                        self._peers.pop(pid, None)
                    else:
                        self._peers[pid] = Peer(
                            id=pid, name=str(msg.get("name") or ip),
                            os=str(msg.get("os") or ""), ip=ip,
                            tcp=int(msg.get("tcp") or P.TCP_PORT),
                        )
                self.on_change()
            except Exception:
                continue

    def _sweep_loop(self) -> None:
        while not self._stop.wait(1.0):
            now = time.monotonic()
            changed = False
            with self._lock:
                for pid, peer in list(self._peers.items()):
                    if not peer.manual and now - peer.last_seen > P.PEER_TTL:
                        del self._peers[pid]
                        changed = True
            if changed:
                self.on_change()

    def peers(self) -> list[Peer]:
        with self._lock:
            return sorted(self._peers.values(), key=lambda p: (p.manual, p.name))

    def ping(self, ip: str) -> None:
        """寻址：手动输入 IP 后立刻可用，同时发一次单播 hello 让对方也认识我们。"""
        ip = ip.strip()
        if not ip:
            return
        pid = "manual:" + ip
        with self._lock:
            self._peers[pid] = Peer(
                id=pid, name=ip, os="", ip=ip, tcp=P.TCP_PORT, manual=True
            )
        self._announce(self.hello, [ip])
        self.on_log(f"已手动添加对端 {ip}")
        self.on_change()

    def remove_manual(self, ip: str) -> None:
        with self._lock:
            self._peers.pop("manual:" + ip, None)
        self.on_change()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._announce(self.bye)
        except Exception:
            pass
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
