# H7-TOOL 只读诊断 MCP 服务器

这是一个面向 H7-TOOL 的只读 MCP 服务器，当前定位是**诊断、识别、读取状态**，不是烧录器自动化控制器。

项目已经在 H7-TOOL V2.33、USB HID Communication 接口和 STM32H7 目标板上做过实机验证。当前所有已经暴露的硬件能力都保持只读：不擦除、不烧录、不复位、不控制电源、不写 GPIO、不修改读写保护。

## 当前能力

### H7-TOOL 本体诊断

- `bridge_status`
  - 查看 MCP 服务器配置、本地串口、H7-TOOL HID 接口。
  - 不接触硬件数据通道。
- `tool_status`
  - 读取 H7-TOOL 本体状态。
  - HID / UDP / TCP Modbus 路径只使用功能码 `0x03` 读保持寄存器。
- `health_summary`
  - 对 H7-TOOL 自身电源、电压、版本等做保守健康摘要。
- `tool_registers`
  - 有界读取 H7-TOOL 保持寄存器。

### HID Lua 只读通道

H7-TOOL 很多功能本质上通过 Lua 脚本实现。当前 MCP 已验证 V2.33 的 HID Lua 执行路径：

- HID function `0x64`：下载并执行 Lua。
- HID function `0x61`：轮询 Lua `print()` 输出。
- HID payload：1024 字节。
- MCP 只运行内置固定脚本或由 Python 生成的安全只读模板，不接受用户提供的任意 Lua。

已实现：

- `lua_health`
  - 运行 `diagnostics/tool_health.lua`，读取 H7-TOOL 本体信息、时钟、运行时间。
- `target_probe`
  - 运行 `diagnostics/target_probe_stm32h7.lua`。
  - 读取 STM32H7 目标的 IDCODE 和 UID。
- `target_identity`
  - 把实机探测结果和本地 H7-TOOL 芯片 Lua 元数据合并成目标画像。
- `read_memory`
  - 生成只读 Lua 模板，调用 `pg_read_mem(address, length)`。
  - 默认最大 1024 字节。
- `read_option_bytes`
  - 从本地芯片 Lua 的 `OB_ADDRESS` 解析 Option Byte 地址。
  - 对每个地址执行 `pg_read_mem(addr, 1)`。
  - 不调用 Option Byte 编程、解保护、擦除、复位或电源控制 API。

### 本地芯片库索引

H7-TOOL 的 `EMMC/H7-TOOL/Programmer/Device` 目录中有大量芯片 Lua 和 FLM 算法文件。当前项目可以把这些本地文件变成可查询的 MCP 能力：

- `device_vendors`
  - 列出支持的厂商和 Lua 数量。
- `device_search`
  - 按关键字搜索芯片脚本。
  - 默认跳过公共 `Lib` 脚本。
  - 支持通配弱匹配，例如搜索 `STM32H743` 可以找到 `ST/STM32H7xx/STM32H7x_2M.lua`。
- `device_profile`
  - 解析单个芯片 Lua 的元数据：
  - 厂商、系列、设备名、接口类型、期望 IDCODE、UID 地址/长度、Flash/RAM 地址、IncludeList、FLM 算法文件。
- `device_capabilities`
  - 扫描芯片 Lua 和 IncludeList 公共库。
  - 分别列出推断出的只读能力和危险能力。
  - 危险能力只做报告，不暴露为可调用动作。

## 已验证硬件

当前实机环境：

- H7-TOOL PC 软件：V2.3.3
- H7-TOOL 固件：V2.33
- USB HID：VID `0xC251`，PID `0xF00A`
- 使用接口：`H7-TOOL HID Communication`，interface `2`
- 目标板：STM32H7 系列，当前 profile 为 `ST/STM32H7xx/STM32H7x_2M.lua`

实机读到的目标信息：

```text
IDCODE = 0x6BA02477
UID Address = 0x1FF1E800
UID Length = 12
UID = 3C 00 1E 00 16 51 33 30 33 34 38 33
```

实机读到的 STM32H7 Option Bytes，32 字节：

```text
F0 AA C6 1B FF 00 00 00 FF 00 00 00 FF 00 00 00
00 08 F0 1F FF 00 00 00 FF 00 00 00 FF 00 00 00
```

## 快速开始

推荐使用 Codex 运行时自带 Python：

```powershell
$py = 'C:\Users\zhe\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
```

安装依赖：

```powershell
& $py -m pip install -r .\requirements.txt
```

自测：

```powershell
& $py .\h7tool_mcp.py --self-test
```

列出 HID 设备：

```powershell
& $py .\h7tool_mcp.py --list-hid-devices
```

使用 USB HID 配置：

```powershell
Copy-Item .\config.usb-hid.example.json .\config.json -Force
```

运行常用诊断：

```powershell
& $py .\h7tool_mcp.py --probe-h7tool
& $py .\h7tool_mcp.py --health-summary
& $py .\h7tool_mcp.py --lua-health
& $py .\h7tool_mcp.py --target-identity ST/STM32H7xx/STM32H7x_2M.lua
& $py .\h7tool_mcp.py --read-memory 0x1FF1E800 12
& $py .\h7tool_mcp.py --read-option-bytes ST/STM32H7xx/STM32H7x_2M.lua
```

索引本地芯片库：

```powershell
& $py .\h7tool_mcp.py --device-vendors
& $py .\h7tool_mcp.py --device-search STM32H743 --device-vendor ST
& $py .\h7tool_mcp.py --device-profile ST/STM32H7xx/STM32H7x_2M.lua
& $py .\h7tool_mcp.py --device-capabilities ST/STM32H7xx/STM32H7x_2M.lua
```

## MCP 客户端配置示例

按你的实际路径调整：

```json
{
  "mcpServers": {
    "h7tool": {
      "command": "C:\\Users\\zhe\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe",
      "args": ["E:\\软件\\绿色软件\\h7toolPC_release\\mcp\\h7tool_mcp.py"]
    }
  }
}
```

## 安全边界

当前 MCP 明确不暴露以下动作：

- 擦除 Flash
- 烧录 Flash
- 写 Option Bytes
- 使能/解除读保护或写保护
- 复位目标板
- 控制 TVCC/电源
- 写 GPIO
- 执行用户传入的任意 Lua

`device_capabilities` 会报告芯片 Lua 中存在的危险能力，例如 `pg_write32`、`pg_erase_*`、`MCU_ProgOptionBytes`、`MCU_RemoveProtect`，但这些只是用于提示和规划，不会变成 MCP 可调用工具。

## 配置文件

`config.json` 是本地文件，不应提交到版本控制。示例文件包括：

- `config.usb-hid.example.json`
- `config.modbus-udp.example.json`
- `config.modbus-tcp.example.json`
- `config.usb-lua.example.json`

当前最完整、验证最多的是 `h7tool_hid` 路径。

## 开发和验证流程

每次新增硬件能力时建议遵循：

1. 先读 H7-TOOL 自带 Lua 或说明文档。
2. 只实现最小只读路径。
3. Python 层严格校验参数。
4. Lua 层使用固定脚本或安全模板。
5. 真机验证。
6. 跑 `py_compile` 和 `--self-test`。
7. 每完成并验证一项功能后提交一次 git。

## 下一步建议

比较适合继续做的功能：

- `protection_status`
  - 基于 `OB_WRP_ADDRESS`、`OB_WRP_MASK`、`OB_WRP_VALUE` 判断保护状态。
- `flash_size`
  - 读取芯片容量寄存器或根据 profile/FLM 信息辅助判断具体型号。
- 更通用的 `target_probe`
  - 根据选中的 device profile 自动生成 UID/IDCODE 读取脚本，而不是只针对 STM32H7。
- RTT 只读日志
  - 在确认协议后实现 `rtt_tail` / `rtt_snapshot`。
