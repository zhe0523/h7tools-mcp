# H7-TOOL read-only diagnostic MCP bridge

This is a read-only MCP server intended for **diagnosis only**.
It deliberately exposes no erase, flash, reset, power-control, GPIO-write, or
protection-changing tool. It does not reverse engineer or assume H7-TOOL's
private protocol.

## What works today

- A compliant stdio MCP handshake plus `tools/list` and `tools/call`.
- `bridge_status`, which lists local serial devices and the discovered H7-TOOL
  HID interfaces without touching the tool.
- Safe mock-mode tests.
- A `modbus_tcp` adapter which implements only Modbus function `0x03` (read
  holding registers). Its packet framing and V1.49 register map come from the
  included historical open-source H7-TOOL firmware.
- A `modbus_udp` adapter implementing read-only function `0x03` over the
  current V2.33 UDP/30010 Modbus RTU framing (standard low-byte-first CRC).
- A verified V2.33 `h7tool_hid` adapter for the current H7-TOOL USB HID
  Communication interface: VID:C251/PID:F00A, interface 2. It implements
  only Modbus function `0x03` reads using 1024-byte HID payload reports.
- A verified HID Lua diagnostics path for the bundled fixed
  `diagnostics/tool_health.lua`: function `0x64` downloads/runs the script and
  function `0x61` is polled over HID to collect `print()` output.

The hardware-facing commands are intentionally disabled until their exact
syntax and response framing are confirmed with the real device.

## Run today

Use the bundled Python:

```powershell
$py = 'C:\Users\zhe\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py .\mcp\h7tool_mcp.py --self-test
& $py .\mcp\h7tool_mcp.py --list-serial-ports
```

The verified V2.33 path is Ethernet/WiFi to UDP/30010. In the vendor app,
select Ethernet/WiFi, then use the current local configuration:

```powershell
& $py .\mcp\h7tool_mcp.py --config .\mcp\config.json --probe-h7tool
& $py .\mcp\h7tool_mcp.py --config .\mcp\config.json --health-summary
& $py .\mcp\h7tool_mcp.py --config .\mcp\config.json --tool-registers 0x0400 6
```

For the USB HID path, close the vendor PC application if it is actively using
the same HID Communication interface, then use:

```powershell
Copy-Item .\mcp\config.usb-hid.example.json .\mcp\config.json -Force
& $py .\mcp\h7tool_mcp.py --config .\mcp\config.json --probe-h7tool
& $py .\mcp\h7tool_mcp.py --config .\mcp\config.json --lua-health
```

For an Ethernet device with its LAN interface actually enabled, configure a
Modbus adapter and test it before adding it to an MCP client:

```powershell
& $py .\mcp\h7tool_mcp.py --config .\mcp\config.json --probe-h7tool
```

To run it in an MCP client, use this server configuration (adjust the Python
path if the bundled runtime changes):

```json
{
  "mcpServers": {
    "h7tool": {
      "command": "C:\\Users\\zhe\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe",
      "args": ["E:\\软件\\绿色软件\\h7toolPC_release\\mcp\\h7tool_mcp.py"]
    }
  }
}
```

Mock/TCP/UDP modes use only the standard library. USB HID requires `hidapi`,
which is included in `requirements.txt`.

## Tomorrow's validation sequence

1. Connect the Ethernet cable and set the vendor PC application to
   Ethernet/WiFi. The validated endpoint is `192.168.3.33:30010` and this PC
   is `192.168.3.4/24`.
2. Run `--probe-h7tool`. It sends a V2.33 read-only UDP session poll followed
   by function-`0x03` reads; it has been verified against this device.
3. Compare the UID, hardware version, and app version with the vendor screen.
   The expected current values are UID `003C001E3232511736303936`, hardware
   `0x0752`, and app `2.33`.
4. Add the MCP server and call `tool_status` or bounded `tool_registers`.
   Call `health_summary` for a conservative, AI-friendly assessment of H7-TOOL
   itself. All three tools are read-only.

## Configuration

`config.json` is intentionally not provided because it may contain LAN
addresses and locally verified command strings; do not commit it to version
control. The allowed adapter types:

- `mock`: no hardware access; used by default and in self-tests.
- `modbus_tcp`: standard Modbus TCP read-only access to H7-TOOL. This is the
  recommended LAN adapter for the first device test.
- `modbus_udp`: legacy H7-TOOL Modbus RTU-over-UDP transport, default port
  30010. It uses an unicast frame; the older MAC-prefixed broadcast discovery
  protocol is intentionally not enabled.
- `tcp`: opens one configured TCP connection per request and sends a single
  configured line.
- `serial`: opens one configured COM port per request and sends a single
  configured line; requires `pyserial`.
- `h7tool_hid`: verified current USB transport. It selects only the
  vendor-defined `H7-TOOL HID Communication` interface and provides only
  function-`0x03` read access plus the fixed bundled `tool_health.lua`
  diagnostic runner and fixed bundled STM32H7 target UID probe. It is verified
  with V2.33 using 1024-byte reports and standard low-byte-first Modbus CRC.
  Close the vendor PC application before use if it otherwise owns the same HID
  reports.

The `commands` values are Python format templates. Only the following
read-oriented names are accepted by the bridge: `status`, `target_probe`,
`target_identity`, `read_memory`, `uart_tail`, `rtt_tail`, and `can_tail`.

`read_memory` is capped at 1024 bytes and logs are capped at 200 lines by
default. With `h7tool_hid`, `read_memory` uses a generated read-only Lua
template containing only validated numeric address/length values and calls
`pg_read_mem`; MCP callers cannot provide arbitrary Lua. Changing those limits
does not permit any write action.

## Health summary

`health_summary` evaluates only H7-TOOL's own TVCC and USB 5V supplies using
conservative ranges, and reports an NTC value outside -40..125 C as unknown
(commonly an unconnected sensor), rather than a hardware fault. Target-facing
measurements such as CH1/CH2 and high-side voltage/current are observations:
zero may be correct when no target is connected.

The Modbus status decoder reads the legacy V1.49 identity and analog register
map: device ID `0x0000..0x0005`, model/version and GPIO `0x0006..0x000B`, and
calibrated measurements `0x000C..0x001F`. It labels the result as compatibility
data because the connected V2.33 firmware must be checked before relying on
the field meanings.

## Boundaries and next step

The verified V2.33 UDP transport uses standard low-byte-first Modbus CRC and
a five-frame `0x61` read-only channel poll before register reads. The device
adds one zero padding byte to some replies; the bridge strips it based on the
function-`0x03` byte count.

The verified V2.33 HID Lua flow mirrors the vendor PC "Download" action: send
one padded 1024-byte HID payload containing function `0x64`, then poll channels
0..4 with function `0x61` until the fixed script's `H7TOOL_DIAG_END` marker is
seen. The MCP bridge does not accept caller-provided Lua.

`target_probe` over `h7tool_hid` uses the same fixed-script path with
`diagnostics/target_probe_stm32h7.lua`. It is read-only and mirrors the manual
Programmer test for an STM32H7x target: initialize the SWD programmer link,
read IDCODE when available, and read 12 UID bytes from `0x1FF1E800`.

`target_identity` combines that live read-only probe with local H7-TOOL device
Lua metadata. By default it reads the bundled
`EMMC/H7-TOOL/Programmer/Device/ST/STM32H7xx/STM32H7x_2M.lua` profile and
returns the selected vendor, series, device, expected IDCODE, UID location,
memory base addresses, and configured FLM algorithm entries. To point it at a
different local H7-TOOL device script, either pass `relative_path` to
`target_identity` or set `adapter.target_lua_path` in `config.json`.

The device-library tools (`device_vendors`, `device_search`, `device_profile`,
and `device_capabilities`) index only local files under
`EMMC/H7-TOOL/Programmer/Device`; they do not contact hardware. Search skips
shared `Lib` scripts by default and treats `x` in device-script names as a
loose wildcard, so a query such as `STM32H743` can find the generic
`STM32H7x_2M.lua` profile. `device_capabilities` also follows the profile's
`IncludeList` and reports inferred read-only capabilities separately from
dangerous write, erase, power, reset, or protection-changing code paths.
