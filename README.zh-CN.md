# H7-TOOL MCP 辅助开发工具

这个项目提供一个本地 MCP 服务器，用来把 H7-TOOL 接入支持 MCP 的 AI 工具。启用之后，AI 可以调用 H7-TOOL 相关工具，查看连接状态、搜索本地芯片库、识别目标板、读取调试诊断信息。

安装和使用从本文开始；已验证的私有 HID/Modbus 入口及安全边界见：[H7-TOOL V2.33 未公开固件接口](docs/undocumented-firmware-interfaces.zh-CN.md)。

## 支持功能

- 列出可用的 H7-TOOL USB 接口和本地桥接配置。
- 读取 H7-TOOL 状态和健康信息。
- 按厂商、系列、芯片名搜索本地 H7-TOOL 设备 Lua 库。
- 搜索 H7-TOOL 自带 Lua 示例和总线辅助脚本，辅助 AI 查找原始外设用法。
- 提供 AI 编写 H7-TOOL Lua 辅助脚本的公开规则和安全边界。
- 提供常用 Lua 调试模板和 AI 调试工作流，覆盖 UART、Modbus RTU、I2C、SPI、CAN 等常见实验。
- 提供离线 Lua 草稿工作区：创建、列出、读取和校验草稿，但不执行脚本。
- 支持对 Lua 草稿做静态审查，并在显式确认后运行通过校验的草稿。
- 提供危险动作门禁策略，供后续烧录、擦除、解锁、改保护等动作统一使用。
- 提供烧录前预检：检查固件文件、哈希、大小、起始地址、目标 profile、Flash 元数据和危险动作策略，但不执行烧录。
- 生成脱敏 Markdown 诊断报告，适合论坛交流、issue、阶段归档或交接。
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
python h7tool_mcp.py --lua-template-library
python h7tool_mcp.py --lua-template-library spi_jedec_id
python h7tool_mcp.py --lua-debug-workflow "读取 SPI Flash JEDEC ID" --lua-debug-interface spi
python h7tool_mcp.py --lua-draft-list
python h7tool_mcp.py --lua-draft-review example.lua
python h7tool_mcp.py --dangerous-action-policy
python h7tool_mcp.py --dangerous-action-plan "program firmware" --dangerous-action-level program
python h7tool_mcp.py --device-profile ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --programming-preflight firmware.bin --device-profile ST/STM32H7xx/STM32H7x_2M.lua --programming-address 0x08000000
python h7tool_mcp.py --diagnostic-report session-summary --device-profile ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --lua-health
python h7tool_mcp.py --target-identity ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --target-summary ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --target-flash-info ST/STM32H7xx/STM32H7x_2M.lua
```

`config.json` 是本机配置文件，已经被 git 忽略，不需要提交。

常规调试动作默认可用，例如查询设备、读目标信息、总线收发、RTT 读取、创建和运行非破坏性 Lua 草稿。危险动作默认关闭；烧录、擦除、解锁、改保护、供电控制、改持久存储或寄存器状态等动作接入时，会先检查 `config.json` 中的 `dangerous_actions`，并要求请求里提供匹配的确认短语。

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
使用 h7tool lua_draft_review 审查一个 Lua 草稿，确认它属于非破坏性还是危险动作。
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
3. 需要 Lua 辅助调试时，让 AI 调用 `lua_debug_workflow` 和 `lua_template_library`，生成小草稿。
4. 调用 `lua_draft_review` 审查草稿；非破坏性调试可以直接用 `lua_draft_run` 加 `execute=true` 运行。
5. 然后调用 `lua_health`、`health_summary` 或 `target_summary` 做硬件状态确认。
6. 目标 profile 确认后，再让 AI 做更具体的内存、Option Byte、RTT 或外设事务。
7. 涉及烧录、擦除、改保护等动作前，先调用 `programming_preflight` 或 `dangerous_action_plan`，确认无误后再进入后续执行工具。
8. 阶段结束时调用 `diagnostic_report` 生成脱敏 Markdown 报告。

## 可用 MCP 工具

- `bridge_status`
- `device_vendors`
- `device_search`
- `lua_example_search`
- `lua_authoring_rules`
- `lua_template_library`
- `lua_debug_workflow`
- `lua_draft_create`
- `lua_draft_list`
- `lua_draft_read`
- `lua_draft_validate`
- `lua_draft_review`
- `lua_draft_run`
- `dangerous_action_policy`
- `dangerous_action_explain`
- `dangerous_action_plan`
- `programming_preflight`
- `diagnostic_report`
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
- `tool_mode_switch`
- `device_file_write`
- `device_file_read`

## 说明

H7-TOOL 设备库里的 Lua 脚本经常描述一整个芯片系列，而不是单个精确型号。例如搜索 `STM32H743` 可能会返回通用 STM32H7 profile。需要精确判断型号时，建议结合实机探测结果、profile 元数据和芯片特定寄存器一起判断。

同一时间最好只让一个程序控制同一个 H7-TOOL 操作通道。如果 AI 调用超时或结果异常，先关闭 PC 工具中可能冲突的操作，再重新尝试。

### 原生目标内存读取与模式切换

`read_memory` 在 `adapter.type=h7tool_hid` 时接受 `transport`：

- `lua`（默认）：保持原来的 Lua `pg_read_mem` 路径，兼容已有调用；
- `native`：直接使用固件私有功能码 `0x66`，首包子功能 0 初始化调试链路，续包子功能 1 连续读取，不经过 Lua VM。

原生读取要求设备已经加载正确的目标/烧录器配置，目标供电和 SWD/SWIM 连线正常；否则设备会返回非零 `status`。当前实现只支持单路目标，多路 SWD 的响应布局尚未纳入。

`tool_mode_switch` 是寄存器 `0xFF7F` 的白名单封装，只允许 `restart_app`、`emmc`、`link`，并要求 `dangerous_actions` 开启 `power` 级别及匹配的确认词。切换后 HID 可能立刻断开或重枚举，这是正常现象。Bootloader、DAP、脱机烧录、任意寄存器写和校准入口不会通过 MCP 暴露。


### 在 H7-TOOL 上读写文件

`device_file_write` 和 `device_file_read` 用于向设备的 EMMC（`0:/`）或 SD 卡（`1:/`）传输普通文件。

- 写入属于危险动作，会受门禁控制：在 `config.json` 里设置 `"dangerous_actions": {"enabled": true, "allowed_levels": ["write"], ...}`，并传入与之匹配的 `confirmation` 确认词。读取不受门禁限制。
- 设备 FAT 以 GBK 存储中文文件名，因此 `path_encoding` 默认为 `gbk`；纯 ASCII 目录可传 `utf-8`。
- Lua 文件接口没有删除、截断、建目录的函数：目标目录必须已存在，且重写比原文件短的内容会保留旧的尾巴；`device_file_write` 会在 `warnings` 里报告这种情况，请用 PC 软件删除该文件后重新写入。
- 在 TOOL 上还有 Lua 脚本正在运行时写入，会与功能码 `0x64` 的 Lua 重置相撞，从而写入错误的内容。`verified: false` 就是这个意思：先在 TOOL 上按 **C** 退出正在运行的脚本，再重新写入；在空闲的 TOOL 上写入并核验通过时，内容是逐字节一致的。
- 超过 16 KiB 的写入、以及跨 4 KiB 页的写入都已在内部处理：单次 `f_write` 不接受大于 16 KiB 的数据，而从非对齐偏移跨越 4096 字节页时设备会重复一个字节。
- Lua 脚本本身不再限于约 1000 字节：功能码 `0x64` 的三个字段是（总长度, 偏移, 本块长度），桥接会把大脚本分报文传输。

### Lua 调用返回空输出时

设备偶尔会对 `0x64`（下载并执行 Lua）请求回 ack，但既不执行脚本也不打印任何东西，而此时 `tool_status` 等寄存器读取仍然正常。在 H7-TOOL 上按一次 **C**（或重新上电）即可清除卡住的 Lua 会话，然后重试。

桥接已经会对只读和幂等的调用自动重试一次；`lua_draft_run` 也接受 `retry_on_empty: true`，适用于重复执行安全的脚本。

`adapter` 里相关的配置：

| 键 | 默认值 | 含义 |
|---|---|---|
| `timeout_ms` | 示例配置为 `20000` | 单次 Lua 调用的总时间窗口 |
| `print_quiet_ms` | `500` | 无标记脚本的输出静默多久后视为结束 |
| `lua_chunk_bytes` | `700` | 传输脚本时的 HID 报文负载，不得超过 1000 |
| `lua_chunk_delay_ms` | `4` | 脚本分块之间的间隔 |
| `drain_before_run_ms` | `150` | 运行前先消耗旧的打印输出，避免被当成本次结果 |

## 截屏

`screenshot` 抓取 H7-TOOL **自身**的屏幕并存成 PNG。

- 功能码 `0x66`、子功能 `0x0100`（`H66_READ_DISP_MEM`）：固件直接从显存 `0x30000000` 拷贝。
- 数据是原始 RGB565 小端、行优先、左上原点、stride = 屏宽、**无压缩**；240x320 面板为 153600 字节。
- `offset` 是显存绝对字节偏移，按 `offset += chunk` 循环取满 `width*height*2` 字节即结束，
  没有结束标志、没有分块序号。
- 单包最大 1009 字节（正好放进一个 1024 字节 HID 报文）；APP V2.33 上抓一整帧约 0.26 秒。

两个必须注意的点：**独占 HID interface 2**（先关掉原厂上位机）；打开后**先排空积压报文**
（有 Lua 程序在重画屏幕时会积压几百个），并且要按 **unit + 功能码 + 子功能 + offset +
length + CRC** 六重匹配，因为管道里还混着 `01 61 ...` 这类无关的 Lua 打印帧。

### 二进制安全写入

`device_file_write` 的分片以 **base64** 传输。Lua 长字符串本身能容纳 NUL 字节，但固件是把
整个脚本当 **C 字符串**交给 `luaL_dostring()` 的，脚本里只要有一个 NUL 就被截断，之后每次
写入都会静默失效。

## EMMC 文件管理（原生通道）

功能码 `0x64` 的 `func` 字段带了一整套文件管理指令（和下载 Lua 用的是同一帧），
所以**列目录 / 删除 / 建目录都能在线做，DAP 调试口全程不断**。Lua 层做不到：
`f_dir` 会让固件崩、`os.remove`/`os.rename` 是静默空操作。

| func | 工具 | 说明 |
|---|---|---|
| 2 | `device_file_list` | 每行 `F<大小hex>\|<日期 时间>\|<文件名>`，`D` 表示目录 |
| 3 | `device_file_md5` | 标准 MD5，已与 hashlib 逐字节核对 |
| 4 | `device_file_delete` | 受 dangerous level `write` 门禁 |
| 6 | 读文件 | 应答 `total(4) offset(4) bytes(4) 数据` |
| 7 | 写文件 | 载荷 `大小(4) MD5(16) 名字长(1) 完整路径 数据` |
| 8 | `device_file_mkdir` | 0 = 成功，1 = 已存在 |

必须处理的固件怪癖：

- 应答是 `func(2) result(1) total(4) offset(4) package_len(4) 数据`，**漏掉 result 字节**
  会让后面每个字段错位一位；
- `LIST` 和 `READ` **不会**给路径补 NUL（`DEL`/`MD5` 会 ✓）；
- `LIST` 的路径**不能带尾部斜杠**，否则返回空清单；
- `LIST` 把请求的 `package_len` 当成自己应答的长度，所以载荷要用 NUL 填充才能一次取一块；
- 一帧**只能发一次**：重发 `WRITE_FILE` 会让固件把同样数据缓冲两遍，文件直接翻倍；
- `DEL_DIR`（5）在固件里声明了但没实现。
