# AI 客户端接入 H7-TOOL MCP 指南

这篇文档说明如何把 H7-TOOL MCP 服务器接入常见 AI 工具，包括 Cherry Studio、Codex、Claude Code 和 opencode。

Windows 下推荐优先使用仓库里的启动脚本：

```text
D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
```

把上面的路径替换成你本机真实路径。这个 `.cmd` 会自动调用：

```text
py -3.12 h7tool_mcp.py
```

这样可以避免不同客户端对 `py`、`python`、参数拆分、中文路径、空格路径的处理差异。

## 通用准备

推荐目录结构：

```text
h7toolPC_release/
  EMMC/
    H7-TOOL/
      Programmer/
        Device/
  mcp/
    h7tool_mcp.py
    h7tool_mcp.cmd
    requirements.txt
    config.json
```

安装依赖并验证：

```powershell
cd D:\Tools\h7toolPC_release\mcp
py -3.12 -m pip install -r requirements.txt
.\h7tool_mcp.cmd --self-test
```

创建本机配置：

```powershell
copy config.usb-hid.example.json config.json
.\h7tool_mcp.cmd --list-hid-devices
```

验证 H7-TOOL 和目标板：

```powershell
.\h7tool_mcp.cmd --lua-health
.\h7tool_mcp.cmd --target-summary ST/STM32H7xx/STM32H7x_2M.lua --include-protection-status
```

如果这些命令都能运行，再接入 AI 客户端。

## Cherry Studio

Cherry Studio 已实测可用。推荐配置：

```text
类型: 标准输入/输出 stdio
命令: D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
参数: 留空
```

如果启用后能调用 `target_summary` 并看到 UID、IDCODE、Flash/RAM、保护状态，说明配置成功。

测试提示词：

```text
使用 h7tool MCP 调用 target_summary，profile 使用 ST/STM32H7xx/STM32H7x_2M.lua，并解释结果。
```

详细排障见：[Cherry Studio 配置 H7-TOOL MCP 教程](cherry-studio.zh-CN.md)。

## Codex / ChatGPT Desktop / Codex IDE

Codex 的 MCP 配置保存在 `config.toml` 中。默认是用户级配置：

```text
~/.codex/config.toml
```

也可以在可信项目中使用项目级配置：

```text
.codex/config.toml
```

推荐写法：

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

配置后重启 Codex / ChatGPT Desktop / IDE 扩展。如果在 ChatGPT Desktop 中使用，可以在输入框里输入：

```text
/mcp
```

查看已连接的 MCP 服务器。

测试提示词：

```text
使用 h7tool MCP 调用 bridge_status，确认服务器可用。
```

```text
使用 h7tool MCP 调用 target_summary，profile 使用 ST/STM32H7xx/STM32H7x_2M.lua，并总结目标板状态。
```

参考：

- OpenAI Codex MCP 文档：https://developers.openai.com/codex/mcp
- OpenAI Codex 配置参考：https://developers.openai.com/codex/config-reference

## Claude Code

Claude Code 推荐用 `claude mcp add` 添加本地 stdio MCP。关键点是 `--` 后面的内容才是 MCP 服务器启动命令。

Windows 下推荐通过 `cmd /c` 启动 `.cmd`：

```powershell
claude mcp add h7tool -- cmd /c D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
claude mcp list
```

如果路径里有空格，给路径加引号：

```powershell
claude mcp add h7tool -- cmd /c "D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd"
```

进入 Claude Code 后，可以用：

```text
/mcp
```

查看 MCP 服务器状态。

测试提示词：

```text
Use the h7tool MCP server to call bridge_status.
```

```text
Use h7tool target_summary with ST/STM32H7xx/STM32H7x_2M.lua and explain the connected target.
```

参考：

- Claude Code MCP 快速开始：https://code.claude.com/docs/en/mcp-quickstart
- Claude Code MCP 文档：https://code.claude.com/docs/en/mcp

## opencode

opencode 支持在配置文件的 `mcp` 字段中定义本地 MCP 服务器。官方配置中本地 MCP 使用：

```json
{
  "type": "local",
  "command": ["command", "arg1", "arg2"],
  "enabled": true
}
```

可以在 `opencode.json` 或 `opencode.jsonc` 中添加：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "h7tool": {
      "type": "local",
      "command": ["cmd", "/c", "D:\\Tools\\h7toolPC_release\\mcp\\h7tool_mcp.cmd"],
      "enabled": true
    }
  }
}
```

添加后，在提示词里明确使用该 MCP：

```text
use the h7tool tool to call bridge_status
```

```text
use h7tool target_summary with ST/STM32H7xx/STM32H7x_2M.lua
```

参考：

- opencode MCP servers 文档：https://opencode.ai/docs/mcp-servers/
- opencode 配置文档：https://opencode.ai/docs/config/

## 常见问题

### Connection closed

优先使用 `.cmd` 启动脚本，并让参数留空：

```text
命令: D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
参数: 留空
```

如果客户端要求命令必须是可执行程序，则使用：

```text
命令: cmd
参数: /c D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
```

### `Unknown option: -3`

这是把 `-3.12` 传给了 `python.exe`。`-3.12` 只能给 Windows 的 `py.exe` 启动器使用。

正确：

```text
命令: py
参数: -3.12 D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py
```

或者：

```text
命令: D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
参数: 留空
```

错误：

```text
命令: python
参数: -3.12 D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py
```

### 找不到 `hid` 或 `serial`

说明客户端启动的 Python 环境没有安装依赖。用同一个 Python 安装：

```powershell
py -3.12 -m pip install -r D:\Tools\h7toolPC_release\mcp\requirements.txt
```

### H7-TOOL 在线但目标命令失败

- 确认目标板供电和 SWD 连接正常。
- 确认 H7-TOOL PC 工具没有占用同一操作通道。
- 先在命令行运行：

```powershell
D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd --target-summary ST/STM32H7xx/STM32H7x_2M.lua --include-protection-status
```

命令行能成功时，再回到 AI 客户端测试。
