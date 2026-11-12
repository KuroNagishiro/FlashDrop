# 全部工具链自包含在项目目录内

桌面端用 uv 在项目内安装私有 Python 3.13 并创建 `.venv`，桌面端运行时零第三方依赖（tkinter 属标准库）；Android 端的 JDK 17 与 Android SDK 放在 `tools/`，构建脚本只引用项目内路径。不改系统 PATH、不写注册表、不装全局包、不加开机自启、不添加防火墙规则，uv 缓存也重定向到 `tools/uv-cache`。

**Considered Options**

- 使用系统 Python / 全局 Android SDK：省一次下载，但会在机器上留下难以清理的全局状态，且 `uv`/SDK 版本漂移会让构建不可复现。
- Flutter 单代码库：两端 UI 一致，但与「桌面端用 uv + Python」的明确要求冲突。

**Consequences**

- `tools/` 体积较大（约 1GB），属于预期成本；删除它不影响源码，重跑安装脚本即可恢复。
- Windows 收件目录固定为程序根目录下的 `downloads/`，配置写在根目录 `config.json`，整个程序可以直接拷走或整个删掉。
- APK 用 `aapt2` / `javac` / `d8` / `apksigner` 手工构建，不引入 Gradle，避免再拉一套构建依赖。
