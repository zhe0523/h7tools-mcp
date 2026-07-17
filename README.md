# H7-TOOL MCP Assistant

[中文说明](README.zh-CN.md)

This project provides a local MCP server for H7-TOOL. After it is enabled in an AI client, the AI can call H7-TOOL-related tools to inspect the connected programmer, search the local device library, identify a target board, and read development diagnostics.

The public documentation only covers installation and usage. Product-internal communication details are intentionally not documented here.

## What It Does

- Lists available H7-TOOL USB interfaces and local bridge settings.
- Reads H7-TOOL status and health information.
- Searches the local H7-TOOL device Lua library by vendor, series, or chip name.
- Searches bundled H7-TOOL Lua examples and bus helper scripts so the AI can inspect original peripheral usage.
- Provides public safety and style rules for AI-authored H7-TOOL Lua helper scripts.
- Provides an offline Lua draft workspace to create, list, read, and validate drafts without executing them.
- Provides a dangerous-action policy gate for future programming, erase, unlock, protection, power, and raw-Lua actions.
- Parses device profiles for interface type, expected ID, UID location, memory ranges, included libraries, and algorithm entries.
- Summarizes profile capabilities so the AI can understand what a chip profile appears to support.
- Probes a connected STM32H7 target and combines live results with the selected local profile.
- Reads bounded target memory ranges for diagnostics.
- Reads option-byte values described by a selected local profile.
- Summarizes protection status when the selected profile provides the required rules.
- Sends and receives short data through H7-TOOL UART channels for loopback tests, AT commands, and simple serial debugging.
- Sends bounded CAN/CAN-FD frames through H7-TOOL.
- Scans I2C addresses or performs one bounded I2C write/read transaction.
- Performs one bounded SPI write/read transaction with CS0 or CS1.
- Attempts to read SEGGER RTT up-buffer logs from target firmware.

## Directory Layout

Recommended layout:

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

In other words, place or clone this repository as the `mcp` directory under the H7-TOOL PC software package root, beside `EMMC`.

Example:

```powershell
cd D:\Tools\h7toolPC_release
git clone https://github.com/zhe0523/h7tools-mcp.git mcp
```

This layout lets the MCP server find the H7-TOOL device library automatically.

## Install

Use Python 3.11 or newer.

```powershell
cd D:\Tools\h7toolPC_release\mcp
python -m pip install -r requirements.txt
python h7tool_mcp.py --self-test
```

If the self-test prints `Self-test passed`, the Python side is working.

## Configure H7-TOOL Access

Create a local `config.json` from the example that matches your connection method. The most common current path is USB HID:

```powershell
copy config.usb-hid.example.json config.json
python h7tool_mcp.py --list-hid-devices
```

If more than one matching H7-TOOL interface is found, copy the correct `serial_number` into `config.json`.

Useful local checks:

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

`config.json` is intentionally ignored by git because it contains local device settings.

Dangerous actions are disabled by default. Future programming, erase, unlock, protection, power-control, and raw-Lua tools must check `dangerous_actions` in `config.json` and require the matching confirmation phrase on each request.

## Start The MCP Server

The MCP server uses stdio. Usually you do not start it manually; your AI client starts it.

On Windows, prefer the launcher script:

```text
D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
```

Replace the path with the absolute path on your machine. The launcher avoids many client-specific differences around Python launchers, argument splitting, non-ASCII paths, and paths containing spaces.

For manual command-line checks, use one of the flags shown by:

```powershell
python h7tool_mcp.py --help
```

When no flag is provided, the program waits for MCP JSON-RPC messages on stdin/stdout, which is what MCP clients expect.

## Connect From AI Tools

Configure this repository's `h7tool_mcp.cmd` as a local stdio MCP server.

Before connecting an AI client, verify the server from a terminal:

```powershell
cd D:\Tools\h7toolPC_release\mcp
.\h7tool_mcp.cmd --self-test
.\h7tool_mcp.cmd --lua-health
```

Then verify any hardware workflow you plan to expose to the AI:

```powershell
.\h7tool_mcp.cmd --target-summary ST/STM32H7xx/STM32H7x_2M.lua --include-protection-status
.\h7tool_mcp.cmd --uart-transact --uart-channel 1 --uart-baud 115200 --uart-send-hex "48 37 0D 0A" --uart-rx-length 64
.\h7tool_mcp.cmd --i2c-transact --i2c-clock 100000 --i2c-scan
.\h7tool_mcp.cmd --spi-transact --spi-freq-id 0 --spi-cs 0 --spi-write-hex "9F" --spi-read-length 3
```

Most AI clients need the same fields:

- Name: `h7tool`
- Type: `stdio`
- Command: `D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd`
- Arguments: empty

If a client cannot launch `.cmd` directly, use `cmd` as the command and `/c D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd` as the arguments.

### Codex / ChatGPT Desktop / Codex IDE

Open the Codex MCP settings and add a stdio server, or edit `~/.codex/config.toml`:

```toml
[mcp_servers.h7tool]
command = 'D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd'
args = []
enabled = true
startup_timeout_sec = 20
tool_timeout_sec = 60
```

You can also add it with Codex CLI:

```powershell
codex mcp add h7tool -- D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
codex mcp list
```

After adding the server, restart or reload the AI client if it does not appear immediately. Ask the AI to call `bridge_status` to confirm the connection.

### Cherry Studio

In Cherry Studio, open `Settings -> MCP Server -> Add server`, choose `STDIO`, then set:

```text
Name: h7tool
Command: D:\Tools\h7toolPC_release\mcp\h7tool_mcp.cmd
Arguments: empty
```

Chinese step-by-step guide: [Cherry Studio 配置 H7-TOOL MCP 教程](docs/cherry-studio.zh-CN.md).

### Claude Code / Claude Desktop / opencode

These clients use the same local stdio MCP idea. Chinese multi-client guide: [AI 客户端接入 H7-TOOL MCP 指南](docs/ai-clients.zh-CN.md).

Lua helper authoring rules are documented in Chinese here: [AI 编写 H7-TOOL Lua 辅助脚本规则](docs/lua-authoring-rules.zh-CN.md).

## How To Ask The AI To Use It

Once the MCP server is connected, ask the AI to use the H7-TOOL tools directly. Example prompts:

```text
Use the h7tool MCP server to list available H7-TOOL interfaces.
```

```text
Use h7tool to search the local device library for STM32H743.
```

```text
Use h7tool lua_example_search to find bundled I2C BH1750 examples and summarize how they are called.
```

```text
Use h7tool lua_authoring_rules before drafting a custom H7-TOOL Lua helper script.
```

```text
Use h7tool lua_draft_create to draft an I2C register-read Lua helper, then validate it with lua_draft_validate without executing it.
```

```text
Use h7tool dangerous_action_policy to check whether programming, erase, unlock, protection, and similar dangerous actions are currently allowed.
```

```text
Use h7tool target_identity with ST/STM32H7xx/STM32H7x_2M.lua and summarize the connected target.
```

```text
Use h7tool target_summary with ST/STM32H7xx/STM32H7x_2M.lua and recommend the next diagnostic step.
```

```text
Use h7tool protection_status for the selected STM32H7 profile and explain the result.
```

```text
Use h7tool uart_transact on channel 1, 115200 8N1, send hex: 48 37 0D 0A, and read up to 64 response bytes.
```

```text
Use h7tool can_transact at 500K bitrate to send standard frame ID 0x321 with data 01 02 03 04.
```

```text
Use h7tool i2c_transact to scan I2C addresses at 100K clock.
```

```text
Use h7tool spi_transact with freq_id 0, phase 0, polarity 0, CS0, send hex 9F, and read 3 bytes.
```

```text
Use h7tool rtt_read to try reading target RTT channel 0 logs.
```

Good workflow:

1. Ask the AI to check `bridge_status`.
2. Ask it to search or inspect the target device profile.
3. Ask it to run `lua_health` or `health_summary`.
4. Ask it to run `target_summary`.
5. Ask for focused memory, option-byte, RTT, or peripheral transactions only after the target profile is selected.

## Available MCP Tools

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

## Notes

Device scripts in the H7-TOOL package often describe whole chip families rather than one exact part number. For example, searching for `STM32H743` may return a generic STM32H7 profile. Use live target data, profile metadata, and chip-specific registers together when exact identification matters.

Only one program should actively control the same H7-TOOL operation path at a time. If an AI call times out or returns an unexpected result, close conflicting operations in the PC tool and try again.
