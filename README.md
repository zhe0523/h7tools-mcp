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
- Provides bounded Lua debugging templates and an AI workflow for UART, Modbus RTU, I2C, SPI, and CAN experiments.
- Provides an offline Lua draft workspace to create, list, read, and validate drafts without executing them.
- Reviews Lua drafts statically and can run validated drafts only after explicit execution confirmation.
- Provides a dangerous-action policy gate for future programming, erase, unlock, protection, power, persistent-storage, and register-state changes.
- Provides programming preflight checks for firmware file hash, size, start address, target profile, flash metadata, and dangerous-action policy. It does not program hardware.
- Generates redacted Markdown diagnostic reports for forum posts, issues, handoff, or session archiving.
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
python h7tool_mcp.py --lua-template-library
python h7tool_mcp.py --lua-template-library spi_jedec_id
python h7tool_mcp.py --lua-debug-workflow "read SPI Flash JEDEC ID" --lua-debug-interface spi
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

`config.json` is intentionally ignored by git because it contains local device settings.

Routine debugging actions are available by default, including device queries, target reads, bus transactions, RTT reads, and non-destructive Lua drafts. Dangerous actions are disabled by default. Programming, erase, unlock, protection changes, power-control, persistent storage changes, and register-state changes must check `dangerous_actions` in `config.json` and require the matching confirmation phrase on each request.

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

Verified private HID/Modbus entry points and their safety boundaries are documented in Chinese here: [H7-TOOL V2.33 未公开固件接口](docs/undocumented-firmware-interfaces.zh-CN.md).

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
Use h7tool lua_draft_review to classify a Lua draft as non-destructive or dangerous before running it.
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
3. When Lua-assisted debugging is useful, ask it to call `lua_debug_workflow` and `lua_template_library` to create a small draft.
4. Ask it to call `lua_draft_review`; non-destructive debugging drafts can be run with `lua_draft_run` and `execute=true`.
5. Ask it to run `lua_health`, `health_summary`, or `target_summary` for hardware state checks.
6. Ask for focused memory, option-byte, RTT, or peripheral transactions only after the target profile is selected.
7. Before programming, erase, protection, or other dangerous actions, ask it to call `programming_preflight` or `dangerous_action_plan`.
8. At the end of a session, ask it to call `diagnostic_report` for a redacted Markdown summary.

## Available MCP Tools

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

## Notes

Device scripts in the H7-TOOL package often describe whole chip families rather than one exact part number. For example, searching for `STM32H743` may return a generic STM32H7 profile. Use live target data, profile metadata, and chip-specific registers together when exact identification matters.

Only one program should actively control the same H7-TOOL operation path at a time. If an AI call times out or returns an unexpected result, close conflicting operations in the PC tool and try again.

### Native target-memory reads and mode switching

With `adapter.type=h7tool_hid`, `read_memory` accepts a `transport` selector:

- `lua` (default) preserves the existing Lua `pg_read_mem` path;
- `native` calls private function `0x66` directly, using subfunction 0 to initialise the debug link for the first chunk and subfunction 1 for subsequent chunks, bypassing the Lua VM.

The native path still needs the correct target/programmer profile to be loaded, a powered target, and a valid SWD/SWIM connection. Otherwise the device returns a non-zero `status`. The current bridge supports one target channel; the firmware's multi-SWD response layout is not exposed yet.

`tool_mode_switch` is a whitelist around register `0xFF7F`. It only accepts `restart_app`, `emmc`, and `link`, and requires the configured dangerous-action `power` level plus confirmation phrase. HID may disconnect or re-enumerate immediately after the request. Bootloader, DAP, offline programming, arbitrary register writes, and calibration controls are deliberately not exposed.


### Reading and writing files on the H7-TOOL

`device_file_write` and `device_file_read` move regular files to and from the tool's EMMC (`0:/`) or SD card (`1:/`).

- Writing is gated as a dangerous action: set `"dangerous_actions": {"enabled": true, "allowed_levels": ["write"], ...}` in `config.json` and pass the matching `confirmation` phrase. Reads are never gated.
- The tool's FAT stores Chinese file names as GBK, so `path_encoding` defaults to `gbk`. Pass `utf-8` if your tree is ASCII-only.
- The Lua file API has no delete, truncate, or mkdir call. The target directory must already exist, and a rewrite shorter than the previous file leaves the old tail in place; `device_file_write` reports that in `warnings`. Delete the file with the H7-TOOL PC software and write again.
- Writing while another Lua script is still running on the tool can race the Lua reset that function `0x64` performs, which lands a wrong image. `verified: false` means exactly that: press **C** on the tool so no script is running, then write again. A verified write on an idle tool is byte-exact.
- Writes larger than 16 KiB, and writes crossing a 4 KiB page, are both handled internally: one `f_write` call rejects a payload above 16 KiB, and the tool duplicates a single byte when one call crosses a 4096-byte page from an unaligned offset.
- A Lua script itself is no longer limited to roughly 1000 bytes. Function `0x64` carries `(total length, offset, chunk length)`, so the bridge streams a large script across several 1024-byte HID reports.

### When a Lua call returns no output

The tool occasionally acknowledges a `function 0x64` (download/execute Lua) request and then neither runs the script nor prints anything, while `tool_status` and other register reads keep working. Press **C** on the H7-TOOL (or power-cycle it) to clear the wedged Lua session, then retry.

The bridge already retries read-only and idempotent calls once, and `lua_draft_run` accepts `retry_on_empty: true` for a script that is safe to run twice.

Relevant `adapter` settings:

| Key | Default | Meaning |
|---|---|---|
| `timeout_ms` | `20000` in the shipped examples | Whole window one Lua call may take |
| `print_quiet_ms` | `500` | How long output may stay quiet before a script without markers counts as finished |
| `lua_chunk_bytes` | `700` | HID report payload used to stream a script; must stay under 1000 |
| `lua_chunk_delay_ms` | `4` | Pause between script chunks |
| `drain_before_run_ms` | `150` | Print polling done before a run, so leftovers are not reported as its output |

## Screenshot

`screenshot` captures the H7-TOOL's own LCD and writes it as a PNG.

- function `0x66`, subfunction `0x0100` (`H66_READ_DISP_MEM`): the firmware
  `memcpy`s straight out of the framebuffer at `0x30000000`.
- the payload is raw RGB565 little-endian, row major, top-left origin, stride = panel
  width, no compression: 153600 bytes for a 240x320 panel.
- `offset` is an absolute byte offset, so a frame is read by walking `offset += chunk`
  until `width * height * 2` bytes arrive. There is no end marker and no sequence number.
- 1009 bytes is the largest chunk that fits one 1024-byte HID report; a whole frame took
  about 0.26 s on APP V2.33.

Two things learned the hard way: claim HID interface 2 exclusively (close the vendor PC
application first), and drain the stale IN reports after opening - a Lua program that
redraws the panel leaves hundreds queued, and unrelated frames such as `01 61 ...` Lua
print frames share the same pipe, so match unit + function + subfunction + offset +
length + CRC rather than the function byte alone.

### Binary-safe file writes

`device_file_write` sends each piece base64 encoded. A Lua long string can hold NUL
bytes, but the firmware passes the whole script to `luaL_dostring()` as a C string, so a
single NUL inside an embedded piece truncates the script and every later write silently
does nothing.

## EMMC file management (native channel)

Function `0x64` carries file management in its `func` field - the same frame the Lua
download uses - so files can be listed, deleted and created while the DAP/debug
interface stays alive. The Lua layer cannot do this: `f_dir` crashes the firmware and
`os.remove`/`os.rename` are silent no-ops.

| func | tool | notes |
|---|---|---|
| 2 | `device_file_list` | line format `F<hex size>|<date> <time>|<name>`, `D` = directory |
| 3 | `device_file_md5` | plain MD5, verified against hashlib |
| 4 | `device_file_delete` | gated as dangerous level `write` |
| 6 | read | reply `total(4) offset(4) bytes(4) data` |
| 7 | write | payload `size(4) md5(16) name_len(1) full path data` |
| 8 | `device_file_mkdir` | 0 = created, 1 = already there |

Firmware quirks the client must handle:

- the reply starts `func(2) result(1) total(4) offset(4) package_len(4) data`; skipping the
  result byte shifts every later field by one;
- `LIST` and `READ` never NUL-terminate the path they receive (`DEL` and `MD5` do);
- `LIST` rejects a trailing slash and then returns an empty listing;
- `LIST` reuses the request's `package_len` as its own reply length, so the payload must be
  NUL padded to fetch a whole chunk;
- a request may only be written once: re-sending a `WRITE_FILE` packet buffers the same
  bytes twice and doubles the file;
- `DEL_DIR` (5) is declared but unimplemented in the firmware.

## Wireless (LAN) mode

The H7-TOOL does not have to be on USB. Everything the file tools need also works over the
tool's legacy UDP transport, so the MCP can drive it purely over the network.

Copy `config.wireless.json` over `config.json` (or point the server at it) and set your
tool's address:

```json
{
  "adapter": {
    "type": "modbus_udp",
    "host": "192.168.1.13",
    "port": 30010,
    "unit_id": 1,
    "timeout_ms": 8000
  }
}
```

The tool's IP can be read from its own registers without any connection: `0x1102`/`0x1103`
hold the local IP (`192.168` / `1.13`), `0x1104`/`0x1105` the gateway, `0x1106`/`0x1107`
the subnet mask.

### What works over the wireless link

| Feature | Wireless (UDP) |
|---|---|
| Holding-register reads (`tool_registers`) | yes - 512-register sweep, no lost replies |
| `device_file_list` / `device_file_md5` | yes |
| `device_file_mkdir` / `device_file_delete` | yes |
| `device_file_read` / `device_file_write` | yes (verified byte-exact against the device's own MD5) |
| Lua download / run (`lua_draft_run`, scripted runs) | yes - same 0x64 channel |
| `screenshot` (0x66 display read) | yes - but the length field must be **u32**; a 16-bit length is silently ignored (this looked like "HID only" at first) |
| Lua download + run + print channel (`0x64` func 0, `0x61` poll) | **yes** - verified: a script's `print` came back over UDP |
| Script-driven tools (`uart_transact`, `can_transact`, `i2c_transact`, `spi_transact`, `rtt_read`, `health_summary`, target/protection helpers) | **yes** - `_script_adapter()` routes them through `ModbusUdpAdapter.run_lua_script`, which mirrors the USB chunking and print-polling |

### Transport facts worth knowing

**Every wireless request needs the session poll first.** V2.33 expects five `0x61` channel
poll frames before the real request; without them only requests that happen to arrive while
a session from an earlier call is still alive get answered. `session_poll` (default true)
in the adapter config controls this. This is what made the display read look "HID only" -
with the poll in place the full 240x320 framebuffer reads back over UDP in 153 slices.

* **Only UDP works.** The tool opens no TCP listener (8080/502 refuse connections) and
  speaks standard **Modbus RTU over UDP on port 30010**, with the usual low-byte-first
  CRC16. Frames sent without a CRC simply time out.
* **The whole custom 0x64 file API runs on this transport**, including writes. It is the
  same frame layout as the USB path; only the wrapping differs.
* `0x64` **func 5 (delete directory) is not implemented** - it answers `0xFF` (invalid
  function). To delete a directory, use **func 4 (DEL_FILE)**, which removes empty
  directories as well as files.
* **Paths must be NUL-terminated.** The firmware does not terminate them itself: without
  the NUL it reads past the string and creates entries whose names have trailing garbage
  from the buffer - and those can then no longer be found by their intended name. This bit
  the file tools until `_native_path()` was introduced.
* `device_file_read` may return 0 bytes immediately after a write (the FAT entry has not
  flushed yet). The tool retries; direct users of the protocol should do the same.

### Register note

Sweeping works over UDP too: 512 consecutive single-register reads finished in about 11 s
with **zero** lost replies, as long as each request is preceded by the session poll (the
adapter does that automatically). Earlier "bulk reads hang" observations were caused by the
tool being asleep, or by a request sent without opening the session - not by the transport.

### Wireless frame details (verified on APP V2.33)

* `0x66` display read: `unit | 0x66 | 0x0100:u16 | offset:u32 | length:**u32** | crc16le`.
  The length is 32-bit. With a 16-bit length the tool ignores the request, which makes it
  look like the feature is not available on this transport - it is.
* `0x64` func 0 (Lua download/run) and `0x61` (print poll) answer over UDP as well, so the
  script-driven debugging helpers are not limited to USB.
