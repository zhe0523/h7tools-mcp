# H7-TOOL MCP 辅助开发工具

这个项目提供一个面向 H7-TOOL 的 MCP 服务器，让 AI 客户端可以辅助完成嵌入式开发中的查询、识别和诊断工作。

项目基于 H7-TOOL PC 软件包中已有的本地文件和能力构建，重点是让开发者更方便地检索芯片库、识别目标板、读取诊断信息。文档不会展开 H7-TOOL 的内部通信细节，也不会要求使用者理解底层传输过程。

## 当前功能

- 查看 H7-TOOL 连接候选和本地桥接配置。
- 读取 H7-TOOL 状态并生成简要健康摘要。
- 搜索本地 H7-TOOL 芯片库。
- 解析芯片 Lua 配置，提取接口类型、期望 ID、UID 位置、存储器范围、依赖库、算法条目等。
- 汇总芯片配置中的能力，区分常用开发诊断能力和需要谨慎处理的能力。
- 探测连接的 STM32H7 目标，并与本地芯片配置合并成目标画像。
- 读取受限范围的目标内存数据，用于诊断。
- 根据芯片配置读取 Option Byte 值。
- 在芯片配置提供规则时，汇总保护状态。

## 环境要求

- Python 3.11 或更新版本。
- H7-TOOL PC 软件包，且其 `EMMC/H7-TOOL` 目录与本项目保持相对位置。
- 如需 USB HID 或串口访问，安装 `requirements.txt` 中的依赖。

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

运行自测：

```powershell
python h7tool_mcp.py --self-test
```

## 常用命令

列出可见的 H7-TOOL USB 接口：

```powershell
python h7tool_mcp.py --list-hid-devices
```

查询本地芯片库：

```powershell
python h7tool_mcp.py --device-vendors
python h7tool_mcp.py --device-search STM32H743 --device-vendor ST
python h7tool_mcp.py --device-profile ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --device-capabilities ST/STM32H7xx/STM32H7x_2M.lua
```

配置 `config.json` 后进行目标诊断：

```powershell
python h7tool_mcp.py --probe-h7tool
python h7tool_mcp.py --health-summary
python h7tool_mcp.py --target-identity ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --read-memory 0x1FF1E800 12
python h7tool_mcp.py --read-option-bytes ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --protection-status ST/STM32H7xx/STM32H7x_2M.lua
```

## MCP 配置示例

按实际路径调整：

```json
{
  "mcpServers": {
    "h7tool": {
      "command": "python",
      "args": ["C:\\path\\to\\h7tools-mcp\\h7tool_mcp.py"]
    }
  }
}
```

## 配置文件

`config.json` 是本地配置文件，不建议提交到仓库。可以从下面的示例文件开始：

- `config.usb-hid.example.json`
- `config.modbus-udp.example.json`
- `config.modbus-tcp.example.json`
- `config.usb-lua.example.json`

## MCP 工具

- `bridge_status`
- `device_vendors`
- `device_search`
- `device_profile`
- `device_capabilities`
- `tool_status`
- `health_summary`
- `lua_health`
- `target_probe`
- `target_identity`
- `tool_registers`
- `read_option_bytes`
- `protection_status`
- `log_tail`
- `read_memory`

## 说明

H7-TOOL 芯片库中的 Lua 脚本经常描述一整个芯片系列，而不是单个精确型号。例如搜索 `STM32H743` 可能会找到通用 H7 配置。需要精确判断型号时，建议结合实机探测结果、芯片配置元数据和芯片特定寄存器一起判断。

## 后续方向

- 增强 STM32 系列的容量和具体型号识别。
- 根据更多芯片 profile 自动生成目标探测脚本。
- 对 Option Bytes 和保护状态做更友好的解释。
- 在行为边界明确后，继续探索 RTT、UART、CAN 助手相关能力。
