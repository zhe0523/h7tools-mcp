# H7-TOOL V2.33 未公开固件接口

> 这不是厂商公开 ABI。结论来自 V2.33 实机、官方上位机行为和公开 V1.49
> 旧源码；升级固件后应重新验证。本文只记录能够明确界定用途和风险的入口。

## HID 封装

- VID/PID：`C251:F00A`，通信接口通常为 interface 2；
- hidapi 写 1025 字节：首字节 report ID 0，随后是至多 1024 字节 payload；
- payload 是 Modbus-RTU 风格帧，数值大端，CRC-16/MODBUS 在线上低字节在前；
- 读取时必须按功能码和长度计算有效帧，不能把尾部 `00`/`FF` 填充算进 CRC；
- 同一接口同一时间只保留一个在途请求，并过滤不匹配的 unit、功能码、子功能和偏移。

## 私有功能码

| 功能码 | 作用 | MCP 状态 |
| ---: | --- | --- |
| `0x61` | Lua/RTT/UART/CAN 多路流 | 已用于脚本输出和总线工具 |
| `0x64` | Lua 下载/执行及文件管理 | 已接入 |
| `0x65` | 旧版临时 Lua 执行 | 源码标为废弃，不接入 |
| `0x66` | 目标内存、脱机配置、LCD 显存 | 只接入只读子功能 |
| `0x70` | PC 消息/虚拟按键预留 | 旧源码为空壳，不接入 |

## `0x64` 文件子功能

通用请求为：

```text
unit | 64 | subfunction:u16be | total:u32be | offset:u32be |
package_len:u32be | payload | crc16le
```

| 子功能 | 作用 | 对应工具 |
| ---: | --- | --- |
| `0` | 重置 Lua VM 后运行 | Lua 工具内部使用 |
| `1` | 不重置 Lua VM，继续运行 | 保留 |
| `2` | 列目录 | `device_file_list` |
| `3` | 文件大小和 MD5 | `device_file_md5` |
| `4` | 删除文件 | `device_file_delete`，`write` 门禁 |
| `5` | 删除目录 | 固件未实现，不接入 |
| `6` | 读文件 | `device_file_read` |
| `7` | 写文件 | `device_file_write`，`write` 门禁 |
| `8` | 建目录 | `device_file_mkdir`，`write` 门禁 |

文件路径是 NUL 结尾的 GBK 字节串。固件存在短文件长度下溢、跨 4 KiB 页重复一字节、
刚写完第一次读取为空等缺陷，MCP 已在实现中规避。

## `0x66` 只读子功能

请求：

```text
unit | 66 | subfunction:u16be | address_or_offset:u32be |
length:u32be | crc16le
```

读响应：

```text
unit | 66 | subfunction:u16be | address_or_offset:u32be |
length:u32be | status:u8 | data[length] | crc16le
```

| 子功能 | 作用 | MCP 状态 |
| ---: | --- | --- |
| `0x0000` | 初始化当前烧录器配置并读目标内存 | `read_memory(transport="native")` 首包 |
| `0x0001` | 不重新初始化，连续读目标内存 | 原生读取续包 |
| `0x0002` | 写目标内存 | 不开放 |
| `0x0003` | 修改脱机烧录默认启动文件 | 不开放 |
| `0x0100` | 读 H7-TOOL LCD 显存 | `screenshot`，V2.33 已验证 |

原生目标读取仍要求先加载正确的目标/烧录器配置，且目标供电、SWD/SWIM 连线正常。
设备会用非零 `status` 报告调试读失败。单包理论最大数据 1009 字节，MCP 使用 960
字节保守分包。当前只支持单路目标；多路 SWD 会返回 `通道数 × length`，尚未纳入。

## 特殊寄存器

### `0xFF7F` 模式切换

旧源码定义 `1` APP、`2` Bootloader、`3` DAP、`4` EMMC、`5` 联机、`6` 文件管理、
`7` 脱机烧录界面、`8` 进入并烧录一次；头文件还声明 `9/10/11`，但旧处理函数未实现。
V2.33 实机另确认 `12` 为 Lua 小程序页、`13` 为官方 CAN 后端。

MCP 的 `tool_mode_switch` 只允许：

- `restart_app` = 1；
- `emmc` = 4；
- `link` = 5。

调用需要危险级别 `power` 和确认词。写入后 HID 可能立即断开，工具只发送一次，不因没有
ACK 而重试。Bootloader、DAP 和烧录模式故意不开放。

### `0xFF7E` 有限按键模拟

值的高字节为按键 ID、低字节为电平状态；旧源码只处理 S（ID 0）和 C（ID 1），并且故意
不回 ACK。它不是五键事件注入，旧源码还禁用了这两路的长按参数，因此 MCP 暂不开放。

## 只记录、不开放

- `0x0300` Lua 控制：值 1 请求运行一次，值 2 调 `init()`，旧源码标注“未用”；
- `0x0180..0x0185` RTC 写入；
- `0xBFFF` 校准开关：`0x5AA5` 初始化校准，`0xEF55` 恢复基础参数；
- `0xC000...` 校准数据；
- 任意原始 `0x06/0x10` 写寄存器。

这些入口能修改设备设置、校准、GPIO、网络或目标状态。若将来接入，必须逐项使用白名单、
参数范围和危险级别，不能暴露“万能寄存器写”。
