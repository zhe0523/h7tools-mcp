# H7-TOOL MCP 辅助开发工具

这个项目提供一个本地 MCP 服务器，用来把 H7-TOOL 接入支持 MCP 的 AI 工具。启用之后，AI 可以调用 H7-TOOL 相关工具，查看连接状态、搜索本地芯片库、识别目标板、读取调试诊断信息。

公开文档只说明安装和使用方式，不展开产品内部通信细节。

## 支持功能

- 列出可用的 H7-TOOL USB 接口和本地桥接配置。
- 读取 H7-TOOL 状态和健康信息。
- 按厂商、系列、芯片名搜索本地 H7-TOOL 设备 Lua 库。
- 解析芯片 profile 中的接口类型、期望 ID、UID 位置、存储器范围、依赖库和算法条目。
- 汇总 profile 能力，方便 AI 理解当前芯片配置大致支持哪些操作。
- 探测已连接的 STM32H7 目标板，并与选定的本地 profile 合并成目标信息。
- 读取受限长度的目标内存数据，用于诊断。
- 根据选定 profile 读取 Option Byte 数值。
- 在 profile 提供规则时汇总保护状态。

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
python h7tool_mcp.py --device-profile ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --lua-health
python h7tool_mcp.py --target-identity ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --target-summary ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --target-flash-info ST/STM32H7xx/STM32H7x_2M.lua
```

`config.json` 是本机配置文件，已经被 git 忽略，不需要提交。

## 启动 MCP 服务器

这个 MCP 服务器使用 stdio 通信。通常不需要手动长期启动它，而是由 AI 客户端按下面的命令自动拉起：

```powershell
python D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py
```

如果只是想在命令行测试，可以查看帮助：

```powershell
python h7tool_mcp.py --help
```

不带任何参数运行时，程序会等待 MCP 客户端通过 stdin/stdout 发送 JSON-RPC 消息，这正是 MCP 客户端需要的启动方式。

## AI 工具怎么连接

下面示例里的路径要换成你本机 `h7tool_mcp.py` 的绝对路径。

### Codex / ChatGPT 桌面端 / Codex IDE

可以在 Codex 的 MCP 设置里添加一个 stdio server，也可以编辑 `~/.codex/config.toml`：

```toml
[mcp_servers.h7tool]
command = "python"
args = ["D:\\Tools\\h7toolPC_release\\mcp\\h7tool_mcp.py"]
enabled = true
```

Codex 也支持在可信项目中使用 `.codex/config.toml` 做项目级 MCP 配置。配置完成后，如果工具没有立刻出现，重启或刷新 AI 客户端。

### Claude Desktop 和其他 JSON 配置的 MCP 客户端

添加类似下面的 server 配置：

```json
{
  "mcpServers": {
    "h7tool": {
      "command": "python",
      "args": ["D:\\Tools\\h7toolPC_release\\mcp\\h7tool_mcp.py"]
    }
  }
}
```

保存配置后重启客户端。server 名称可以自定义，建议使用 `h7tool`。

### Cherry Studio

Cherry Studio 使用 `设置 -> MCP 服务器 -> 添加服务器` 配置。类型选择 `STDIO`，推荐命令填写 `h7tool_mcp.cmd` 的绝对路径，参数留空。

详细步骤见：[Cherry Studio 配置 H7-TOOL MCP 教程](docs/cherry-studio.zh-CN.md)。

更多客户端配置见：[AI 客户端接入 H7-TOOL MCP 指南](docs/ai-clients.zh-CN.md)。

## 怎么让 AI 调用

连接成功后，直接让 AI 使用 h7tool MCP 工具即可。示例：

```text
使用 h7tool MCP 服务器列出可用的 H7-TOOL 接口。
```

```text
使用 h7tool 搜索本地芯片库里的 STM32H743。
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

推荐流程：

1. 先让 AI 调用 `bridge_status`。
2. 再让 AI 搜索或检查目标芯片 profile。
3. 然后调用 `lua_health` 或 `health_summary`。
4. 再调用 `target_summary`。
5. 目标 profile 确认后，再让 AI 做更具体的读取或总结。

## 可用 MCP 工具

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
- `target_summary`
- `target_flash_info`
- `tool_registers`
- `read_option_bytes`
- `protection_status`
- `uart_transact`
- `can_transact`
- `rtt_read`
- `log_tail`
- `read_memory`

## 说明

H7-TOOL 设备库里的 Lua 脚本经常描述一整个芯片系列，而不是单个精确型号。例如搜索 `STM32H743` 可能会返回通用 STM32H7 profile。需要精确判断型号时，建议结合实机探测结果、profile 元数据和芯片特定寄存器一起判断。

同一时间最好只让一个程序控制同一个 H7-TOOL 操作通道。如果 AI 调用超时或结果异常，先关闭 PC 工具中可能冲突的操作，再重新尝试。
