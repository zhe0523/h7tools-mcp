# H7-TOOL MCP Assistant

[中文说明](README.zh-CN.md)

This project provides a local MCP server for H7-TOOL. After it is enabled in an AI client, the AI can call H7-TOOL-related tools to inspect the connected programmer, search the local device library, identify a target board, and read development diagnostics.

The public documentation only covers installation and usage. Product-internal communication details are intentionally not documented here.

## What It Does

- Lists available H7-TOOL USB interfaces and local bridge settings.
- Reads H7-TOOL status and health information.
- Searches the local H7-TOOL device Lua library by vendor, series, or chip name.
- Parses device profiles for interface type, expected ID, UID location, memory ranges, included libraries, and algorithm entries.
- Summarizes profile capabilities so the AI can understand what a chip profile appears to support.
- Probes a connected STM32H7 target and combines live results with the selected local profile.
- Reads bounded target memory ranges for diagnostics.
- Reads option-byte values described by a selected local profile.
- Summarizes protection status when the selected profile provides the required rules.

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
python h7tool_mcp.py --device-profile ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --lua-health
python h7tool_mcp.py --target-identity ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --target-summary ST/STM32H7xx/STM32H7x_2M.lua
```

`config.json` is intentionally ignored by git because it contains local device settings.

## Start The MCP Server

The MCP server uses stdio. Usually you do not start it manually; your AI client starts it with this command:

```powershell
python D:\Tools\h7toolPC_release\mcp\h7tool_mcp.py
```

For manual command-line checks, use one of the flags shown by:

```powershell
python h7tool_mcp.py --help
```

When no flag is provided, the program waits for MCP JSON-RPC messages on stdin/stdout, which is what MCP clients expect.

## Connect From AI Tools

Use an absolute path to `h7tool_mcp.py`.

### Codex / ChatGPT Desktop / Codex IDE

Open the Codex MCP settings and add a stdio server, or edit `~/.codex/config.toml`:

```toml
[mcp_servers.h7tool]
command = "python"
args = ["D:\\Tools\\h7toolPC_release\\mcp\\h7tool_mcp.py"]
enabled = true
```

Codex also supports project-level MCP config in `.codex/config.toml` for trusted projects. After adding the server, restart or reload the AI client if it does not appear immediately.

### Claude Desktop And Other JSON-Based MCP Clients

Add a server entry like this:

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

After saving the config, restart the client. The server name can be any friendly name; `h7tool` is recommended.

## How To Ask The AI To Use It

Once the MCP server is connected, ask the AI to use the H7-TOOL tools directly. Example prompts:

```text
Use the h7tool MCP server to list available H7-TOOL interfaces.
```

```text
Use h7tool to search the local device library for STM32H743.
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

Good workflow:

1. Ask the AI to check `bridge_status`.
2. Ask it to search or inspect the target device profile.
3. Ask it to run `lua_health` or `health_summary`.
4. Ask it to run `target_summary`.
5. Ask for focused reads or summaries only after the target profile is selected.

## Available MCP Tools

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
- `tool_registers`
- `read_option_bytes`
- `protection_status`
- `log_tail`
- `read_memory`

## Notes

Device scripts in the H7-TOOL package often describe whole chip families rather than one exact part number. For example, searching for `STM32H743` may return a generic STM32H7 profile. Use live target data, profile metadata, and chip-specific registers together when exact identification matters.

Only one program should actively control the same H7-TOOL operation path at a time. If an AI call times out or returns an unexpected result, close conflicting operations in the PC tool and try again.
