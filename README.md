# H7-TOOL MCP Assistant

[中文说明](README.zh-CN.md)

This project provides an MCP server for using H7-TOOL as an assisted embedded-development tool. It helps an AI client inspect the tool, search the local H7-TOOL device library, identify a connected target, and collect useful development diagnostics.

The implementation is designed around the H7-TOOL files already present in a normal PC software package. It does not publish private transport details or require users to understand the underlying communication framing.

## Features

- List H7-TOOL connection candidates and local bridge configuration.
- Read H7-TOOL status and produce a compact health summary.
- Search the local H7-TOOL device library by vendor, series, or chip name.
- Parse device Lua profiles for interface type, expected ID, UID location, memory ranges, included libraries, and algorithm entries.
- Summarize device-profile capabilities, including development-useful operations and operations that should be treated carefully.
- Probe a connected STM32H7 target and combine the live result with a selected local profile.
- Read bounded target memory ranges for diagnostics.
- Read option-byte values from addresses described by a selected local profile.
- Summarize protection status when the selected profile provides the required check rules.

## Requirements

- Python 3.11+.
- H7-TOOL PC software package with its `EMMC/H7-TOOL` directory available beside this project.
- Optional Python packages from `requirements.txt` for USB HID or serial access.

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run self-test:

```powershell
python h7tool_mcp.py --self-test
```

## Common Commands

List visible H7-TOOL USB interfaces:

```powershell
python h7tool_mcp.py --list-hid-devices
```

Inspect local device-library support:

```powershell
python h7tool_mcp.py --device-vendors
python h7tool_mcp.py --device-search STM32H743 --device-vendor ST
python h7tool_mcp.py --device-profile ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --device-capabilities ST/STM32H7xx/STM32H7x_2M.lua
```

Run target diagnostics after configuring `config.json`:

```powershell
python h7tool_mcp.py --probe-h7tool
python h7tool_mcp.py --health-summary
python h7tool_mcp.py --target-identity ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --read-memory 0x1FF1E800 12
python h7tool_mcp.py --read-option-bytes ST/STM32H7xx/STM32H7x_2M.lua
python h7tool_mcp.py --protection-status ST/STM32H7xx/STM32H7x_2M.lua
```

## MCP Configuration

Example:

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

Use an absolute path that matches your local checkout.

## Configuration Files

`config.json` is local and should not be committed. Start from one of the example files:

- `config.usb-hid.example.json`
- `config.modbus-udp.example.json`
- `config.modbus-tcp.example.json`
- `config.usb-lua.example.json`

## MCP Tools

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

## Notes

Device scripts in the H7-TOOL package often describe whole chip families rather than a single exact part number. For example, searching for `STM32H743` may return a generic H7 profile. Use live target data, profile metadata, and chip-specific registers together when exact identification matters.

## Suggested Next Steps

- Improve exact chip-size identification for STM32 families.
- Generalize target probing so it can be generated from more device profiles.
- Add friendly summaries for option bytes and protection state.
- Explore RTT, UART, and CAN assistant features after their public-facing behavior is understood.
