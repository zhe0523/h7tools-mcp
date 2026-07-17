# Cherry Studio 配置 H7-TOOL MCP 教程

这篇教程用于在 Cherry Studio 中启用本项目的 H7-TOOL MCP 服务器。配置完成后，可以在 Cherry Studio 的对话里让 AI 调用 H7-TOOL 工具，例如查看连接状态、搜索芯片库、识别目标板、读取保护状态等。

Cherry Studio 官方 MCP 配置流程是：打开设置，进入 `MCP 服务器`，点击 `添加服务器`，选择 `STDIO` 类型，然后填写命令和参数。

## 1. 准备项目目录

推荐把本仓库放在 H7-TOOL PC 软件包根目录下，并命名为 `mcp`：

```text
h7toolPC_release/
  EMMC/
    H7-TOOL/
      Programmer/
        Device/
  mcp/
    h7tool_mcp.py
    requirements.txt
    config.json
```

示例：

```powershell
cd D:\Tools\h7toolPC_release
git clone https://github.com/zhe0523/h7tools-mcp.git mcp
```

如果你已经把仓库放在别的位置，也可以使用，只是要确认 `h7tool_mcp.py` 的路径在 Cherry Studio 里填对。

## 2. 安装 Python 依赖

进入 MCP 项目目录：

```powershell
cd D:\Tools\h7toolPC_release\mcp
python -m pip install -r requirements.txt
python h7tool_mcp.py --self-test
```

如果 `python` 不是你想用的 Python，也可以改用 Python 启动器：

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 h7tool_mcp.py --self-test
```

看到 `Self-test passed` 就说明 Python 环境正常。

## 3. 创建本机配置文件

USB HID 是当前推荐配置：

```powershell
copy config.usb-hid.example.json config.json
python h7tool_mcp.py --list-hid-devices
```

如果你使用的是 `py -3.12`，后续命令也保持一致：

```powershell
py -3.12 h7tool_mcp.py --list-hid-devices
```

如果只接了一台 H7-TOOL，`config.json` 里的 `serial_number` 可以留空。如果同时连接多台 H7-TOOL，把 `--list-hid-devices` 输出中的目标设备序列号填入 `config.json`。

建议先在命令行确认一次目标板链路：

```powershell
python h7tool_mcp.py --lua-health
python h7tool_mcp.py --target-summary ST/STM32H7xx/STM32H7x_2M.lua --include-protection-status
```

这一步不是 Cherry Studio 必需步骤，但能提前排除 Python、H7-TOOL、目标板连接问题。

## 4. 在 Cherry Studio 添加 MCP 服务器

打开 Cherry Studio：

1. 进入 `设置`。
2. 找到 `MCP 服务器`。
3. 点击 `添加服务器`。
4. 类型选择 `STDIO`。
5. 填写服务器信息。

Windows 下最推荐使用仓库里的启动脚本，这样可以避免参数拆分和 Python 启动器差异：

```text
名称: h7tool
类型: STDIO
命令: D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
参数: 留空
```

如果不用启动脚本，也可以直接配置 Python。推荐配置如下：

```text
名称: h7tool
类型: STDIO
命令: py
参数: -3.12 D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py
```

如果你习惯直接使用 `python`，也可以这样填：

```text
名称: h7tool
类型: STDIO
命令: python
参数: D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py
```

注意：

- `命令` 只填可执行程序，例如 `py` 或 `python`。
- `参数` 填后面的参数。如果使用 `py -3.12`，参数就是 `-3.12 D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py`。
- `D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py` 只是示例路径，必须换成你本机真实的 `h7tool_mcp.py` 绝对路径。
- `py` 和 `python` 不能混用参数：如果命令填 `py`，参数可以带 `-3.12`；如果命令填 `python`，参数里不要写 `-3.12`。
- 如果 Cherry Studio 对同一行参数拆分不符合预期，把参数拆成多行：第一行 `-3.12`，第二行脚本绝对路径。
- 如果路径里有空格，优先把仓库放到无空格路径；如果必须使用带空格路径，按 Cherry Studio 当前输入框规则给脚本路径加引号。

保存后，如果工具没有出现，可以重启 Cherry Studio 再试。

## 5. 在对话中启用和调用

在 Cherry Studio 的聊天界面，确认当前助手或对话已启用 `h7tool` 这个 MCP 服务器。不同版本界面可能略有不同，通常需要在工具、MCP 或助手工具设置里勾选刚添加的服务器。

可以这样测试：

```text
使用 h7tool MCP，调用 bridge_status，看看 H7-TOOL MCP 服务器是否正常。
```

再测试设备：

```text
使用 h7tool MCP 调用 health_summary，总结当前 H7-TOOL 状态。
```

测试目标板：

```text
使用 h7tool MCP 调用 target_summary，profile 使用 ST/STM32H7xx/STM32H7x_2M.lua，并解释结果。
```

如果 Cherry Studio 能显示工具调用过程，并返回 H7-TOOL 状态或目标板信息，就说明配置成功。

## 6. 常见问题

### 工具没有出现在 Cherry Studio 里

- 确认服务器类型是 `STDIO`。
- 确认命令和参数分开填写。
- 确认脚本路径是绝对路径。
- 保存后重启 Cherry Studio。

### 启用时报 `Connection closed`

通常是 MCP 进程刚启动就退出了。优先检查这两项：

1. 优先改用启动脚本，参数留空。

```text
命令: D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
参数:
```

2. 如果命令填的是 `python`，参数不要写 `-3.12`。

错误示例：

```text
命令: python
参数: -3.12 D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py
```

正确示例一：

```text
命令: py
参数: -3.12 D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py
```

如果这一行仍然失败，可以把参数拆成两行：

```text
命令: py
参数:
-3.12
D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py
```

正确示例二：

```text
命令: python
参数: D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py
```

3. 确认脚本路径真实存在。可以在 PowerShell 里测试：

```powershell
Test-Path D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py
Test-Path D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
py -3.12 D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py --self-test
D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd --self-test
```

如果 `--self-test` 能输出 `Self-test passed`，说明 Cherry Studio 里也应该使用同一组命令和参数。

### 提示找不到 hid 或 serial

说明 Cherry Studio 调起的 Python 环境没有安装依赖。用同一个命令安装：

```powershell
py -3.12 -m pip install -r D:\Tools\h7toolPC_release\mcp\requirements.txt
```

如果 Cherry Studio 配的是 `python`，则使用：

```powershell
python -m pip install -r D:\Tools\h7toolPC_release\mcp\requirements.txt
```

### H7-TOOL 能枚举，但 Lua 或目标板命令失败

- 确认 H7-TOOL 已连接电脑。
- 确认目标板供电和 SWD 接线正常。
- 关闭 H7-TOOL PC 工具中可能正在占用同一操作通道的功能，再重试。
- 先在命令行运行 `--lua-health` 和 `--target-summary`，确认不是 Cherry Studio 配置问题。

### 想确认 Cherry Studio 调用的是哪个 Python

把 Cherry Studio 的 `命令` 改成你确认过的绝对路径，例如：

```text
命令: C:\Users\YourName\AppData\Local\Programs\Python\Python312\python.exe
参数: D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py
```

这样可以避免系统里多个 Python 导致依赖装错位置。

## 参考

- Cherry Studio 官方文档：[配置和使用 MCP](https://docs.cherry-ai.com/advanced-basic/mcp/config)
- Cherry Studio 官方文档：[MCP 环境安装](https://docs.cherry-ai.com/advanced-basic/mcp/install)
