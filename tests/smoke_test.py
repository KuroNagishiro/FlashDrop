"""本机回环自测：不开界面验证帧协议、CRC、落盘与同名冲突。

运行：.venv\\Scripts\\python.exe tests\\smoke_test.py
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flashdrop.engine import Engine  # noqa: E402
from flashdrop import protocol as P  # noqa: E402

received: list = []
events: list[str] = []
done = threading.Event()


def inbox_path() -> Path:
    return OUT


def cb(**kw):
    events.append(kw)


def main() -> None:
    global OUT
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "src"
        src.mkdir()
        (src / "hello.txt").write_text("你好 FlashDrop\n" * 100, "utf-8")
        (src / "nested").mkdir()
        (src / "nested" / "empty").mkdir()
        (src / "nested" / "data.bin").write_bytes(bytes(range(256)) * 500)
        OUT = tmp / "inbox"
        OUT.mkdir()

        engine = Engine("测试机", inbox_path, {
            "on_log": lambda m: print("[log]", m),
            "on_received_text": lambda t, s: (events.append("text:" + t), done.set()),
            "on_received_files": lambda c, t, s: (
                events.append(f"files:{c}"), done.set()),
            "on_progress": lambda d, t: None,
        })
        engine.start()
        time.sleep(0.2)

        ok, msg = engine.send_files(
            [str(src / "hello.txt"), str(src / "nested")], "127.0.0.1")
        assert ok, f"第一次投递失败: {msg}"
        done.wait(5)
        done.clear()
        assert (OUT / "hello.txt").read_text("utf-8") == "你好 FlashDrop\n" * 100
        assert (OUT / "nested" / "data.bin").read_bytes() == bytes(range(256)) * 500
        assert (OUT / "nested" / "empty").is_dir(), "空目录未保留"
        print("[ok] 文件/文件夹/空目录落盘 + CRC 校验通过")

        ok, msg = engine.send_files([str(src / "hello.txt")], "127.0.0.1")
        assert ok, f"第二次投递失败: {msg}"
        done.wait(5)
        done.clear()
        assert (OUT / "hello (2).txt").exists(), "同名未自动加序号"
        assert (OUT / "hello.txt").read_text("utf-8") == "你好 FlashDrop\n" * 100
        print("[ok] 同名不覆盖，生成 hello (2).txt")

        ok, msg = engine.send_text("剪贴板测试 ✓", "127.0.0.1")
        assert ok, f"文字投递失败: {msg}"
        done.wait(5)
        assert any(e.startswith("text:剪贴板测试") for e in events), events
        print("[ok] 文字投递通过")

        engine.stop()
    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    main()
