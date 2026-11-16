"""手工构建 FlashDrop.apk，只用 tools/ 内的 JDK 与 Android SDK，不引入 Gradle。

流程：aapt2 compile/link -> javac -> jar -> d8 -> 注入 classes.dex
      -> zipalign -> keytool 自签 -> apksigner 签名/校验
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TOOLS = ROOT / "tools"
JDK = TOOLS / "jdk"
SDK = TOOLS / "android-sdk"
BT = SDK / "build-tools" / "36.1.0"
ANDROID_JAR = SDK / "platforms" / "android-36" / "android.jar"
BUILD = HERE / "build"
OUT = ROOT / "FlashDrop.apk"

JAVA = JDK / "bin" / "java.exe"
JAVAC = JDK / "bin" / "javac.exe"
JAR = JDK / "bin" / "jar.exe"
KEYTOOL = JDK / "bin" / "keytool.exe"
AAPT2 = BT / "aapt2.exe"
ZIPALIGN = BT / "zipalign.exe"
D8_JAR = BT / "lib" / "d8.jar"
APKSIGNER_JAR = BT / "lib" / "apksigner.jar"


def run(args: list[str], label: str) -> None:
    print(f"\n>>> {label}", flush=True)
    cmd = [str(a) for a in args]
    print("    " + " ".join(cmd[:4]) + (" ..." if len(cmd) > 4 else ""), flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.stdout.strip():
        print(p.stdout.strip()[-4000:], flush=True)
    if p.returncode != 0:
        print((p.stderr or "").strip()[-6000:], file=sys.stderr, flush=True)
        raise SystemExit(f"[FAIL] {label} (exit {p.returncode})")
    if p.stderr.strip() and ("warning" in p.stderr.lower() or "note:" in p.stderr.lower()):
        print(p.stderr.strip()[-2000:], flush=True)


def check() -> None:
    missing = [p.name for p in (JAVA, JAVAC, JAR, KEYTOOL, AAPT2, ZIPALIGN,
                                D8_JAR, APKSIGNER_JAR, ANDROID_JAR) if not p.exists()]
    if missing:
        raise SystemExit("缺少构建工具：" + ", ".join(missing) + "\n请先运行 tools/ 的安装脚本。")


def main() -> None:
    check()
    if BUILD.exists():
        shutil.rmtree(BUILD)
    for sub in ("gen", "classes", "dex"):
        (BUILD / sub).mkdir(parents=True, exist_ok=True)

    flat = BUILD / "compiled.zip"
    base = BUILD / "base.apk"
    aligned = BUILD / "aligned.apk"
    # keystore 必须持久保留：每次新建会导致已安装版本签名不匹配，无法覆盖升级
    keystore = HERE / "flashdrop.keystore"

    run([AAPT2, "compile", "--dir", HERE / "res", "-o", flat], "1/9 aapt2 compile")

    run([AAPT2, "link", "-o", base, "-I", ANDROID_JAR,
         "--manifest", HERE / "AndroidManifest.xml",
         "-R", flat, "--java", BUILD / "gen", "--auto-add-overlay",
         "--min-sdk-version", "29", "--target-sdk-version", "36",
         "--version-code", "5", "--version-name", "1.0.1"], "2/9 aapt2 link")

    java_files = sorted(str(p) for p in (HERE / "src").rglob("*.java"))
    gen_files = sorted(str(p) for p in (BUILD / "gen").rglob("*.java"))
    run([JAVAC, "--release", "11", "-encoding", "UTF-8",
         "-cp", ANDROID_JAR, "-d", BUILD / "classes", *java_files, *gen_files],
        "3/9 javac")

    classes_jar = BUILD / "classes.jar"
    run([JAR, "cf", classes_jar, "-C", BUILD / "classes", "."], "4/9 jar")
    run([JAVA, "-Xmx1g", "-cp", D8_JAR, "com.android.tools.r8.D8",
         "--lib", ANDROID_JAR, "--min-api", "29",
         "--output", BUILD / "dex", classes_jar], "5/9 d8")

    dex = BUILD / "dex" / "classes.dex"
    if not dex.exists():
        raise SystemExit("d8 没有生成 classes.dex")
    with zipfile.ZipFile(base, "a", zipfile.ZIP_DEFLATED) as z:
        z.write(dex, "classes.dex")
    print("    注入 classes.dex OK", flush=True)
    run([ZIPALIGN, "-f", "-p", "4", base, aligned], "6/9 zipalign")

    if not keystore.exists():
        run([KEYTOOL, "-genkeypair", "-v",
             "-keystore", keystore, "-alias", "flashdrop",
             "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
             "-storepass", "android", "-keypass", "android",
             "-dname", "CN=FlashDrop, OU=SelfUse, O=FlashDrop, L=Home, S=Home, C=CN"],
            "7/9 keytool")
    else:
        print("\n>>> 7/9 keytool 复用已有签名，跳过")

    if OUT.exists():
        OUT.unlink()
    run([JAVA, "-jar", APKSIGNER_JAR, "sign",
         "--ks", keystore, "--ks-pass", "pass:android",
         "--key-pass", "pass:android",
         "--v1-signing-enabled", "true",
         "--v2-signing-enabled", "true",
         "--v3-signing-enabled", "true",
         "--out", OUT, aligned], "8/9 apksigner sign")
    run([JAVA, "-jar", APKSIGNER_JAR, "verify", "--verbose", OUT], "9/9 apksigner verify")

    print(f"\nOK -> {OUT}  ({OUT.stat().st_size / 1024 / 1024:.2f} MB)", flush=True)


if __name__ == "__main__":
    main()
