# H7-TOOL MCP 辅助开发工具

这个项目提供一个本地 MCP 服务器，用来把 H7-TOOL 接入支持 MCP 的 AI 工具。启用之后，AI 可以调用 H7-TOOL 相关工具，查看连接状态、搜索本地芯片库、识别目标板、读取调试诊断信息。

公开文档只说明安装和使用方式，不展开产品内部通信细节。

## 支持功能

- 列出可用的 H7-TOOL USB 接口和本地桥接配置。
- 读取 H7-TOOL 状态和健康信息。
- 按厂商、系列、芯片名搜索本地 H7-TOOL 设备 Lua 库。
- 搜索 H7-TOOL 自带 Lua 示例和总线辅助脚本，辅助 AI 查找原始外设用法。
- 提供 AI 编写 H7-TOOL Lua 辅助脚本的公开规则和安全边界。
- 提供离线 Lua 草稿工作区：创建、列出、读取和校验草稿，但不执行脚本。
- 提供危险动作门禁策略，供后续烧录、擦除、解锁、改保护等动作统一使用。
- 解析芯片 profile 中的接口类型、期望 ID、UID 位置、存储器范围、依赖库和算法条目。
- 汇总 profile 能力，方便 AI 理解当前芯片配置大致支持哪些操作。
- 探测已连接的 STM32H7 目标板，并与选定的本地 profile 合并成目标信息。
- 读取受限长度的目标内存数据，用于诊断。
- 根据选定 profile 读取 Option Byte 数值。
- 在 profile 提供规则时汇总保护状态。
- 通过 H7-TOOL 串口通道收发短数据，适合做串口回环、AT 指令、简单串口调试。
- 通过 H7-TOOL CAN/CAN-FD 发送受限长度帧，适合让 AI 辅助构造和复现实验报文。
- 通过 H7-TOOL I2C 扫描地址，或执行一次受限的写/读事务。
- 通过 H7-TOOL SPI 执行一次带片选的受限写/读事务，例如读取外设 ID。
- 尝试读取目标固件中的 SEGGER RTT up-buffer，用于固件日志诊断。

## 目录应该放在哪里

推荐目录结构：

```text
h7toolPC_release/
  EMMC/
    H7-TOOL/
      Programmer/
        Device/
  mcp/
    h7tool_mcp.py
    README.md
    requirements.txt
    config.json
```

也就是说，把本仓库放到 H7-TOOL PC 软件包根目录下面，目录名建议叫 `mcp`，并且与 `EMMC` 同级。

示例：

```powershell
cd D:\Tools\h7toolPC_release
git clone https://github.com/zhe0523/h7tools-mcp.git mcp
```

这样 MCP 服务器可以自动找到 H7-TOOL 自带的设备库。

## 安装

需要 Python 3.11 或更新版本。

```powershell
cd D:\Tools\h7toolPC_release\mcp
python -m pip install -r requirements.txt
python h7tool_mcp.py --self-test
```

如果输出 `Self-test passed`，说明 Python 侧运行正常。

## 配置 H7-TOOL 连接

从示例文件创建本地 `config.json`。当前常用方式是 USB HID：

```powershell
copy config.usb-hid.example.json config.json
python h7tool_mcp.py --list-hid-devices
```

如果发现多个匹配的 H7-TOOL 接口，把正确设备的 `serial_number` 填入 `config.json`。

常用本地检查命令：

```powershell
python h7tool_mcp.py --device-vendors
python h7tool_mcp.py --device-search STM32H743 --device-vendor ST
python h7tool_mcp.py --lua-example-search BH1750 --lua-example-interface i2c
python h7tool_mcp.py --lua-authoring-rules
python h7tool_mcp.py --lua-draft-list
python h7tool_mcp.py --dangerous-action-policy
python h7tool_mcp.py --device-profile ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --lua-health
python h7tool_mcp.py --target-identity ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --target-summary ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --target-flash-info ST/STM32H7xx/STM32H7x_2M.lua
```

`config.json` 是本机配置文件，已经被 git 忽略，不需要提交。

危险动作默认关闭。后续烧录、擦除、解锁、改保护、供电控制、执行自定义 Lua 等功能接入时，会先检查 `config.json` 中的 `dangerous_actions`，并要求每次请求提供匹配的确认短语。

## 启动 MCP 服务器

这个 MCP 服务器使用 stdio 通信。通常不需要手动长期启动它，而是由 AI 客户端自动拉起。

Windows 下推荐让 AI 客户端启动这个脚本：

```text
D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
```

把路径换成你本机仓库里的 `h7tool_mcp.cmd` 绝对路径。这个脚本会自动调用合适的 Python 命令，能减少客户端对参数拆分、中文路径、空格路径的兼容问题。

如果只是想在命令行测试，可以查看帮助：

```powershell
python h7tool_mcp.py --help
```

不带任何参数运行时，程序会等待 MCP 客户端通过 stdin/stdout 发送 JSON-RPC 消息，这正是 MCP 客户端需要的启动方式。

## AI 工具怎么连接

连接思路只有一句话：把本仓库里的 `h7tool_mcp.cmd` 配置成一个本地 stdio MCP 服务器。

### 连接前检查

先在命令行确认服务器能正常运行：

```powershell
cd D:\Tools\h7toolPC_release\mcp
.\h7tool_mcp.cmd --self-test
.\h7tool_mcp.cmd --lua-health
```

再确认目标板或外设相关功能能在命令行运行。例如：

```powershell
.\h7tool_mcp.cmd --target-summary ST/STM32H7xx/STM32H7x_2M.lua --include-protection-status
.\h7tool_mcp.cmd --uart-transact --uart-channel 1 --uart-baud 115200 --uart-send-hex "48 37 0D 0A" --uart-rx-length 64
.\h7tool_mcp.cmd --i2c-transact --i2c-clock 100000 --i2c-scan
.\h7tool_mcp.cmd --spi-transact --spi-freq-id 0 --spi-cs 0 --spi-write-hex "9F" --spi-read-length 3
```

命令行能跑通后，再接入 AI 客户端会更容易定位问题。

### 通用配置

大多数 AI 客户端都需要三个信息：

- 名称：`h7tool`
- 类型：`stdio` 或“标准输入/输出”
- 命令：`D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd`
- 参数：留空

路径必须换成你本机的绝对路径。如果客户端不支持直接运行 `.cmd`，就使用：

```text
命令: cmd
参数: /c D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
```

### Codex / ChatGPT 桌面端 / Codex IDE

可以在 Codex 的 MCP 设置里添加 stdio server，也可以编辑 `~/.codex/config.toml`：

```toml
[mcp_servers.h7tool]
command = 'D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd'
args = []
enabled = true
startup_timeout_sec = 20
tool_timeout_sec = 60
```

也可以用 Codex CLI 添加：

```powershell
codex mcp add h7tool -- D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
codex mcp list
```

配置完成后重启或刷新客户端。进入对话后，可以让 AI 调用 `bridge_status` 检查是否连接成功。

### Cherry Studio

在 `设置 -> MCP 服务器 -> 添加服务器` 中配置：

```text
类型: 标准输入/输出 stdio
名称: h7tool
命令: D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
参数: 留空
```

启用后，用提示词“使用 h7tool MCP 调用 bridge_status”测试。详细步骤见：[Cherry Studio 配置 H7-TOOL MCP 教程](docs/cherry-studio.zh-CN.md)。

### Claude Code / Claude Desktop / opencode

这些客户端也按“本地 stdio MCP”配置。推荐直接看单独教程：[AI 客户端接入 H7-TOOL MCP 指南](docs/ai-clients.zh-CN.md)。

AI 编写 Lua 辅助脚本的规则见：[AI 编写 H7-TOOL Lua 辅助脚本规则](docs/lua-authoring-rules.zh-CN.md)。

## 怎么让 AI 调用

连接成功后，直接让 AI 使用 h7tool MCP 工具即可。示例：

```text
使用 h7tool MCP 服务器列出可用的 H7-TOOL 接口。
```

```text
使用 h7tool 搜索本地芯片库里的 STM32H743。
```

```text
使用 h7tool lua_example_search 搜索 H7-TOOL 自带的 I2C BH1750 示例，并总结它的调用方式。
```

```text
使用 h7tool lua_authoring_rules 获取 AI 编写 H7-TOOL Lua 辅助脚本时必须遵守的规则。
```

```text
使用 h7tool lua_draft_create 生成一个读取 I2C 寄存器的 Lua 草稿，然后用 lua_draft_validate 检查它，但不要执行。
```

```text
使用 h7tool dangerous_action_policy 查看当前是否允许烧录、擦除、解锁、改保护等危险动作。
```

```text
使用 h7tool target_identity，profile 选择 ST/STM32H7xx/STM32H7x_2M.lua，然后总结当前目标板信息。
```

```text
使用 h7tool target_summary，profile 选择 ST/STM32H7xx/STM32H7x_2M.lua，然后建议下一步诊断操作。
```

```text
使用 h7tool protection_status 读取并解释当前 STM32H7 profile 的保护状态。
```

```text
使用 h7tool uart_transact，在串口 1 上用 115200 8N1 发送十六进制 48 37 0D 0A，并读取最多 64 字节响应。
```

```text
使用 h7tool can_transact，用 500K 波特率发送标准帧 ID 0x321，数据为 01 02 03 04。
```

```text
使用 h7tool i2c_transact，以 100K 时钟扫描 I2C 设备地址。
```

```text
使用 h7tool spi_transact，freq_id 0、phase 0、polarity 0、CS0，发送 9F 并读取 3 字节。
```

```text
使用 h7tool rtt_read，尝试读取目标固件 RTT channel 0 的日志。
```

推荐流程：

1. 先让 AI 调用 `bridge_status`。
2. 再让 AI 搜索或检查目标芯片 profile。
3. 然后调用 `lua_health` 或 `health_summary`。
4. 再调用 `target_summary`。
5. 目标 profile 确认后，再让 AI 做更具体的内存、Option Byte、RTT 或外设事务。

## 可用 MCP 工具

- `bridge_status`
- `device_vendors`
- `device_search`
- `lua_example_search`
- `lua_authoring_rules`
- `lua_draft_create`
- `lua_draft_list`
- `lua_draft_read`
- `lua_draft_validate`
- `dangerous_action_policy`
- `dangerous_action_explain`
- `device_profile`
- `device_capabilities`
- `tool_status`
- `health_summary`
- `lua_health`
- `target_probe`
- `target_identity`
- `target_summary`
- `target_flash_info`
- `tool_registers`
- `read_option_bytes`
- `protection_status`
- `uart_transact`
- `can_transact`
- `i2c_transact`
- `spi_transact`
- `rtt_read`
- `log_tail`
- `read_memory`

## 说明

H7-TOOL 设备库里的 Lua 脚本经常描述一整个芯片系列，而不是单个精确型号。例如搜索 `STM32H743` 可能会返回通用 STM32H7 profile。需要精确判断型号时，建议结合实机探测结果、profile 元数据和芯片特定寄存器一起判断。

同一时间最好只让一个程序控制同一个 H7-TOOL 操作通道。如果 AI 调用超时或结果异常，先关闭 PC 工具中可能冲突的操作，再重新尝试。
