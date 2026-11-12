# FlashDrop 线协议 v1

Python 桌面端与 Java Android 端必须逐字节一致。改动本协议需同步改两端并把 `VERSION` 加一。

## 常量

| 项 | 值 |
| --- | --- |
| UDP 发现端口 | 47831 |
| TCP 投递端口 | 47832 |
| 帧标识 `MAGIC` | `FD01`（4 字节 ASCII） |
| hello 间隔 / 对端过期 | 2s / 7s |
| 分块 | 65536 字节 |
| 整数 | 4 字节大端无符号 |

## 发现（UDP 广播到 255.255.255.255 与各网卡的定向广播地址）

UTF-8 JSON，单包 < 512 字节：

```json
{"p":"flashdrop","v":1,"id":"<稳定 UUID>","name":"书房PC","os":"windows","tcp":47832,"bye":false}
```

- 忽略 `p != "flashdrop"`、`v != 1`、`id` 等于自身 id 的包。
- `bye:true` 表示对端主动退出，立即从列表移除。
- 非手动发现的对端 7 秒未收到 hello 即过期。
- **寻址兜底**：手填 IP 时先在本地建立 `manual:<IP>` 条目（不参与过期），再向该 IP 单播一个 hello。手动条目不需要对方回包也能发送。

## 投递（每条 TCP 连接一次投递）

```
客户端 -> 服务端
  MAGIC(4) | HLEN(4) | HEADER(HLEN 字节 UTF-8 JSON)
  [ 数据(entry.size 字节) | CRC32(4) ] * N        // 仅 kind=files
服务端 -> 客户端
  状态(1: 1=成功 0=失败) | MLEN(4) | 消息(MLEN 字节)
```

HEADER 公共字段：`v`(1)、`kind`(files|text)、`from`(发送方显示名)。

`kind=text`：额外字段 `text`（UTF-8，上限 1MB），无条目。接收端写入系统剪贴板并提示。

`kind=files`：额外字段 `entries` 与 `total`（所有文件字节数之和）。每个条目：

```json
{"rel":"报告/第三章/a.txt","size":12345,"dir":false}
```

- `rel` 一律用 `/`，相对投递根目录；单文件就是文件名，文件夹以文件夹名开头。
- 目录条目 `size=0, dir=true`，无数据体，但仍跟一个值为 0 的 CRC32。
- CRC32 用标准 zlib/IEEE 多项式，发送端流式计算、接收端流式校验；不一致则该文件丢弃并整条投递判失败。
- 空目录照常发条目；Android 的 MediaStore 无法表示空目录，接收端跳过创建即可。

## 接收端落盘规则

1. 先对全部 `rel` 做校验：拒绝反斜杠、绝对路径、盘符、`..`、空段、NUL。
2. 规划阶段对每个**顶层名**做同名冲突处理：`报告.txt` → `报告 (2).txt`，目录 `照片` → `照片 (2)`；同一次投递内复用同一重命名结果。
3. 只允许写入收件目录：Windows 为程序根目录 `downloads/`，Android 为 `Download/FlashDrop/`（MediaStore）。绝不覆盖已有文件。
