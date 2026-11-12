# 原生 TCP + UDP 广播，不用 HTTP 也不用 mDNS

投递走原生 TCP socket 上的自定义帧，发现走自发 UDP 子网广播，两者都不依赖 HTTP 或 mDNS/DNS-SD。Windows 的 mDNS 服务发布不可靠（系统侧解析较强、发布常需 Bonjour 或用户态库），Android 17 的 NsdManager 又叠加了本地网络权限；两端都是自家 App、同一子网，一个固定端口的广播包足够。原生 socket 还顺带绕开了 Android 9+ / iOS 17+ 对明文 HTTP 的默认限制，省掉自签证书与证书信任配置。

**Considered Options**

- mDNS/DNS-SD + HTTPS：生态标准，但 Windows 端发布不稳、需要证书在各端建立信任，且 V1 的信任模型根本不做认证，加密挡不住伪造。
- HTTP + JSON 上传：实现最简单的常规选择，但移动端默认拦明文 HTTP，配置成本高于直接写 socket。

**Consequences**

- 帧格式是 Python 与 Java 之间的硬契约，任何改动必须两端同步，见 `docs/PROTOCOL.md`。
- 不加密、不认证。与 ADR-0002 一致：安全性完全由家庭私有 WiFi 边界承担。
- 组播被网络设备丢弃时会静默失败，因此必须保留手填 IP / 单播 hello 这条寻址兜底。V1 的寻址兜底**只做手填 IP**，二维码未实现：需要相机权限与扫码库，与「只放一个文本框、不用考虑太复杂」的极简目标冲突。两端界面都显示本机 IP，方便手填。
- 两端界面都直接显示本机 IP，让寻址兜底真正可用，而不是只留一个理论上的入口。
- 首次运行会被 Windows 防火墙问一次放行；项目不主动添加防火墙规则（那属于改动本机环境）。
