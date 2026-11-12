"""投递引擎：TCP 服务端(接收) + 客户端(发送)。

一次投递 = 一条 TCP 连接：
    MAGIC(4) | 头长(4) | 头(JSON) | [数据(size) | CRC32(4)] * N  -> 接收端
    状态(1) | 消息长(4) | 消息(UTF-8)                            <- 接收端
"""
from __future__ import annotations

import os
import posixpath
import socket
import threading
from pathlib import Path

from . import inbox as IB
from . import protocol as P


def prepare_files(paths: list[str]) -> tuple[dict, list[str]]:
    """把用户选择的文件/文件夹展开成 header 条目 + 对应的本地源路径。"""
    entries: list[dict] = []
    sources: list[str] = []
    for raw in paths:
        p = Path(raw)
        if p.is_symlink() or not p.exists():
            continue
        if p.is_dir():
            base = p.name
            entries.append({"rel": base, "size": 0, "dir": True})
            sources.append("")
            for root, dirs, files in os.walk(p, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not (Path(root) / d).is_symlink())
                files.sort()
                relroot = Path(root).relative_to(p)
                prefix = posixpath.join(base, *relroot.parts) if relroot.parts else base
                for d in dirs:
                    entries.append({"rel": posixpath.join(prefix, d), "size": 0, "dir": True})
                    sources.append("")
                for f in files:
                    fp = Path(root) / f
                    if fp.is_symlink() or not fp.is_file():
                        continue
                    entries.append({
                        "rel": posixpath.join(prefix, f),
                        "size": fp.stat().st_size, "dir": False,
                    })
                    sources.append(str(fp))
        elif p.is_file():
            entries.append({"rel": p.name, "size": p.stat().st_size, "dir": False})
            sources.append(str(p))
    total = sum(e["size"] for e in entries)
    return {"kind": "files", "entries": entries, "total": total}, sources


class Engine:
    def __init__(self, my_name: str, get_inbox, callbacks: dict):
        self.my_name = my_name
        self.get_inbox = get_inbox
        self.cb = callbacks
        self._srv: socket.socket | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()   # 同一时刻只允许一个发出中的投递

    # ---------- 日志 ----------
    def _log(self, msg: str) -> None:
        self.cb.get("on_log", lambda _m: None)(msg)

    # ---------- 接收 ----------
    def start(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("", P.TCP_PORT))
        except OSError as e:
            s.close()
            raise RuntimeError(f"无法监听 TCP {P.TCP_PORT}：{e}") from e
        s.listen(8)
        s.settimeout(1.0)
        self._srv = s
        threading.Thread(target=self._accept_loop, daemon=True, name="fd-tcp-accept").start()

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(
                target=self._handle, args=(conn, addr), daemon=True, name="fd-tcp-recv"
            ).start()

    def _handle(self, conn: socket.socket, addr) -> None:
        try:
            conn.settimeout(P.SOCKET_TIMEOUT)
            if P.read_exact(conn, 4) != P.MAGIC:
                raise ValueError("协议标识不匹配")
            hlen = P.from_u32(P.read_exact(conn, 4))
            if hlen > P.MAX_HEADER:
                raise ValueError("投递头过大")
            header = P.decode_header(P.read_exact(conn, hlen))
            if header.get("v") != P.VERSION:
                raise ValueError(f"协议版本不匹配: {header.get('v')}")
            sender = str(header.get("from") or addr[0])

            if header.get("kind") == "text":
                text = str(header.get("text") or "")
                self.cb.get("on_received_text", lambda *a: None)(text, sender)
                self._ack(conn, True, "文字已送达")
                self._log(f"收到来自 {sender} 的文字（{len(text)} 字）")
            elif header.get("kind") == "files":
                count, targets = self._receive_files(conn, header)
                self.cb.get("on_received_files", lambda *a: None)(count, targets, sender)
                self._ack(conn, True, f"已接收 {count} 项")
                self._log(f"收到来自 {sender} 的 {count} 项文件")
            else:
                raise ValueError("未知的投递类型")
        except Exception as e:
            try:
                self._ack(conn, False, str(e))
            except Exception:
                pass
            self._log(f"接收失败：{e}")
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _receive_files(self, conn, header) -> tuple[int, list[Path]]:
        entries = header.get("entries") or []
        # 先整体校验 + 规划，避免写到一半才发现路径非法
        plan = IB.plan(self.get_inbox(), entries)
        targets = [plan[e["rel"]] for e in entries]
        written: list[Path] = []
        for entry, target in zip(entries, targets):
            size = int(entry.get("size") or 0)
            is_dir = bool(entry.get("dir"))
            IB.ensure_parent(target)
            if is_dir:
                target.mkdir(parents=True, exist_ok=True)
                P.read_exact(conn, 4)
                continue
            crc = 0
            with open(target, "wb") as f:
                left = size
                while left > 0:
                    chunk = conn.recv(min(P.CHUNK, left))
                    if not chunk:
                        raise ConnectionError("文件数据不完整")
                    f.write(chunk)
                    crc = P.crc32(chunk, crc)
                    left -= len(chunk)
            expected = P.from_u32(P.read_exact(conn, 4))
            if crc != expected:
                try:
                    target.unlink()
                except OSError:
                    pass
                raise ValueError(f"校验失败，已丢弃：{entry['rel']}")
            written.append(target)
        return len(entries), [t for t in written if t.is_file()][:5]

    @staticmethod
    def _ack(conn, ok: bool, msg: str) -> None:
        raw = msg.encode("utf-8")
        conn.sendall(bytes([1 if ok else 0]) + P.u32(len(raw)) + raw)

    # ---------- 发送 ----------
    def _connect(self, ip: str, port: int) -> socket.socket:
        s = socket.create_connection((ip, port), timeout=8)
        s.settimeout(P.SOCKET_TIMEOUT)
        return s

    def send_text(self, text: str, ip: str, port: int = P.TCP_PORT) -> tuple[bool, str]:
        if not text:
            return False, "文字是空的"
        if len(text.encode("utf-8")) > P.MAX_TEXT:
            return False, "文字超过 1MB 上限"
        with self._lock:
            return self._send({"kind": "text", "text": text}, [], ip, port)

    def send_files(self, paths: list[str], ip: str,
                   port: int = P.TCP_PORT) -> tuple[bool, str]:
        header, sources = prepare_files(paths)
        if not header["entries"]:
            return False, "没有可发送的文件"
        with self._lock:
            return self._send(header, sources, ip, port)

    def _send(self, header: dict, sources: list[str], ip: str,
              port: int) -> tuple[bool, str]:
        header = dict(header)
        header.update({"v": P.VERSION, "from": self.my_name})
        on_progress = self.cb.get("on_progress", lambda *_a: None)
        total = int(header.get("total") or 0)
        try:
            s = self._connect(ip, port)
            with s:
                raw = P.encode_header(header)
                s.sendall(P.MAGIC + P.u32(len(raw)) + raw)
                done = 0
                for entry, src in zip(header.get("entries") or [], sources):
                    if entry.get("dir"):
                        s.sendall(P.u32(0))
                        continue
                    crc = 0
                    with open(src, "rb") as f:
                        while True:
                            chunk = f.read(P.CHUNK)
                            if not chunk:
                                break
                            s.sendall(chunk)
                            crc = P.crc32(chunk, crc)
                            done += len(chunk)
                            on_progress(done, total)
                    s.sendall(P.u32(crc))
                status = P.read_exact(s, 1)[0]
                mlen = P.from_u32(P.read_exact(s, 4))
                msg = P.read_exact(s, mlen).decode("utf-8", "replace")
                return status == 1, msg
        except Exception as e:
            return False, str(e)

    def stop(self) -> None:
        self._stop.set()
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass
            self._srv = None
