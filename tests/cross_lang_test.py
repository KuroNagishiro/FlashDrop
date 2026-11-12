"""跨语言联调：Python 桌面端 <-> Java(复用 Android 端 Proto) 双向投递。

运行：.venv\\Scripts\\python.exe tests\\cross_lang_test.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flashdrop.engine import Engine  # noqa: E402

JDK = ROOT / "tools" / "jdk" / "bin"
JAVAC = JDK / "javac.exe"
JAVA = JDK / "java.exe"
CP = Path(__file__).resolve().parent / "_javaclasses"


def javac() -> None:
    if CP.exists():
        shutil.rmtree(CP)
    CP.mkdir(parents=True)
    p = subprocess.run([
        str(JAVAC), "--release", "11", "-encoding", "UTF-8", "-d", str(CP),
        str(ROOT / "android" / "src" / "com" / "flashdrop" / "app" / "Proto.java"),
        str(Path(__file__).with_name("JavaPeerTest.java")),
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise SystemExit("javac 失败:\n" + p.stderr)


def java_run(mode: str, arg: str, background: bool = False):
    cmd = [str(JAVA), "-Dfile.encoding=UTF-8", "-cp", str(CP),
           "JavaPeerTest", mode, arg]
    if background:
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30)
    return (p.stdout or "") + (p.stderr or "")


def main() -> None:
    javac()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        payload = tmp / "payload.bin"
        payload.write_bytes(bytes(range(256)) * 400)
        inbox = tmp / "inbox"
        inbox.mkdir()

        # --- A. Python -> Java：文件 ---
        jdest = tmp / "javainbox"
        proc = java_run("recv", str(jdest), background=True)
        time.sleep(0.4)
        engine = Engine("PySender", lambda: inbox, {"on_log": print})
        ok, msg = engine.send_files([str(payload)], "127.0.0.1")
        out, _ = proc.communicate(timeout=25)
        assert ok, f"Python->Java 文件投递失败: {msg}\n{out}"
        assert "RECV_OK" in out, out
        assert (jdest / "from_python.bin").read_bytes() == payload.read_bytes()
        print("[ok] A Python -> Java 文件（帧/CRC）一致")

        # --- B. Python -> Java：文字 ---
        proc = java_run("recvtext", "-", background=True)
        time.sleep(0.4)
        ok, msg = engine.send_text("CrossLangText123", "127.0.0.1")
        out, _ = proc.communicate(timeout=25)
        assert ok, f"Python->Java 文字投递失败: {msg}\n{out}"
        assert "TEXT_OK=CrossLangText123" in out, out
        print("[ok] B Python -> Java 文字一致")

        # --- C/D. Java -> Python ---
        got_text = []
        engine2 = Engine("PyReceiver", lambda: inbox, {
            "on_log": print,
            "on_received_text": lambda t, s: got_text.append(t),
            "on_received_files": lambda c, t, s: None,
            "on_progress": lambda d, t: None,
        })
        engine2.start()
        time.sleep(0.3)
        out = java_run("send", str(payload))
        assert "SEND_OK status=1" in out, out
        assert (inbox / "from_java.txt").read_bytes() == payload.read_bytes()
        print("[ok] C Java -> Python 文件（帧/CRC）一致")

        out = java_run("sendtext", "JavaToPython456")
        assert "SEND_OK status=1" in out, out
        time.sleep(0.3)
        assert got_text == ["JavaToPython456"], got_text
        print("[ok] D Java -> Python 文字一致")
        engine2.stop()

    print("\nCROSS-LANGUAGE TEST PASSED")


if __name__ == "__main__":
    main()
