# AI 编写 H7-TOOL Lua 辅助脚本规则

这份规则用于指导 AI 编写 H7-TOOL Lua 辅助脚本。公开文档只描述脚本编写约束和使用流程，不展开产品内部通信细节。

## 推荐流程

1. 先调用 `lua_example_search` 搜索 H7-TOOL 自带示例。
2. 如果现有 MCP 工具已经覆盖需求，优先使用 `i2c_transact`、`spi_transact`、`uart_transact`、`can_transact`、`rtt_read` 等工具。
3. 确实需要自定义 Lua 时，只写小而明确的单用途脚本。
4. 让脚本输出稳定的 `key=value` 字段，方便 AI 或 MCP 层解析。
5. 一次只让一个程序控制同一个 H7-TOOL 操作通道。

## 草稿工作区

AI 可以先把 Lua 写成离线草稿，而不是直接执行：

- `lua_draft_create`：创建或覆盖草稿。
- `lua_draft_list`：列出草稿。
- `lua_draft_read`：读取草稿并返回校验结果。
- `lua_draft_validate`：校验草稿文本或已保存草稿。
- `lua_draft_review`：静态审查草稿，归类为非破坏性或危险动作。
- `lua_draft_run`：在显式确认后运行已保存草稿。

草稿保存在本地 `workspace/lua_drafts/`，该目录不提交到 git。创建、列表、读取、校验、审查工具不会执行 Lua，也不会访问硬件。

运行草稿时必须满足：

- 只能运行 `workspace/lua_drafts/` 里的 `.lua` 文件。
- 每次请求必须传 `execute=true`。
- 草稿必须通过 `lua_draft_validate`。
- 草稿必须包含 `H7TOOL_USER_BEGIN` 和 `H7TOOL_USER_END` 输出标记。
- 如果 `lua_draft_review` 判断为危险动作，还必须通过 `dangerous_action_policy` 的配置和确认短语；配置里需要同时允许 `raw_lua` 和对应的具体危险级别。

## 危险动作门禁

烧录、擦除、解锁、改保护、供电控制、执行自定义 Lua 等动作属于危险动作。相关功能接入时必须先检查 `dangerous_action_policy`：

- `dangerous_actions.enabled` 必须为 `true`。
- 动作级别必须出现在 `dangerous_actions.allowed_levels` 中。
- 每次请求都必须提供与 `confirmation_phrase` 完全一致的确认短语。

当前门禁级别包括：

- `write`：写寄存器、写 EEPROM、写外设状态等。
- `erase`：擦除 Flash、EEPROM、外部 Flash 等。
- `program`：烧录目标或外部存储器。
- `protection`：改 Option Byte、读保护、安全锁等。
- `power`：目标供电、复位、电源时序。
- `raw_lua`：执行自定义 Lua 脚本。

## 输出格式

建议所有 AI 编写的 Lua 辅助脚本都使用类似结构：

```lua
print("H7TOOL_USER_BEGIN")
print("operation=i2c_register_read")
print("ok=0")
-- 执行受限操作
print("ok=1")
print("H7TOOL_USER_END")
```

规则：

- 必须有唯一的 BEGIN/END 标记。
- 标记之间使用 `key=value` 输出。
- 十六进制字节使用大写两位格式，并用空格分隔。
- 输出中要有足够字段判断操作是否成功。

## 安全边界

- 循环必须有明确次数上限，不写无限循环。
- 读写长度必须有上限。
- 地址、长度、片选、通道等参数必须在生成脚本前校验。
- 探索未知硬件时优先使用只读或可逆事务。
- I2C/SPI 等总线在失败路径也要尽量发送 stop 或释放片选。
- 除非用户明确要求，不写擦除、烧录、解锁、改保护、改 Option Byte、断电上电等动作。
- 不把本机路径、设备序列号、UID、抓包内容写进公开文件。

## 常用模板

### I2C 寄存器读取

```lua
print("H7TOOL_USER_BEGIN")
i2c_bus("init", CLK)
i2c_bus("start")
ack = i2c_bus("send", ADDR * 2)
ack = i2c_bus("send", REG)
i2c_bus("start")
ack = i2c_bus("send", ADDR * 2 + 1)
rx = i2c_bus("recive", LEN)
i2c_bus("stop")
print("read_len=" .. string.len(rx))
print("H7TOOL_USER_END")
```

### SPI 命令后读取

```lua
print("H7TOOL_USER_BEGIN")
spi_bus("init", FREQ_ID, PHASE, POLARITY)
gpio_write(CS, 0)
spi_bus("send", TX)
rx = spi_bus("recive", LEN)
gpio_write(CS, 1)
print("read_len=" .. string.len(rx))
print("H7TOOL_USER_END")
```

这些模板只表达脚本结构。实际脚本应根据目标外设、线序、参数范围和返回格式进一步收紧。
