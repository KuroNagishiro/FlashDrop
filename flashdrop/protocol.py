"""FlashDrop 线协议常量与编解码。

桌面端(Python)与 Android 端(Java)共享同一份协议，见 docs/PROTOCOL.md。
故意不使用 HTTP：原生 TCP socket 可绕开移动端对明文 HTTP 的默认限制，
也不需要自签证书与证书信任配置。
"""
from __future__ import annotations

import json
import struct
import zlib

MAGIC = b"FD01"
HELLO_TAG = "flashdrop"
VERSION = 1

UDP_PORT = 47831          # 发现：UDP 子网广播
TCP_PORT = 47832          # 投递：TCP 长连接
DISCOVERY_INTERVAL = 2.0  # 广播间隔(秒)
PEER_TTL = 7.0            # 超过该时间未收到 hello 即视为离线
CHUNK = 64 * 1024
SOCKET_TIMEOUT = 120.0
MAX_HEADER = 4 * 1024 * 1024
MAX_TEXT = 1024 * 1024


def u32(n: int) -> bytes:
    return struct.pack(">I", n & 0xFFFFFFFF)


def from_u32(b: bytes) -> int:
    return struct.unpack(">I", b)[0]


def encode_header(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode_header(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))


def crc32(data: bytes, prev: int = 0) -> int:
    return zlib.crc32(data, prev) & 0xFFFFFFFF


def read_exact(sock, n: int) -> bytes:
    """读满 n 字节，连接提前关闭时抛 ConnectionError。"""
    buf = bytearray()
    while len(buf) < n:
        part = sock.recv(min(CHUNK, n - len(buf)))
        if not part:
            raise ConnectionError("对端提前断开了连接")
        buf.extend(part)
    return bytes(buf)
