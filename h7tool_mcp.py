#!/usr/bin/env python3
"""A local MCP assistant server for H7-TOOL development workflows.

The server exposes H7-TOOL status, local device-library search, target
identification, and focused diagnostic reads to MCP-compatible AI clients.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import socket
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SERVER_NAME = "h7tool-mcp-assistant"
SERVER_VERSION = "0.3.0"
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
DEVICE_ROOT = Path(__file__).resolve().parent.parent / "EMMC" / "H7-TOOL" / "Programmer" / "Device"
DEFAULT_TARGET_LUA = DEVICE_ROOT / "ST" / "STM32H7xx" / "STM32H7x_2M.lua"


class BridgeError(Exception):
    """An expected, user-actionable bridge error."""


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "adapter": {"type": "mock"},
            "commands": {},
            "limits": {"max_read_memory_bytes": 1024, "max_log_lines": 200},
        }
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(f"Cannot read configuration {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise BridgeError("Configuration root must be a JSON object")
    config.setdefault("adapter", {"type": "mock"})
    config.setdefault("commands", {})
    config.setdefault("limits", {})
    config["limits"].setdefault("max_read_memory_bytes", 1024)
    config["limits"].setdefault("max_log_lines", 200)
    return config


def parse_response(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return {"raw": "", "format": "empty"}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text, "format": "text"}
    return {"raw": text, "format": "json", "data": parsed}


def parse_target_probe_output(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace").strip()
    data: dict[str, Any] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key in {"idcode", "cpuid", "uid_address"} and value.lower().startswith("0x"):
            data[key] = value.upper().replace("X", "x")
        elif key in {"uid_length", "uid_read"}:
            try:
                data[key] = int(float(value))
            except ValueError:
                data[key] = value
        elif key == "uid":
            parts = [part.upper() for part in value.split() if part]
            data["uid_hex"] = " ".join(parts)
            data["uid_bytes"] = parts
        elif key in {"pg_init", "jtag2swd"}:
            data[key] = value
    connected = False
    uid_read = data.get("uid_read")
    if uid_read == 1:
        connected = True
    for key in ("idcode", "cpuid"):
        value = data.get(key)
        if isinstance(value, str) and value not in {"0x00000000", "unavailable"}:
            connected = True
    data["connected"] = connected
    return {"raw": text, "format": "h7tool_target_probe", "data": data}


def parse_read_memory_output(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace").strip()
    data: dict[str, Any] = {}
    chunks: list[tuple[int, list[str]]] = []
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "address" and value.lower().startswith("0x"):
            data["address"] = value.upper().replace("X", "x")
        elif key in {"length", "read"}:
            try:
                data[key] = int(float(value))
            except ValueError:
                data[key] = value
        else:
            match = re.fullmatch(r"data\[(\d+)\]", key)
            if match:
                chunks.append((int(match.group(1)), [part.upper() for part in value.split() if part]))
    memory_bytes: list[str] = []
    for _offset, parts in sorted(chunks, key=lambda item: item[0]):
        memory_bytes.extend(parts)
    if memory_bytes:
        data["data_hex"] = " ".join(memory_bytes)
        data["data_bytes"] = memory_bytes
    data["ok"] = data.get("read") == 1 and len(memory_bytes) == data.get("length")
    return {"raw": text, "format": "h7tool_read_memory", "data": data}


def parse_option_bytes_output(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace").strip()
    data: dict[str, Any] = {"entries": []}
    entries: list[dict[str, Any]] = data["entries"]
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "read_count":
            try:
                data["read_count"] = int(float(value))
            except ValueError:
                data["read_count"] = value
            continue
        match = re.fullmatch(r"ob\[(\d+)\]", key)
        if match:
            parts = value.split()
            if len(parts) >= 3:
                entries.append(
                    {
                        "index": int(match.group(1)),
                        "address": parts[0].upper().replace("X", "x"),
                        "read": _parse_lua_number(parts[1]),
                        "value": parts[2].upper(),
                    }
                )
    data["ok"] = bool(entries) and len(entries) == data.get("read_count") and all(entry.get("read") == 1 for entry in entries)
    data["data_hex"] = " ".join(str(entry["value"]) for entry in entries)
    return {"raw": text, "format": "h7tool_option_bytes", "data": data}


def _parse_lua_number(value: str) -> int | str:
    try:
        return int(float(value))
    except ValueError:
        return value


def _safe_int_expr(expr: str) -> int | None:
    """Evaluate the small integer expressions used in H7-TOOL Lua metadata."""
    try:
        node = ast.parse(expr.strip(), mode="eval").body
    except SyntaxError:
        return None

    def walk(item: ast.AST) -> int:
        if isinstance(item, ast.Constant) and isinstance(item.value, int):
            return item.value
        if isinstance(item, ast.UnaryOp) and isinstance(item.op, ast.USub):
            return -walk(item.operand)
        if isinstance(item, ast.BinOp) and isinstance(item.op, (ast.Add, ast.Sub, ast.Mult)):
            left = walk(item.left)
            right = walk(item.right)
            if isinstance(item.op, ast.Add):
                return left + right
            if isinstance(item.op, ast.Sub):
                return left - right
            return left * right
        raise ValueError("unsupported expression")

    try:
        return walk(node)
    except ValueError:
        return None


def parse_lua_target_profile(script_path: Path, text: str) -> dict[str, Any]:
    def string_value(name: str) -> str | None:
        match = re.search(rf"(?m)^\s*{name}\s*=\s*\"([^\"]*)\"", text)
        return match.group(1) if match else None

    def int_value(name: str) -> int | None:
        match = re.search(rf"(?m)^\s*{name}\s*=\s*([^\r\n-]+)", text)
        return _safe_int_expr(match.group(1).strip()) if match else None

    def string_assignment(name: str) -> str | None:
        match = re.search(rf"(?ms)^\s*{name}\s*=\s*(?P<body>.*?)(?:\n\s*[A-Za-z_][A-Za-z0-9_]*\s*=|\n\s*end\b)", text)
        if not match:
            return None
        body = match.group("body")
        return " ".join(re.findall(r"\"([0-9A-Fa-fxX\s]+)\"", body))

    def int_table(name: str) -> list[int]:
        match = re.search(rf"(?ms)^\s*{name}\s*=\s*\{{(?P<body>.*?)\}}", text)
        if not match:
            return []
        values: list[int] = []
        for token in re.findall(r"0x[0-9A-Fa-f]+|\d+", match.group("body")):
            try:
                values.append(int(token, 0))
            except ValueError:
                continue
        return values

    include_list: list[str] = []
    include_match = re.search(r"IncludeList\s*=\s*\{(?P<body>.*?)\}", text, flags=re.S)
    if include_match:
        include_list = re.findall(r"\"(0:/H7-TOOL/Programmer/Device/[^\"]+)\"", include_match.group("body"))
    algo_entries: list[dict[str, Any]] = []
    algo_list = re.search(r"AlgoFile_List\s*=\s*\{(?P<body>.*?)\}", text, flags=re.S)
    if algo_list:
        for match in re.finditer(r"\"([A-Za-z0-9_]+)\"\s*,\s*([^,\n]+)\s*,\s*([^,\n]+)", algo_list.group("body")):
            variable, address_expr, size_expr = match.groups()
            algo_entries.append(
                {
                    "variable": variable,
                    "file": string_value(variable),
                    "address": _format_hex(_safe_int_expr(address_expr), 8),
                    "size_bytes": _safe_int_expr(size_expr),
                }
            )
    uid_addr = int_value("UID_ADDR")
    uid_bytes = int_value("UID_BYTES")
    mcu_id = int_value("MCU_ID")
    ob_address = string_assignment("OB_ADDRESS")
    wrp_addresses = int_table("OB_WRP_ADDRESS")
    wrp_masks = int_table("OB_WRP_MASK")
    wrp_values = int_table("OB_WRP_VALUE")
    protection_checks = [
        {
            "address": _format_hex(address, 8),
            "mask": _format_hex(wrp_masks[index] if index < len(wrp_masks) else None, 2),
            "unprotected_value": _format_hex(wrp_values[index] if index < len(wrp_values) else None, 2),
        }
        for index, address in enumerate(wrp_addresses)
    ]
    return {
        "source": str(script_path),
        "relative_path": _relative_device_path(script_path),
        "vendor": script_path.parts[-3] if len(script_path.parts) >= 3 else None,
        "series": script_path.parent.name,
        "device": script_path.stem,
        "chip_type": string_value("CHIP_TYPE"),
        "expected_idcode": _format_hex(mcu_id, 8),
        "uid_address": _format_hex(uid_addr, 8),
        "uid_length": uid_bytes,
        "flash_address": _format_hex(int_value("FLASH_ADDRESS"), 8),
        "ram_address": _format_hex(int_value("RAM_ADDRESS"), 8),
        "algorithm_ram_address": _format_hex(int_value("AlgoRamAddr"), 8),
        "algorithm_ram_size_bytes": int_value("AlgoRamSize"),
        "option_byte_addresses": parse_ob_address_string(ob_address) if ob_address else [],
        "protection_checks": protection_checks,
        "include_list": include_list,
        "algorithm_files": algo_entries,
    }


def parse_ob_address_string(value: str) -> list[str]:
    addresses: list[str] = []
    for token in re.findall(r"[0-9A-Fa-f]{8}", value):
        addresses.append(f"0x{int(token, 16):08X}")
    return addresses


def _relative_device_path(script_path: Path) -> str | None:
    try:
        return script_path.resolve().relative_to(DEVICE_ROOT.resolve()).as_posix()
    except ValueError:
        return None


def _format_hex(value: int | None, width: int = 0) -> str | None:
    if value is None:
        return None
    return f"0x{value:0{width}X}" if width else f"0x{value:X}"


def _h7tool_device_path(path_text: str) -> Path | None:
    prefix = "0:/H7-TOOL/Programmer/Device/"
    if not path_text.startswith(prefix):
        return None
    return DEVICE_ROOT / path_text[len(prefix) :]


def read_target_profile(config: dict[str, Any]) -> dict[str, Any]:
    adapter_config = config.get("adapter", {})
    configured_path = adapter_config.get("target_lua_path") if isinstance(adapter_config, dict) else None
    script_path = Path(configured_path) if isinstance(configured_path, str) and configured_path else DEFAULT_TARGET_LUA
    try:
        text = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise BridgeError(f"Cannot read target Lua profile {script_path}: {exc}") from exc
    return parse_lua_target_profile(script_path, text)


def read_selected_target_profile(config: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    if any(key in arguments for key in ("relative_path", "vendor", "series", "device")):
        return read_device_profile(arguments)
    return read_target_profile(config)


def _device_lua_files() -> list[Path]:
    if not DEVICE_ROOT.exists():
        raise BridgeError(f"H7-TOOL device library not found: {DEVICE_ROOT}")
    return sorted(path for path in DEVICE_ROOT.rglob("*.lua") if path.is_file())


def device_vendors() -> dict[str, Any]:
    vendors: dict[str, int] = {}
    for path in _device_lua_files():
        try:
            vendor = path.relative_to(DEVICE_ROOT).parts[0]
        except (ValueError, IndexError):
            continue
        vendors[vendor] = vendors.get(vendor, 0) + 1
    return {
        "device_root": str(DEVICE_ROOT),
        "total_lua": sum(vendors.values()),
        "vendors": [{"vendor": name, "lua_count": count} for name, count in sorted(vendors.items())],
    }


def _device_summary(path: Path) -> dict[str, Any]:
    relative = _relative_device_path(path)
    parts = Path(relative).parts if relative is not None else ()
    return {
        "vendor": parts[0] if len(parts) >= 1 else None,
        "series": parts[-2] if len(parts) >= 2 else None,
        "device": path.stem,
        "relative_path": relative,
    }


def _query_matches_device(query: str, summary: dict[str, Any], path: Path) -> bool:
    normalized_query = re.sub(r"[^a-z0-9]+", "", query.lower())
    haystack = " ".join(str(value) for value in summary.values() if value is not None).lower()
    if query.strip().lower() in haystack:
        return True
    compact_values = [re.sub(r"[^a-z0-9]+", "", str(value).lower()) for value in summary.values() if value is not None]
    if normalized_query and any(normalized_query in value for value in compact_values):
        return True
    for value in compact_values:
        for token in re.findall(r"[a-z0-9]*x[a-z0-9]*", value):
            pattern = "^" + re.escape(token).replace("x", "[a-z0-9]*") + "$"
            if re.fullmatch(pattern, normalized_query):
                return True
    try:
        sample = path.read_text(encoding="utf-8", errors="replace")[:8192].lower()
    except OSError:
        return False
    return query.strip().lower() in sample


def search_device_library(
    query: str,
    vendor: str | None = None,
    limit: int = 50,
    include_libraries: bool = False,
) -> dict[str, Any]:
    normalized_query = query.strip().lower()
    normalized_vendor = vendor.strip().lower() if isinstance(vendor, str) and vendor.strip() else None
    if limit < 1 or limit > 200:
        raise BridgeError("limit must be between 1 and 200")
    matches: list[dict[str, Any]] = []
    for path in _device_lua_files():
        summary = _device_summary(path)
        if not include_libraries and summary.get("series") == "Lib":
            continue
        haystack = " ".join(str(value) for value in summary.values() if value is not None).lower()
        if normalized_vendor and str(summary.get("vendor", "")).lower() != normalized_vendor:
            continue
        if normalized_query and not _query_matches_device(query, summary, path):
            continue
        matches.append(summary)
        if len(matches) >= limit:
            break
    return {
        "device_root": str(DEVICE_ROOT),
        "query": query,
        "vendor": vendor,
        "limit": limit,
        "include_libraries": include_libraries,
        "matches": matches,
        "returned": len(matches),
    }


def resolve_device_script(arguments: dict[str, Any]) -> Path:
    relative_path = arguments.get("relative_path")
    if isinstance(relative_path, str) and relative_path.strip():
        candidate = (DEVICE_ROOT / relative_path).resolve()
        try:
            candidate.relative_to(DEVICE_ROOT.resolve())
        except ValueError as exc:
            raise BridgeError("relative_path must stay inside the H7-TOOL device library") from exc
        if candidate.suffix.lower() != ".lua":
            raise BridgeError("relative_path must point to a .lua file")
        if not candidate.exists():
            raise BridgeError(f"Device Lua file not found: {relative_path}")
        return candidate
    vendor = arguments.get("vendor")
    series = arguments.get("series")
    device = arguments.get("device")
    if all(isinstance(value, str) and value.strip() for value in (vendor, series, device)):
        candidate = (DEVICE_ROOT / str(vendor) / str(series) / f"{device}.lua").resolve()
        try:
            candidate.relative_to(DEVICE_ROOT.resolve())
        except ValueError as exc:
            raise BridgeError("device path must stay inside the H7-TOOL device library") from exc
        if not candidate.exists():
            raise BridgeError(f"Device Lua file not found: {vendor}/{series}/{device}.lua")
        return candidate
    raise BridgeError("Provide relative_path, or vendor + series + device")


def read_device_profile(arguments: dict[str, Any]) -> dict[str, Any]:
    script_path = resolve_device_script(arguments)
    try:
        text = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise BridgeError(f"Cannot read device Lua profile {script_path}: {exc}") from exc
    return parse_lua_target_profile(script_path, text)


def _read_lua_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise BridgeError(f"Cannot read Lua file {path}: {exc}") from exc


def _function_names(text: str) -> list[str]:
    names = re.findall(r"(?m)^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)
    return sorted(set(names))


def _assigned_names(text: str) -> set[str]:
    return set(re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", text))


def _contains_any(text: str, patterns: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.I):
            found.append(pattern)
    return found


def device_capabilities(arguments: dict[str, Any]) -> dict[str, Any]:
    script_path = resolve_device_script(arguments)
    main_text = _read_lua_text(script_path)
    profile = parse_lua_target_profile(script_path, main_text)
    sources: list[dict[str, Any]] = [
        {
            "kind": "device",
            "path": str(script_path),
            "relative_path": _relative_device_path(script_path),
        }
    ]
    combined_parts = [main_text]
    for include in profile.get("include_list", []):
        if not isinstance(include, str):
            continue
        include_path = _h7tool_device_path(include)
        if include_path is None:
            sources.append({"kind": "include", "path": include, "available": False})
            continue
        available = include_path.exists()
        sources.append(
            {
                "kind": "include",
                "path": str(include_path),
                "relative_path": _relative_device_path(include_path),
                "available": available,
            }
        )
        if available:
            combined_parts.append(_read_lua_text(include_path))
    combined = "\n".join(combined_parts)
    functions = _function_names(combined)
    assignments = _assigned_names(combined)

    read_only: list[dict[str, Any]] = []
    dangerous: list[dict[str, Any]] = []
    notes: list[str] = []

    if profile.get("uid_address") and profile.get("uid_length"):
        read_only.append(
            {
                "name": "uid",
                "source": "UID_ADDR/UID_BYTES",
                "address": profile.get("uid_address"),
                "length": profile.get("uid_length"),
            }
        )
    if profile.get("expected_idcode") or "ReadDeviceID" in functions:
        read_only.append(
            {
                "name": "device_id",
                "source": "MCU_ID/ReadDeviceID",
                "expected_idcode": profile.get("expected_idcode"),
            }
        )
    if profile.get("flash_address"):
        read_only.append(
            {
                "name": "bounded_memory_read",
                "source": "FLASH_ADDRESS/RAM_ADDRESS metadata + pg_read_mem",
                "flash_address": profile.get("flash_address"),
                "ram_address": profile.get("ram_address"),
            }
        )
    if "OB_ADDRESS" in assignments or "OB_FILE_ADDRESS" in assignments:
        read_only.append(
            {
                "name": "option_bytes_read",
                "source": "OB_ADDRESS/OB_FILE_ADDRESS",
                "supported": True,
            }
        )
    if "OB_WRP_ADDRESS" in assignments or "MCU_CheckProtect" in functions:
        read_only.append(
            {
                "name": "protection_status_read",
                "source": "OB_WRP_ADDRESS/MCU_CheckProtect",
                "supported": True,
            }
        )
    if "MCU_ReadUID" in functions:
        read_only.append({"name": "custom_uid_read", "source": "MCU_ReadUID"})
    if "MCU_ReadOB" in functions:
        read_only.append({"name": "custom_option_bytes_read", "source": "MCU_ReadOB"})
    if "MCU_ReadOptionByte" in functions:
        read_only.append({"name": "custom_option_byte_read", "source": "MCU_ReadOptionByte"})

    dangerous_patterns = {
        "target_register_write": (r"\bpg_write(?:8|16|32)?\b",),
        "flash_or_ob_program": (r"\bpg_prog_", r"\bMCU_ProgOptionBytes\b"),
        "erase": (r"\bpg_erase_", r"\berase_chip\b"),
        "read_protect_change": (r"\bset_read_protect\b", r"\bMCU_RemoveProtect\b", r"\bRemoveProtect\b"),
        "power_or_reset_side_effect": (r"\bset_tvcc\b", r"\bpoweroff\b", r"\breset\b"),
    }
    for name, patterns in dangerous_patterns.items():
        matched = _contains_any(combined, patterns)
        if matched:
            dangerous.append({"name": name, "matched_patterns": matched})

    if dangerous:
        notes.append("Dangerous capabilities are reported for awareness only; MCP does not expose them as callable actions.")
    if any(item["name"] == "option_bytes_read" for item in read_only):
        notes.append("Option-byte read support is inferred from Lua metadata; a separate hardware read tool should still be validated per family.")

    return {
        "profile": profile,
        "sources": sources,
        "functions": functions,
        "read_only_capabilities": read_only,
        "dangerous_capabilities": dangerous,
        "notes": notes,
    }


def summarize_target_identity(identity_result: dict[str, Any], protection_result: dict[str, Any] | None = None) -> dict[str, Any]:
    identity = identity_result.get("identity", {})
    profile = identity_result.get("profile", {})
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(profile, dict):
        profile = {}
    algorithms = profile.get("algorithm_files", [])
    if not isinstance(algorithms, list):
        algorithms = []
    algorithm_summary = [
        {
            "file": item.get("file"),
            "address": item.get("address"),
            "size_bytes": item.get("size_bytes"),
        }
        for item in algorithms
        if isinstance(item, dict)
    ]
    option_byte_addresses = profile.get("option_byte_addresses", [])
    protection_checks = profile.get("protection_checks", [])
    has_option_bytes = isinstance(option_byte_addresses, list) and len(option_byte_addresses) > 0
    has_protection_checks = isinstance(protection_checks, list) and len(protection_checks) > 0
    connected = bool(identity.get("connected"))
    idcode_match = bool(identity.get("idcode_match"))
    warnings: list[str] = []
    if not connected:
        warnings.append("Target did not report a connected state.")
    if connected and not idcode_match:
        warnings.append("Live IDCODE does not match the selected profile.")
    if not algorithm_summary:
        warnings.append("Selected profile does not expose flash algorithm metadata.")
    next_tools = ["device_capabilities"]
    if connected:
        next_tools.extend(["read_memory", "target_flash_info", "read_option_bytes" if has_option_bytes else "", "protection_status" if has_protection_checks else ""])
    next_tools = [name for name in next_tools if name]
    summary: dict[str, Any] = {
        "profile": {
            "relative_path": profile.get("relative_path"),
            "vendor": profile.get("vendor"),
            "series": profile.get("series"),
            "device": profile.get("device"),
        },
        "target": {
            "connected": connected,
            "interface": identity.get("interface"),
            "idcode": identity.get("idcode"),
            "expected_idcode": identity.get("expected_idcode"),
            "idcode_match": idcode_match,
            "uid_address": identity.get("uid_address"),
            "uid_length": identity.get("uid_length"),
            "uid_hex": identity.get("uid_hex"),
        },
        "memory": {
            "flash_address": identity.get("flash_address"),
            "ram_address": identity.get("ram_address"),
            "algorithm_ram_address": profile.get("algorithm_ram_address"),
            "algorithm_ram_size_bytes": profile.get("algorithm_ram_size_bytes"),
            "flash_algorithms": algorithm_summary,
        },
        "profile_support": {
            "option_byte_address_count": len(option_byte_addresses) if isinstance(option_byte_addresses, list) else 0,
            "protection_check_count": len(protection_checks) if isinstance(protection_checks, list) else 0,
            "include_count": len(profile.get("include_list", [])) if isinstance(profile.get("include_list"), list) else 0,
        },
        "next_tools": next_tools,
        "warnings": warnings,
    }
    if protection_result is not None:
        summary["protection"] = protection_result.get("status", protection_result)
    return summary


def primary_flash_algorithm_size(profile: dict[str, Any]) -> int | None:
    flash_address = profile.get("flash_address")
    algorithms = profile.get("algorithm_files", [])
    if not isinstance(flash_address, str) or not isinstance(algorithms, list):
        return None
    for item in algorithms:
        if not isinstance(item, dict):
            continue
        if str(item.get("address", "")).upper() == flash_address.upper() and isinstance(item.get("size_bytes"), int):
            return item["size_bytes"]
    return None


def default_flash_size_register(profile: dict[str, Any]) -> int | None:
    vendor = str(profile.get("vendor", "")).upper()
    series = str(profile.get("series", "")).upper()
    if vendor == "ST" and series.startswith("STM32H7"):
        return 0x1FF1E880
    return None


def summarize_flash_info(profile: dict[str, Any], memory_result: dict[str, Any], address: int) -> dict[str, Any]:
    data = memory_result.get("result", {}).get("data", {})
    bytes_text = data.get("data_bytes", []) if isinstance(data, dict) else []
    values: list[int] = []
    if isinstance(bytes_text, list):
        for item in bytes_text[:2]:
            try:
                values.append(int(str(item), 16))
            except ValueError:
                pass
    register_kb = values[0] | (values[1] << 8) if len(values) >= 2 else None
    register_bytes = register_kb * 1024 if register_kb is not None else None
    profile_bytes = primary_flash_algorithm_size(profile)
    match = register_bytes == profile_bytes if register_bytes is not None and profile_bytes is not None else None
    warnings: list[str] = []
    if register_bytes is None:
        warnings.append("Flash size register could not be decoded.")
    if match is False:
        warnings.append("Flash size register does not match the selected profile primary flash algorithm size.")
    return {
        "profile": {
            "relative_path": profile.get("relative_path"),
            "vendor": profile.get("vendor"),
            "series": profile.get("series"),
            "device": profile.get("device"),
        },
        "register": {
            "address": _format_hex(address, 8),
            "raw_hex": data.get("data_hex") if isinstance(data, dict) else None,
            "size_kb": register_kb,
            "size_bytes": register_bytes,
        },
        "profile_flash": {
            "flash_address": profile.get("flash_address"),
            "primary_algorithm_size_bytes": profile_bytes,
            "size_match": match,
        },
        "warnings": warnings,
        "raw_read": memory_result.get("result"),
    }


def crc16_modbus(data: bytes) -> int:
    """CRC-16/MODBUS, as used by the legacy H7-TOOL USB/UDP RTU framing."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


@dataclass
class CommandAdapter:
    config: dict[str, Any]

    @property
    def kind(self) -> str:
        return str(self.config.get("type", "mock")).lower()

    def execute(self, payload: str) -> dict[str, Any]:
        if self.kind == "mock":
            return self._mock(payload)
        if self.kind == "tcp":
            return self._tcp(payload)
        if self.kind == "serial":
            return self._serial(payload)
        raise BridgeError(f"Unsupported adapter type: {self.kind}")

    def _mock(self, payload: str) -> dict[str, Any]:
        values = {
            "status": {"tool": "H7-TOOL", "mode": "mock", "connected": True, "vcc_v": 3.30},
            "target_probe": {
                "connected": True,
                "debug_port": "SWD",
                "target": "mock-cortex-m",
                "idcode": "0x2BA01477",
            },
        }
        for key, value in values.items():
            if payload.strip().lower() == key:
                return {"raw": json.dumps(value), "format": "json", "data": value}
        return {"raw": f"MOCK: command accepted: {payload}", "format": "text"}

    def _tcp(self, payload: str) -> dict[str, Any]:
        host = self.config.get("host")
        port = self.config.get("serial_port", self.config.get("port"))
        if not isinstance(host, str) or not isinstance(port, int):
            raise BridgeError("TCP adapter requires adapter.host and integer adapter.port")
        timeout_s = max(0.1, float(self.config.get("timeout_ms", 1000)) / 1000)
        ending = str(self.config.get("line_ending", "\r\n")).encode("ascii")
        try:
            with socket.create_connection((host, port), timeout=timeout_s) as client:
                client.settimeout(timeout_s)
                client.sendall(payload.encode("utf-8") + ending)
                chunks: list[bytes] = []
                deadline = time.monotonic() + timeout_s
                while time.monotonic() < deadline:
                    try:
                        data = client.recv(4096)
                    except socket.timeout:
                        break
                    if not data:
                        break
                    chunks.append(data)
                    if ending and ending in data:
                        break
        except OSError as exc:
            raise BridgeError(f"TCP request to {host}:{port} failed: {exc}") from exc
        return parse_response(b"".join(chunks))

    def _serial(self, payload: str) -> dict[str, Any]:
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BridgeError("Serial support needs pyserial: pip install pyserial") from exc
        port = self.config.get("port")
        if not isinstance(port, str):
            raise BridgeError("Serial adapter requires adapter.port, for example COM16")
        timeout_s = max(0.1, float(self.config.get("timeout_ms", 1000)) / 1000)
        baudrate = int(self.config.get("baudrate", 115200))
        ending = str(self.config.get("line_ending", "\r\n")).encode("ascii")
        try:
            with serial.Serial(port, baudrate=baudrate, timeout=timeout_s, write_timeout=timeout_s) as dev:
                dev.reset_input_buffer()
                dev.write(payload.encode("utf-8") + ending)
                dev.flush()
                response = dev.read_until(ending) if ending else dev.read(4096)
        except Exception as exc:  # pyserial exposes platform-specific exception types
            raise BridgeError(f"Serial request to {port} failed: {exc}") from exc
        return parse_response(response)


@dataclass
class LegacyH7ToolLuaSerialAdapter:
    """Run the bundled read-only health Lua script over the legacy USB COM protocol.

    The H7-TOOL V1.4.4 PC source documents function 0x64 (download/execute
    Lua) and function 0x61 (asynchronous Lua ``print`` output).  Only the
    repository's fixed ``tool_health.lua`` is sent; MCP callers cannot provide
    arbitrary Lua or any write/reset/program command.
    """

    config: dict[str, Any]

    @staticmethod
    def _frame_length(data: bytearray) -> int | None:
        """Return one complete legacy frame length, 0 for bad sync, or None."""
        if len(data) < 2:
            return None
        if data[0] != 1:
            return 0
        if data[1] == 0x64:
            return 5 if len(data) >= 5 else None
        if data[1] == 0x61:
            if len(data) < 5:
                return None
            return int.from_bytes(data[3:5], "big") + 7
        # A Modbus exception is five bytes.  It is useful to return a clear
        # error instead of blocking while a device is in an unexpected mode.
        if data[1] & 0x80:
            return 5 if len(data) >= 5 else None
        return 0

    @staticmethod
    def _valid_frame(frame: bytes) -> bool:
        return len(frame) >= 5 and crc16_modbus(frame[:-2]) == int.from_bytes(frame[-2:], "big")

    def run_health_script(self) -> dict[str, Any]:
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BridgeError(
                "H7-TOOL USB Lua support needs pyserial. Run: "
                "& $py -m pip install -r .\\mcp\\requirements.txt"
            ) from exc
        port = self.config.get("port")
        if not isinstance(port, str) or not port.strip():
            raise BridgeError("h7tool_lua_serial requires adapter.port, for example COM16")
        script_path = Path(__file__).with_name("diagnostics") / "tool_health.lua"
        try:
            script = script_path.read_bytes()
        except OSError as exc:
            raise BridgeError(f"Cannot read bundled health script: {exc}") from exc
        if b"H7TOOL_DIAG_BEGIN" not in script or b"H7TOOL_DIAG_END" not in script:
            raise BridgeError("Bundled health script failed its safety marker check")
        # H64_LUA_RUN_WITH_RESET (0) resets Lua state only, then executes the
        # script. It does not reset the target or H7-TOOL hardware.
        payload = script + (b"" if script.endswith(b"\0") else b"\0")
        request_body = struct.pack(">BBHIII", 1, 0x64, 0, len(payload), 0, len(payload)) + payload
        request = request_body + crc16_modbus(request_body).to_bytes(2, "big")
        timeout_s = max(1.0, float(self.config.get("timeout_ms", 4000)) / 1000)
        settle_s = max(0.05, float(self.config.get("settle_ms", 200)) / 1000)
        baudrate = int(self.config.get("baudrate", 115200))
        buffer = bytearray()
        output = bytearray()
        ack_seen = False
        frames = 0
        deadline = time.monotonic() + timeout_s
        last_frame_at = time.monotonic()
        try:
            with serial.Serial(port, baudrate=baudrate, timeout=0.05, write_timeout=timeout_s) as dev:
                dev.reset_input_buffer()
                dev.write(request)
                dev.flush()
                while time.monotonic() < deadline:
                    waiting = getattr(dev, "in_waiting", 0)
                    chunk = dev.read(waiting or 1)
                    if chunk:
                        buffer.extend(chunk)
                    while True:
                        frame_len = self._frame_length(buffer)
                        if frame_len is None:
                            break
                        if frame_len == 0:
                            del buffer[0]
                            continue
                        if len(buffer) < frame_len:
                            break
                        frame = bytes(buffer[:frame_len])
                        del buffer[:frame_len]
                        if not self._valid_frame(frame):
                            continue
                        frames += 1
                        last_frame_at = time.monotonic()
                        if frame[1] == 0x64:
                            if frame[2] != 0:
                                raise BridgeError(f"H7-TOOL rejected health Lua, status {frame[2]}")
                            ack_seen = True
                        elif frame[1] == 0x61 and frame[2] == 0:
                            output.extend(frame[5:-2])
                        elif frame[1] & 0x80:
                            raise BridgeError(f"H7-TOOL returned Modbus exception 0x{frame[1]:02X}")
                    text = output.decode("utf-8", errors="replace")
                    if "H7TOOL_DIAG_END" in text and time.monotonic() - last_frame_at >= settle_s:
                        break
        except BridgeError:
            raise
        except Exception as exc:  # pyserial exposes platform-specific exception types
            raise BridgeError(f"H7-TOOL USB request to {port} failed: {exc}") from exc
        text = output.decode("utf-8", errors="replace").strip()
        if not ack_seen:
            raise BridgeError(f"No H7-TOOL Lua acknowledgement from {port}; verify COM port and close the vendor app")
        if "H7TOOL_DIAG_BEGIN" not in text or "H7TOOL_DIAG_END" not in text:
            raise BridgeError(f"Lua was acknowledged but diagnostic output was incomplete: {text!r}")
        return {
            "transport": "legacy_usb_virtual_com/function_64_lua + function_61_print",
            "script": "diagnostics/tool_health.lua",
            "frames": frames,
            "result": parse_response(output),
        }


@dataclass
class ModbusTcpAdapter:
    """Read-only Modbus TCP transport used by the open-source H7-TOOL V1.49 app.

    The source shows the device accepts a normal 6-byte MBAP header followed by
    unit-id and PDU.  This adapter implements function 0x03 only.
    """

    config: dict[str, Any]
    transaction_id: int = 0

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        if not 0 <= address <= 0xFFFF or not 1 <= count <= 60:
            raise BridgeError("Modbus read address must be 0..65535 and count must be 1..60")
        host = self.config.get("host")
        port = self.config.get("port")
        if not isinstance(host, str) or not isinstance(port, int):
            raise BridgeError("modbus_tcp adapter requires adapter.host and integer adapter.port")
        unit_id = int(self.config.get("unit_id", 1))
        if not 0 <= unit_id <= 0xFF:
            raise BridgeError("adapter.unit_id must be 0..255")
        timeout_s = max(0.1, float(self.config.get("timeout_ms", 1000)) / 1000)
        self.transaction_id = (self.transaction_id + 1) & 0xFFFF
        pdu = struct.pack(">BHH", 0x03, address, count)
        request = struct.pack(">HHHB", self.transaction_id, 0, len(pdu) + 1, unit_id) + pdu
        try:
            with socket.create_connection((host, port), timeout=timeout_s) as client:
                client.settimeout(timeout_s)
                client.sendall(request)
                header = self._recv_exact(client, 6)
                response_transaction, protocol_id, length = struct.unpack(">HHH", header)
                if response_transaction != self.transaction_id or protocol_id != 0 or not 2 <= length <= 260:
                    raise BridgeError("Unexpected Modbus TCP response header")
                body = self._recv_exact(client, length)
        except BridgeError:
            raise
        except OSError as exc:
            raise BridgeError(f"Modbus TCP request to {host}:{port} failed: {exc}") from exc
        if body[0] != unit_id:
            raise BridgeError(f"Unexpected Modbus unit id in response: {body[0]}")
        response_pdu = body[1:]
        if not response_pdu:
            raise BridgeError("Empty Modbus PDU")
        if response_pdu[0] == 0x83:
            code = response_pdu[1] if len(response_pdu) > 1 else None
            raise BridgeError(f"H7-TOOL rejected holding-register read; Modbus exception {code}")
        if response_pdu[0] != 0x03 or len(response_pdu) < 2:
            raise BridgeError("Unexpected Modbus function response")
        byte_count = response_pdu[1]
        data = response_pdu[2:]
        if byte_count != count * 2 or len(data) != byte_count:
            raise BridgeError("Malformed Modbus register payload")
        return list(struct.unpack(">" + "H" * count, data))

    @staticmethod
    def _recv_exact(client: socket.socket, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            part = client.recv(remaining)
            if not part:
                raise BridgeError("Modbus TCP connection closed before the full response arrived")
            chunks.append(part)
            remaining -= len(part)
        return b"".join(chunks)


@dataclass
class ModbusUdpAdapter:
    """Read-only Modbus RTU over the legacy H7-TOOL UDP transport.

    The current V2.33 PC application sends ordinary Modbus RTU frames to
    UDP/30010, with the standard low-byte-first CRC field. A six-byte MAC
    prefix is only needed for broadcast discovery, so the bridge uses unicast
    requests to avoid unnecessary LAN traffic.
    """

    config: dict[str, Any]

    @staticmethod
    def _session_poll_frame(index: int) -> bytes:
        """V2.33 UDP channel poll observed from the vendor PC application."""
        body = bytes((1, 0x61, 0, index, 0, 0, 4, 0, 0, 0, 0, 0, 0, 0))
        return body + crc16_modbus(body).to_bytes(2, "little")

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        if not 0 <= address <= 0xFFFF or not 1 <= count <= 60:
            raise BridgeError("Modbus read address must be 0..65535 and count must be 1..60")
        host = self.config.get("host")
        port = self.config.get("port", 30010)
        if not isinstance(host, str) or not isinstance(port, int):
            raise BridgeError("modbus_udp adapter requires adapter.host and integer adapter.port")
        unit_id = int(self.config.get("unit_id", 1))
        if not 0 <= unit_id <= 0xFF:
            raise BridgeError("adapter.unit_id must be 0..255")
        timeout_s = max(0.1, float(self.config.get("timeout_ms", 1000)) / 1000)
        frame = struct.pack(">BBHH", unit_id, 0x03, address, count)
        request = frame + crc16_modbus(frame).to_bytes(2, "little")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                # V2.33 begins its UDP exchange with five channel poll frames.
                # They are read-only keepalive/receive-window requests and let
                # MCP work even when the vendor application is not running.
                if bool(self.config.get("session_poll", True)):
                    for index in range(5):
                        client.sendto(self._session_poll_frame(index), (host, port))
                client.sendto(request, (host, port))
                deadline = time.monotonic() + timeout_s
                response = b""
                while time.monotonic() < deadline:
                    client.settimeout(max(0.01, min(0.1, deadline - time.monotonic())))
                    try:
                        candidate, _peer = client.recvfrom(2048)
                    except socket.timeout:
                        continue
                    # Ignore the asynchronous 0x61 responses to the session
                    # poll and wait for the requested function-0x03 response.
                    candidate_frame = candidate[6:] if len(candidate) >= 8 and candidate[6] == unit_id else candidate
                    if len(candidate_frame) >= 2 and candidate_frame[0] == unit_id and candidate_frame[1] in {0x03, 0x83}:
                        response = candidate
                        break
                if not response:
                    raise BridgeError(f"Modbus UDP request to {host}:{port} timed out")
        except BridgeError:
            raise
        except OSError as exc:
            raise BridgeError(f"Modbus UDP request to {host}:{port} failed: {exc}") from exc
        # A broadcast request receives a six-byte MAC prefix. We send unicast,
        # but accept the prefix so captures and devices with that behavior work.
        if len(response) >= 8 and response[6] == unit_id and response[7] == 0x03:
            response = response[6:]
        if len(response) < 5:
            raise BridgeError("Truncated Modbus UDP response")
        if response[0] != unit_id:
            raise BridgeError(f"Unexpected Modbus unit id in response: {response[0]}")
        # Current V2.33 firmware appends a zero pad byte to some UDP replies.
        # Select the RTU frame length from the Modbus function payload instead
        # of treating the final datagram bytes as CRC unconditionally.
        if response[1] == 0x03:
            frame_length = 5 + response[2]
        elif response[1] == 0x83:
            frame_length = 5
        else:
            raise BridgeError("Unexpected Modbus function response")
        if len(response) < frame_length:
            raise BridgeError("Truncated Modbus UDP response")
        response = response[:frame_length]
        expected_crc = int.from_bytes(response[-2:], "little")
        if crc16_modbus(response[:-2]) != expected_crc:
            raise BridgeError("Invalid Modbus UDP response CRC")
        if response[1] == 0x83:
            code = response[2] if len(response) > 2 else None
            raise BridgeError(f"H7-TOOL rejected holding-register read; Modbus exception {code}")
        byte_count = response[2]
        data = response[3:-2]
        if byte_count != count * 2 or len(data) != byte_count:
            raise BridgeError("Malformed Modbus UDP register payload")
        return list(struct.unpack(">" + "H" * count, data))


def registers_to_float(registers: list[int], offset: int) -> float:
    return struct.unpack(">f", struct.pack(">HH", registers[offset], registers[offset + 1]))[0]


def decode_h7tool_status(identity: list[int], analog: list[int]) -> dict[str, Any]:
    """Decode the V1.49 read-only register map; newer firmware is verified at runtime."""
    if len(identity) != 12 or len(analog) != 20:
        raise ValueError("unexpected H7-TOOL status register span")
    version = identity[7]
    version_minor_bcd = version & 0xFF
    measurement_names = (
        "ch1_v",
        "ch2_v",
        "high_side_v",
        "high_side_a",
        "tvcc_v",
        "tvcc_a",
        "ntc_ohm",
        "ntc_c",
        "usb_5v",
        "external_power_v",
    )
    measurements = {name: registers_to_float(analog, index * 2) for index, name in enumerate(measurement_names)}
    return {
        "register_map": "H7-TOOL V2.33 UDP map, validated against the connected tool; field semantics beyond listed values remain compatibility data",
        "device_id_hex": "".join(f"{identity[index + 1]:04X}{identity[index]:04X}" for index in range(0, 6, 2)),
        "hardware_model": identity[6],
        "app_version_raw": f"0x{version:04X}",
        "app_version": f"{version >> 8}.{version_minor_bcd >> 4}{version_minor_bcd & 0x0F}",
        "gpio_inputs_bits": f"0x{identity[8]:04X}{identity[9]:04X}",
        "gpio_outputs_bits": f"0x{identity[10]:04X}{identity[11]:04X}",
        "measurements": measurements,
    }


def summarize_h7tool_health(status: dict[str, Any]) -> dict[str, Any]:
    """Turn the verified V2.33 status map into conservative health checks.

    This function deliberately treats target-facing readings (CH1, CH2, and
    high-side) as observations, not faults: a disconnected target can make
    those values correctly read as zero. Only H7-TOOL's own supply rails have
    bounded warnings.
    """
    measurements = status.get("measurements")
    if not isinstance(measurements, dict):
        raise BridgeError("H7-TOOL status did not contain measurement data")
    checks: list[dict[str, Any]] = []

    def bounded_check(name: str, field: str, minimum: float, maximum: float, nominal: str) -> None:
        value = measurements.get(field)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            checks.append({"name": name, "status": "unknown", "value": value, "reason": "missing or non-finite measurement"})
        elif minimum <= value <= maximum:
            checks.append({"name": name, "status": "ok", "value": value, "unit": "V", "expected": nominal})
        else:
            checks.append(
                {
                    "name": name,
                    "status": "warning",
                    "value": value,
                    "unit": "V",
                    "expected": nominal,
                    "reason": f"outside conservative range {minimum:.1f}..{maximum:.1f} V",
                }
            )

    bounded_check("tool_tvcc", "tvcc_v", 3.0, 3.6, "nominal 3.3 V")
    bounded_check("tool_usb_supply", "usb_5v", 4.5, 5.5, "nominal 5.0 V")

    ntc_c = measurements.get("ntc_c")
    if isinstance(ntc_c, (int, float)) and math.isfinite(ntc_c) and -40 <= ntc_c <= 125:
        checks.append({"name": "tool_ntc_temperature", "status": "ok", "value": ntc_c, "unit": "C"})
    else:
        checks.append(
            {
                "name": "tool_ntc_temperature",
                "status": "unknown",
                "value": ntc_c,
                "reason": "outside sensor operating range; commonly indicates an unconnected or unavailable NTC sensor",
            }
        )

    warnings = [check for check in checks if check["status"] == "warning"]
    unknown = [check for check in checks if check["status"] == "unknown"]
    overall = "warning" if warnings else "ok"
    return {
        "overall": overall,
        "device": {
            "uid": status.get("device_id_hex"),
            "hardware_model_hex": f"0x{int(status['hardware_model']):04X}" if isinstance(status.get("hardware_model"), int) else None,
            "app_version": status.get("app_version"),
        },
        "checks": checks,
        "observations": {
            "target_facing_measurements": {
                name: measurements.get(name)
                for name in ("ch1_v", "ch2_v", "high_side_v", "high_side_a", "external_power_v")
            },
            "gpio_inputs_bits": status.get("gpio_inputs_bits"),
            "gpio_outputs_bits": status.get("gpio_outputs_bits"),
        },
        "warning_count": len(warnings),
        "unknown_count": len(unknown),
        "safety": "Read-only assessment. No target or H7-TOOL setting was changed.",
    }


def list_windows_serial_ports() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    command = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "Get-CimInstance Win32_SerialPort | "
        "Select-Object DeviceID,Name,Description | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            check=False,
            capture_output=True,
            timeout=5,
        )
        output = result.stdout.decode("utf-8-sig", errors="replace")
        if result.returncode != 0 or not output.strip():
            return []
        entries = json.loads(output)
        return entries if isinstance(entries, list) else [entries]
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []


def list_h7tool_hid_devices() -> list[dict[str, Any]]:
    """Enumerate H7-TOOL HID interfaces without opening or writing to them."""
    try:
        import hid  # type: ignore[import-not-found]
    except ImportError:
        return []
    devices: list[dict[str, Any]] = []
    try:
        for item in hid.enumerate(0xC251, 0xF00A):
            devices.append(
                {
                    "vendor_id": f"0x{item['vendor_id']:04X}",
                    "product_id": f"0x{item['product_id']:04X}",
                    "interface_number": item.get("interface_number"),
                    "product": item.get("product_string"),
                    "manufacturer": item.get("manufacturer_string"),
                    "serial_number": item.get("serial_number"),
                    "usage_page": f"0x{item.get('usage_page', 0):04X}",
                    "usage": f"0x{item.get('usage', 0):04X}",
                }
            )
    except OSError:
        return []
    return devices


@dataclass
class H7ToolHidModbusAdapter:
    """Read-only Modbus RTU transport over H7-TOOL's USB HID Communication interface.

    The connected V2.33 tool exposes VID:C251/PID:F00A interface 2 with product
    name ``H7-TOOL HID Communication``. It uses 1024-byte input/output payload
    reports (plus report ID), with standard Modbus RTU low-byte-first CRC.
    HID padding is transport detail only and is not part of the Modbus frame.
    """

    config: dict[str, Any]

    def _find_interface(self) -> dict[str, Any]:
        try:
            import hid  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BridgeError("H7-TOOL USB HID support needs hidapi: & $py -m pip install -r .\\mcp\\requirements.txt") from exc
        vendor_id = int(self.config.get("vendor_id", 0xC251))
        product_id = int(self.config.get("product_id", 0xF00A))
        interface_number = int(self.config.get("interface_number", 2))
        serial_number = self.config.get("serial_number")
        candidates = [item for item in hid.enumerate(vendor_id, product_id) if item.get("interface_number") == interface_number]
        if isinstance(serial_number, str) and serial_number:
            candidates = [item for item in candidates if item.get("serial_number") == serial_number]
        if not candidates:
            raise BridgeError(
                f"H7-TOOL HID Communication interface not found (VID:PID={vendor_id:04X}:{product_id:04X}, interface {interface_number}). "
                "Connect H7-TOOL directly by USB and confirm it appears in --list-hid-devices."
            )
        if len(candidates) > 1:
            raise BridgeError("More than one matching H7-TOOL HID interface found; set adapter.serial_number in config.json")
        return candidates[0]

    @staticmethod
    def _extract_frame(report: bytes) -> bytes | None:
        """Extract one CRC-valid RTU response from a padded V2.33 HID report."""
        if len(report) < 5 or report[0] != 1:
            return None
        function = report[1]
        if function == 0x03 and len(report) >= 3:
            frame_length = 5 + report[2]
        elif function & 0x80:
            frame_length = 5
        else:
            return None
        if frame_length > len(report):
            return None
        frame = report[:frame_length]
        return frame if crc16_modbus(frame[:-2]) == int.from_bytes(frame[-2:], "little") else None

    @staticmethod
    def _report(frame: bytes) -> bytes:
        if len(frame) > 1024:
            raise BridgeError("H7-TOOL HID frame is larger than one 1024-byte payload report")
        return b"\0" + frame + b"\0" * (1025 - 1 - len(frame))

    @staticmethod
    def _extract_lua_ack(report: bytes) -> bool:
        """Return True for a V2.33 HID function-0x64 success acknowledgement."""
        if len(report) < 19 or report[0] != 1 or report[1] != 0x64:
            return False
        frame = report[:19]
        if crc16_modbus(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
            return False
        return frame[2:4] == b"\0\0"

    @staticmethod
    def _extract_lua_print(report: bytes) -> bytes | None:
        """Extract one function-0x61 print payload from a V2.33 HID report."""
        if len(report) < 10 or report[0] != 1 or report[1] != 0x61:
            return None
        text_length = int.from_bytes(report[6:8], "big")
        frame_length = 10 + text_length
        if frame_length > len(report):
            return None
        frame = report[:frame_length]
        if crc16_modbus(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
            return None
        return frame[8 : 8 + text_length]

    @staticmethod
    def _lua_poll_frame(channel: int) -> bytes:
        body = bytes([1, 0x61, 0, channel, 0, 0, 0x10, 0, 0, 0, 0, 0, 0, 0])
        return body + crc16_modbus(body).to_bytes(2, "little")

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        if not 0 <= address <= 0xFFFF or not 1 <= count <= 60:
            raise BridgeError("Modbus read address must be 0..65535 and count must be 1..60")
        try:
            import hid  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BridgeError("H7-TOOL USB HID support needs hidapi: & $py -m pip install -r .\\mcp\\requirements.txt") from exc
        item = self._find_interface()
        timeout_ms = max(100, int(self.config.get("timeout_ms", 1000)))
        unit_id = int(self.config.get("unit_id", 1))
        if not 0 <= unit_id <= 0xFF:
            raise BridgeError("adapter.unit_id must be 0..255")
        request_body = struct.pack(">BBHH", unit_id, 0x03, address, count)
        request = request_body + crc16_modbus(request_body).to_bytes(2, "little")
        # V2.33 interface 2 reports are 1025 bytes including report ID 0.
        # hidapi accepts that ID as the first byte passed to write().
        request_report = b"\0" + request + b"\0" * (1025 - 1 - len(request))
        dev = hid.device()
        try:
            dev.open_path(item["path"])
            written = dev.write(request_report)
            if written != len(request_report):
                raise BridgeError("H7-TOOL HID write did not accept the read request")
            deadline = time.monotonic() + timeout_ms / 1000
            while time.monotonic() < deadline:
                report = bytes(dev.read(1024, min(100, timeout_ms)))
                frame = self._extract_frame(report)
                if frame is None:
                    continue
                if frame[0] != unit_id:
                    continue
                if frame[1] == 0x83:
                    raise BridgeError(f"H7-TOOL rejected holding-register read; Modbus exception {frame[2]}")
                if frame[1] != 0x03 or frame[2] != count * 2:
                    continue
                data = frame[3:-2]
                if len(data) != count * 2:
                    continue
                return list(struct.unpack(">" + "H" * count, data))
        except BridgeError:
            raise
        except Exception as exc:  # hidapi has platform-specific exception types
            raise BridgeError(f"H7-TOOL HID read request failed: {exc}") from exc
        finally:
            try:
                dev.close()
            except Exception:
                pass
        raise BridgeError(
            "No matching H7-TOOL HID response. Verify the vendor PC application is closed and the tool is not in another active HID mode."
        )

    def _run_lua_script(self, script: bytes, script_label: str, begin_marker: bytes, end_marker: bytes) -> dict[str, Any]:
        try:
            import hid  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BridgeError("H7-TOOL USB HID support needs hidapi: & $py -m pip install -r .\\mcp\\requirements.txt") from exc
        if begin_marker not in script or end_marker not in script:
            raise BridgeError(f"Lua script {script_label} failed its safety marker check")
        item = self._find_interface()
        timeout_ms = max(1000, int(self.config.get("timeout_ms", 8000)))
        payload = script + (b"" if script.endswith(b"\0") else b"\0")
        request_body = struct.pack(">BBHIII", 1, 0x64, 0, len(payload), 0, len(payload)) + payload
        request = request_body + crc16_modbus(request_body).to_bytes(2, "little")
        output = bytearray()
        ack_seen = False
        reports = 0
        dev = hid.device()
        try:
            dev.open_path(item["path"])
            written = dev.write(self._report(request))
            if written != 1025:
                raise BridgeError("H7-TOOL HID write did not accept the Lua request")
            deadline = time.monotonic() + timeout_ms / 1000
            next_poll = 0.0
            channel = 0
            while time.monotonic() < deadline:
                now = time.monotonic()
                if now >= next_poll:
                    dev.write(self._report(self._lua_poll_frame(channel)))
                    channel = (channel + 1) % 5
                    next_poll = now + 0.02
                report = bytes(dev.read(1024, 50))
                if not report:
                    continue
                reports += 1
                if self._extract_lua_ack(report):
                    ack_seen = True
                    continue
                text = self._extract_lua_print(report)
                if text is not None:
                    text = text.rstrip(b"\xff")
                    if not text.strip(b"\0"):
                        continue
                    text = text.lstrip(b"\0")
                    output.extend(text)
                    decoded = output.decode("utf-8", errors="replace")
                    if end_marker.decode("ascii") in decoded:
                        break
        except BridgeError:
            raise
        except Exception as exc:  # hidapi has platform-specific exception types
            raise BridgeError(f"H7-TOOL HID Lua request failed: {exc}") from exc
        finally:
            try:
                dev.close()
            except Exception:
                pass
        decoded = output.decode("utf-8", errors="replace").strip()
        if not ack_seen:
            raise BridgeError("No H7-TOOL HID Lua acknowledgement; close the vendor PC application and retry")
        begin_text = begin_marker.decode("ascii")
        end_text = end_marker.decode("ascii")
        if begin_text not in decoded or end_text not in decoded:
            raise BridgeError(f"Lua was acknowledged but diagnostic output was incomplete: {decoded!r}")
        return {
            "transport": "h7tool_hid/function_64_lua + function_61_print_poll",
            "script": script_label,
            "reports": reports,
            "result": parse_response(output),
        }

    def _run_fixed_lua_script(self, script_name: str, begin_marker: bytes, end_marker: bytes) -> dict[str, Any]:
        script_path = Path(__file__).with_name("diagnostics") / script_name
        try:
            script = script_path.read_bytes()
        except OSError as exc:
            raise BridgeError(f"Cannot read bundled Lua script {script_name}: {exc}") from exc
        return self._run_lua_script(script, f"diagnostics/{script_name}", begin_marker, end_marker)

    def run_health_script(self) -> dict[str, Any]:
        return self._run_fixed_lua_script("tool_health.lua", b"H7TOOL_DIAG_BEGIN", b"H7TOOL_DIAG_END")

    def run_target_probe_script(self) -> dict[str, Any]:
        result = self._run_fixed_lua_script(
            "target_probe_stm32h7.lua",
            b"H7TOOL_TARGET_BEGIN",
            b"H7TOOL_TARGET_END",
        )
        result["result"] = parse_target_probe_output(result["result"]["raw"].encode("utf-8", errors="replace"))
        return result

    def run_read_memory_script(self, address: int, length: int) -> dict[str, Any]:
        script = f"""print("H7TOOL_MEM_BEGIN")
local A=0x{address:08X}
local L={length}
local function hx(b,s,n)
 local r=""
 for i=s,s+n-1 do r=r..string.format("%02X ",string.byte(b,i)) end
 return r
end
if pg_init then local r=pg_init() if r==nil then print("pg_init=nil") else print("pg_init="..r) end end
print(string.format("address=0x%08X",A))
print("length="..L)
if pg_read_mem then
 local ok,b=pg_read_mem(A,L)
 print("read="..ok)
 if ok==1 and b then
  local o=1
  while o<=#b do
   local n=16
   if o+n-1>#b then n=#b-o+1 end
   print(string.format("data[%d]=",o-1)..hx(b,o,n))
   o=o+n
  end
 end
else
 print("read=unavailable")
end
print("H7TOOL_MEM_END")
""".encode("ascii")
        result = self._run_lua_script(script, "generated/read_memory.lua", b"H7TOOL_MEM_BEGIN", b"H7TOOL_MEM_END")
        result["result"] = parse_read_memory_output(result["result"]["raw"].encode("utf-8", errors="replace"))
        return result

    def run_read_option_bytes_script(self, addresses: list[int]) -> dict[str, Any]:
        if not addresses:
            raise BridgeError("Selected device profile does not define option byte addresses")
        if len(addresses) > 256:
            raise BridgeError("Refusing to read more than 256 option byte addresses")
        lua_addresses = ",".join(f"0x{address:08X}" for address in addresses)
        script = f"""print("H7TOOL_OB_BEGIN")
local A={{{lua_addresses}}}
if pg_init then local r=pg_init() if r==nil then print("pg_init=nil") else print("pg_init="..r) end end
print("read_count="..#A)
for i=1,#A do
 local ok,b=pg_read_mem(A[i],1)
 local v="??"
 if ok==1 and b then v=string.format("%02X",string.byte(b,1)) end
 print(string.format("ob[%d]=0x%08X %s %s",i-1,A[i],ok,v))
end
print("H7TOOL_OB_END")
""".encode("ascii")
        result = self._run_lua_script(script, "generated/read_option_bytes.lua", b"H7TOOL_OB_BEGIN", b"H7TOOL_OB_END")
        result["result"] = parse_option_bytes_output(result["result"]["raw"].encode("utf-8", errors="replace"))
        return result


class H7ToolMcp:
    def __init__(self, config: dict[str, Any], config_path: Path) -> None:
        self.config = config
        self.config_path = config_path
        self.adapter = CommandAdapter(config["adapter"])
        self.modbus = ModbusTcpAdapter(config["adapter"])
        self.modbus_udp = ModbusUdpAdapter(config["adapter"])
        self.hid_modbus = H7ToolHidModbusAdapter(config["adapter"])

    def status(self) -> dict[str, Any]:
        return {
            "server": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "safety": "development-assistant mode; flash, erase, power, reset, and protection-changing actions are not exposed as MCP tools",
            "adapter": self.adapter.kind,
            "config_path": str(self.config_path),
            "configured_commands": sorted(self.config["commands"].keys()),
            "serial_ports": list_windows_serial_ports(),
            "h7tool_hid_devices": list_h7tool_hid_devices(),
        }

    def run_configured_command(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        template = self.config["commands"].get(name)
        if template is None:
            raise BridgeError(
                f"Command '{name}' is not configured. Copy config.example.json to config.json and "
                "add a command verified from vendor documentation or a manual test."
            )
        if not isinstance(template, str) or not template.strip():
            raise BridgeError(f"Command '{name}' must be a non-empty string template")
        try:
            payload = template.format(**arguments)
        except KeyError as exc:
            raise BridgeError(f"Command '{name}' requires missing argument: {exc.args[0]}") from exc
        result = self.adapter.execute(payload)
        return {"command": name, "result": result}

    def read_modbus_status(self) -> dict[str, Any]:
        # 0x0000..0x000B: UID, model/version, and GPIO status.
        # 0x000C..0x001F: ten IEEE-754 measurements (two registers each).
        if self.adapter.kind == "modbus_udp":
            reader = self.modbus_udp
        elif self.adapter.kind == "h7tool_hid":
            reader = self.hid_modbus
        else:
            reader = self.modbus
        identity = reader.read_holding_registers(0x0000, 12)
        analog = reader.read_holding_registers(0x000C, 20)
        return {
            "transport": f"{self.adapter.kind}/function_03/read_holding_registers",
            "data": decode_h7tool_status(identity, analog),
        }

    def read_modbus_registers(self, arguments: dict[str, Any]) -> dict[str, Any]:
        address_text = str(arguments.get("address", ""))
        count = int(arguments.get("count", 0))
        if not address_text.startswith("0x"):
            raise BridgeError("address must be hexadecimal, for example 0x0000")
        try:
            address = int(address_text, 16)
        except ValueError as exc:
            raise BridgeError("address must be hexadecimal, for example 0x0000") from exc
        if not 1 <= count <= 60:
            raise BridgeError("count must be between 1 and 60 registers")
        if self.adapter.kind == "modbus_udp":
            reader = self.modbus_udp
        elif self.adapter.kind == "h7tool_hid":
            reader = self.hid_modbus
        else:
            reader = self.modbus
        values = reader.read_holding_registers(address, count)
        return {
            "transport": f"{self.adapter.kind}/function_03/read_holding_registers",
            "address": f"0x{address:04X}",
            "count": count,
            "values_u16": values,
            "values_hex": [f"0x{value:04X}" for value in values],
        }

    def read_lua_health(self) -> dict[str, Any]:
        return LegacyH7ToolLuaSerialAdapter(self.config["adapter"]).run_health_script()

    def read_hid_lua_health(self) -> dict[str, Any]:
        return self.hid_modbus.run_health_script()

    def read_hid_target_probe(self) -> dict[str, Any]:
        return self.hid_modbus.run_target_probe_script()

    def read_hid_target_memory(self, address: int, length: int) -> dict[str, Any]:
        return self.hid_modbus.run_read_memory_script(address, length)

    def read_option_bytes(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.adapter.kind != "h7tool_hid":
            raise BridgeError("read_option_bytes currently requires adapter.type = h7tool_hid")
        profile = read_selected_target_profile(self.config, arguments)
        address_texts = profile.get("option_byte_addresses", [])
        if not isinstance(address_texts, list) or not address_texts:
            raise BridgeError("Selected device profile does not define option byte addresses")
        addresses: list[int] = []
        for item in address_texts:
            if not isinstance(item, str):
                continue
            addresses.append(int(item, 16))
        result = self.hid_modbus.run_read_option_bytes_script(addresses)
        result["profile"] = {
            "relative_path": profile.get("relative_path"),
            "vendor": profile.get("vendor"),
            "series": profile.get("series"),
            "device": profile.get("device"),
        }
        return result

    def protection_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.adapter.kind != "h7tool_hid":
            raise BridgeError("protection_status currently requires adapter.type = h7tool_hid")
        profile = read_selected_target_profile(self.config, arguments)
        checks = profile.get("protection_checks", [])
        if not isinstance(checks, list) or not checks:
            raise BridgeError("Selected device profile does not define protection status checks")
        addresses: list[int] = []
        for check in checks:
            if isinstance(check, dict) and isinstance(check.get("address"), str):
                addresses.append(int(check["address"], 16))
        read_result = self.hid_modbus.run_read_option_bytes_script(addresses)
        entries = read_result["result"]["data"].get("entries", [])
        values_by_address = {
            entry["address"].upper(): int(str(entry["value"]), 16)
            for entry in entries
            if isinstance(entry, dict) and entry.get("read") == 1 and isinstance(entry.get("value"), str)
        }
        decoded: list[dict[str, Any]] = []
        for check in checks:
            if not isinstance(check, dict):
                continue
            address = str(check.get("address", "")).upper()
            mask_text = check.get("mask")
            expected_text = check.get("unprotected_value")
            value = values_by_address.get(address)
            mask = int(mask_text, 16) if isinstance(mask_text, str) else None
            expected = int(expected_text, 16) if isinstance(expected_text, str) else None
            unprotected = None
            if value is not None and mask is not None and expected is not None:
                unprotected = (value & mask) == expected
            decoded.append(
                {
                    "address": check.get("address"),
                    "value": _format_hex(value, 2),
                    "mask": mask_text,
                    "unprotected_value": expected_text,
                    "unprotected": unprotected,
                }
            )
        protected_checks = [item for item in decoded if item.get("unprotected") is False]
        unknown_checks = [item for item in decoded if item.get("unprotected") is None]
        return {
            "profile": {
                "relative_path": profile.get("relative_path"),
                "vendor": profile.get("vendor"),
                "series": profile.get("series"),
                "device": profile.get("device"),
            },
            "status": {
                "overall": "unknown" if unknown_checks else ("protected" if protected_checks else "unprotected"),
                "protected_count": len(protected_checks),
                "unknown_count": len(unknown_checks),
                "check_count": len(decoded),
            },
            "checks": decoded,
            "raw_read": read_result["result"],
        }

    def target_identity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.adapter.kind != "h7tool_hid":
            raise BridgeError("target_identity currently requires adapter.type = h7tool_hid")
        profile = read_selected_target_profile(self.config, arguments)
        probe = self.read_hid_target_probe()
        probe_data = probe["result"]["data"]
        expected_idcode = profile.get("expected_idcode")
        actual_idcode = probe_data.get("idcode")
        return {
            "transport": probe["transport"],
            "script": probe["script"],
            "profile": profile,
            "probe": probe["result"],
            "identity": {
                "connected": bool(probe_data.get("connected")),
                "interface": profile.get("chip_type"),
                "vendor": profile.get("vendor"),
                "series": profile.get("series"),
                "device": profile.get("device"),
                "idcode": actual_idcode,
                "expected_idcode": expected_idcode,
                "idcode_match": bool(
                    isinstance(actual_idcode, str)
                    and isinstance(expected_idcode, str)
                    and actual_idcode.upper() == expected_idcode.upper()
                ),
                "uid_address": probe_data.get("uid_address") or profile.get("uid_address"),
                "uid_length": probe_data.get("uid_length") or profile.get("uid_length"),
                "uid_hex": probe_data.get("uid_hex"),
                "uid_bytes": probe_data.get("uid_bytes"),
                "flash_address": profile.get("flash_address"),
                "ram_address": profile.get("ram_address"),
            },
        }

    def target_summary(self, arguments: dict[str, Any]) -> dict[str, Any]:
        include_protection = bool(arguments.get("include_protection", False))
        include_flash_info = bool(arguments.get("include_flash_info", False))
        identity_args = {key: value for key, value in arguments.items() if key not in {"include_protection", "include_flash_info", "flash_size_address"}}
        identity_result = self.target_identity(identity_args)
        protection_result = None
        protection_error = None
        flash_info_result = None
        flash_info_error = None
        if include_protection:
            try:
                protection_result = self.protection_status(identity_args)
            except BridgeError as exc:
                protection_error = str(exc)
        if include_flash_info:
            try:
                flash_info_args = dict(identity_args)
                if "flash_size_address" in arguments:
                    flash_info_args["address"] = arguments["flash_size_address"]
                flash_info_result = self.target_flash_info(flash_info_args)
            except BridgeError as exc:
                flash_info_error = str(exc)
        summary = summarize_target_identity(identity_result, protection_result)
        if flash_info_result is not None:
            flash_warnings = flash_info_result.get("warnings", [])
            if isinstance(flash_warnings, list):
                summary.setdefault("warnings", []).extend(str(item) for item in flash_warnings)
            summary["flash_info"] = {
                "register": flash_info_result.get("register"),
                "profile_flash": flash_info_result.get("profile_flash"),
                "warnings": flash_warnings,
            }
        result: dict[str, Any] = {
            "summary": summary,
            "identity": identity_result,
        }
        if protection_result is not None:
            result["protection_status"] = protection_result
        if protection_error is not None:
            result["protection_error"] = protection_error
        if flash_info_result is not None:
            result["flash_info"] = flash_info_result
        if flash_info_error is not None:
            result["flash_info_error"] = flash_info_error
        return result

    def target_flash_info(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.adapter.kind != "h7tool_hid":
            raise BridgeError("target_flash_info currently requires adapter.type = h7tool_hid")
        profile = read_selected_target_profile(self.config, arguments)
        address_text = arguments.get("address")
        if isinstance(address_text, str) and address_text.strip():
            if not address_text.startswith("0x"):
                raise BridgeError("address must be hexadecimal, for example 0x1FF1E880")
            address = int(address_text, 16)
        else:
            address = default_flash_size_register(profile)
            if address is None:
                raise BridgeError("No default flash-size register is known for the selected profile; provide address")
        memory_result = self.read_hid_target_memory(address, 4)
        return summarize_flash_info(profile, memory_result, address)

    def health_summary(self) -> dict[str, Any]:
        if self.adapter.kind not in {"modbus_tcp", "modbus_udp", "h7tool_hid"}:
            raise BridgeError("health_summary requires adapter.type = modbus_tcp, modbus_udp, or h7tool_hid")
        status = self.read_modbus_status()
        return {"transport": status["transport"], "data": summarize_h7tool_health(status["data"])}

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "bridge_status":
            return self.status()
        if name == "device_vendors":
            return device_vendors()
        if name == "device_search":
            return search_device_library(
                str(arguments.get("query", "")),
                arguments.get("vendor") if isinstance(arguments.get("vendor"), str) else None,
                int(arguments.get("limit", 50)),
                bool(arguments.get("include_libraries", False)),
            )
        if name == "device_profile":
            return read_device_profile(arguments)
        if name == "device_capabilities":
            return device_capabilities(arguments)
        if name == "tool_status":
            if self.adapter.kind in {"modbus_tcp", "modbus_udp", "h7tool_hid"}:
                return self.read_modbus_status()
            if self.adapter.kind == "h7tool_lua_serial":
                return self.read_lua_health()
            return self.run_configured_command("status", arguments)
        if name == "health_summary":
            return self.health_summary()
        if name == "lua_health":
            if self.adapter.kind != "h7tool_hid":
                raise BridgeError("lua_health requires adapter.type = h7tool_hid")
            return self.read_hid_lua_health()
        if name == "tool_registers":
            if self.adapter.kind not in {"modbus_tcp", "modbus_udp", "h7tool_hid"}:
                raise BridgeError("tool_registers requires adapter.type = modbus_tcp, modbus_udp, or h7tool_hid")
            return self.read_modbus_registers(arguments)
        if name == "target_probe":
            if self.adapter.kind == "h7tool_hid":
                return self.read_hid_target_probe()
            return self.run_configured_command("target_probe", arguments)
        if name == "target_identity":
            return self.target_identity(arguments)
        if name == "target_summary":
            return self.target_summary(arguments)
        if name == "target_flash_info":
            return self.target_flash_info(arguments)
        if name == "read_option_bytes":
            return self.read_option_bytes(arguments)
        if name == "protection_status":
            return self.protection_status(arguments)
        if name == "log_tail":
            source = str(arguments.get("source", ""))
            if source not in {"uart", "rtt", "can"}:
                raise BridgeError("log_tail source must be uart, rtt, or can")
            lines = int(arguments.get("lines", 50))
            max_lines = int(self.config["limits"]["max_log_lines"])
            if not 1 <= lines <= max_lines:
                raise BridgeError(f"lines must be between 1 and {max_lines}")
            return self.run_configured_command(f"{source}_tail", {"lines": lines})
        if name == "read_memory":
            address = str(arguments.get("address", ""))
            length = int(arguments.get("length", 0))
            max_length = int(self.config["limits"]["max_read_memory_bytes"])
            if not address.startswith("0x"):
                raise BridgeError("address must be hexadecimal, for example 0x20000000")
            try:
                address_int = int(address, 16)
            except ValueError as exc:
                raise BridgeError("address must be hexadecimal, for example 0x20000000") from exc
            if not 0 <= address_int <= 0xFFFFFFFF:
                raise BridgeError("address must be a 32-bit target address")
            if not 1 <= length <= max_length:
                raise BridgeError(f"length must be between 1 and {max_length} bytes")
            if self.adapter.kind == "h7tool_hid":
                return self.read_hid_target_memory(address_int, length)
            return self.run_configured_command("read_memory", {"address": address, "length": length})
        raise BridgeError(f"Unknown tool: {name}")


TOOLS: list[dict[str, Any]] = [
    {
        "name": "bridge_status",
        "description": "Show bridge configuration and available serial ports/H7-TOOL HID interfaces. Does not contact H7-TOOL.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "device_vendors",
        "description": "List local H7-TOOL Programmer device-library vendors and Lua script counts. Pure filesystem indexing; no hardware access.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "device_search",
        "description": "Search local H7-TOOL Programmer device Lua scripts by keyword and optional vendor. Pure filesystem indexing; no hardware access.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": ""},
                "vendor": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                "include_libraries": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "device_profile",
        "description": "Parse one local H7-TOOL device Lua profile and return metadata such as interface, IDCODE, UID address, memory base addresses, includes, and FLM algorithms.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "vendor": {"type": "string"},
                "series": {"type": "string"},
                "device": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "device_capabilities",
        "description": "Inspect one local H7-TOOL device Lua profile plus included device libraries and summarize inferred capabilities. Pure filesystem analysis; no hardware access.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "vendor": {"type": "string"},
                "series": {"type": "string"},
                "device": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "tool_status",
        "description": "Read H7-TOOL status. With adapter.type=h7tool_lua_serial, runs the bundled health Lua script; other adapters require a configured verified command.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "health_summary",
        "description": "Produce an H7-TOOL health assessment: UID, versions, internal supply rails, NTC availability, target-facing observations, and warnings.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "lua_health",
        "description": "Run the bundled diagnostics/tool_health.lua over the configured H7-TOOL HID interface and return its print output.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "target_probe",
        "description": "Run a target probe. With adapter.type=h7tool_hid, executes the bundled STM32H7 UID probe script over HID.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "target_identity",
        "description": "Build a target identity profile by combining selected local H7-TOOL device Lua metadata with the live STM32H7 UID probe. Selection accepts relative_path or vendor/series/device; omitted uses config/default profile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "vendor": {"type": "string"},
                "series": {"type": "string"},
                "device": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "target_summary",
        "description": "Build a concise target summary for AI reporting and next-step planning. Optionally includes protection status when the selected profile supports it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "vendor": {"type": "string"},
                "series": {"type": "string"},
                "device": {"type": "string"},
                "include_protection": {"type": "boolean", "default": False},
                "include_flash_info": {"type": "boolean", "default": False},
                "flash_size_address": {"type": "string", "pattern": "^0x[0-9A-Fa-f]+$"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "target_flash_info",
        "description": "Read a target flash-size register for the selected profile and compare it with the profile primary flash algorithm size.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "vendor": {"type": "string"},
                "series": {"type": "string"},
                "device": {"type": "string"},
                "address": {"type": "string", "pattern": "^0x[0-9A-Fa-f]+$"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "tool_registers",
        "description": "Read H7-TOOL holding registers with Modbus function 0x03 over TCP, legacy UDP, or USB HID Communication. Never writes registers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "pattern": "^0x[0-9A-Fa-f]+$"},
                "count": {"type": "integer", "minimum": 1, "maximum": 60},
            },
            "required": ["address", "count"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_option_bytes",
        "description": "Read option-byte addresses from the selected local device profile over the configured HID Lua path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "vendor": {"type": "string"},
                "series": {"type": "string"},
                "device": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "protection_status",
        "description": "Read protection-related profile check addresses and summarize whether the selected target appears protected, unprotected, or unknown.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string"},
                "vendor": {"type": "string"},
                "series": {"type": "string"},
                "device": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "log_tail",
        "description": "Read a bounded UART, RTT, or CAN log window through a configured command.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "enum": ["uart", "rtt", "can"]},
                "lines": {"type": "integer", "minimum": 1, "default": 50},
            },
            "required": ["source"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_memory",
        "description": "Read a bounded target memory range. With adapter.type=h7tool_hid, uses a generated Lua memory-read template; other adapters require a configured command.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "pattern": "^0x[0-9A-Fa-f]+$"},
                "length": {"type": "integer", "minimum": 1, "maximum": 1024},
            },
            "required": ["address", "length"],
            "additionalProperties": False,
        },
    },
]


def result_message(value: Any, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}], "isError": is_error}


def jsonrpc_response(request_id: Any, result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result
    return message


def handle_request(server: H7ToolMcp, request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    if not isinstance(method, str):
        return jsonrpc_response(request_id, error={"code": -32600, "message": "Invalid JSON-RPC request"})
    if request_id is None:  # MCP notifications, including notifications/initialized
        return None
    try:
        if method == "initialize":
            client_version = request.get("params", {}).get("protocolVersion", "2024-11-05")
            protocol_version = client_version if client_version in SUPPORTED_PROTOCOL_VERSIONS else "2024-11-05"
            return jsonrpc_response(
                request_id,
                {
                    "protocolVersion": protocol_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": "H7-TOOL development-assistant bridge. Configure verified H7-TOOL access before requesting hardware data.",
                },
            )
        if method == "tools/list":
            return jsonrpc_response(request_id, {"tools": TOOLS})
        if method == "tools/call":
            params = request.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise BridgeError("tools/call requires string name and object arguments")
            return jsonrpc_response(request_id, result_message(server.call_tool(name, arguments)))
        return jsonrpc_response(request_id, error={"code": -32601, "message": f"Method not found: {method}"})
    except BridgeError as exc:
        return jsonrpc_response(request_id, result_message({"error": str(exc)}, is_error=True))
    except (TypeError, ValueError) as exc:
        return jsonrpc_response(request_id, result_message({"error": f"Invalid arguments: {exc}"}, is_error=True))
    except Exception as exc:  # Do not leak a traceback through the MCP channel.
        print(f"Unexpected bridge error: {exc}", file=sys.stderr, flush=True)
        return jsonrpc_response(request_id, result_message({"error": "Unexpected bridge error; see server stderr."}, is_error=True))


def write_mcp_response(response: dict[str, Any], framed: bool) -> None:
    payload = json.dumps(response, ensure_ascii=False).encode("utf-8")
    if framed and hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
        return
    print(payload.decode("utf-8"), flush=True)


def read_mcp_framed_body(stream: Any, first_header: bytes) -> str:
    headers = [first_header]
    while True:
        line = stream.readline()
        if line in {b"", b"\r\n", b"\n"}:
            break
        headers.append(line)
    content_length = None
    for header in headers:
        if header.lower().startswith(b"content-length:"):
            try:
                content_length = int(header.split(b":", 1)[1].strip())
            except ValueError as exc:
                raise ValueError("Invalid Content-Length header") from exc
            break
    if content_length is None:
        raise ValueError("Missing Content-Length header")
    body = stream.read(content_length)
    if len(body) != content_length:
        raise ValueError("Unexpected EOF while reading MCP message body")
    return body.decode("utf-8")


def serve_text_lines(server: H7ToolMcp) -> int:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("message must be an object")
            response = handle_request(server, request)
        except (json.JSONDecodeError, ValueError) as exc:
            response = jsonrpc_response(None, error={"code": -32700, "message": f"Parse error: {exc}"})
        if response is not None:
            write_mcp_response(response, framed=False)
    return 0


def serve(server: H7ToolMcp) -> int:
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return serve_text_lines(server)
    framed = False
    while True:
        line = stream.readline()
        if line == b"":
            break
        if line in {b"\r\n", b"\n"}:
            continue
        try:
            if line.lower().startswith(b"content-length:"):
                framed = True
                message = read_mcp_framed_body(stream, line)
            else:
                message = line.decode("utf-8")
            request = json.loads(message)
            if not isinstance(request, dict):
                raise ValueError("message must be an object")
            response = handle_request(server, request)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            response = jsonrpc_response(None, error={"code": -32700, "message": f"Parse error: {exc}"})
        if response is not None:
            write_mcp_response(response, framed=framed)
    return 0


def self_test(_server: H7ToolMcp) -> int:
    # Always isolate the self-test from the operator's hardware configuration.
    server = H7ToolMcp(load_config(Path("__nonexistent_mock_config__.json")), Path("__nonexistent_mock_config__.json"))
    assert server.status()["adapter"] == "mock"
    assert server.adapter.execute("target_probe")["data"]["debug_port"] == "SWD"
    sample = bytes.fromhex("01 64 00 00 00")
    assert LegacyH7ToolLuaSerialAdapter._frame_length(bytearray(sample)) == 5
    assert LegacyH7ToolLuaSerialAdapter._frame_length(bytearray(b"\x01\x61\x00\x00\x03abc")) == 10
    summary = summarize_h7tool_health(
        {
            "device_id_hex": "TEST",
            "hardware_model": 0x0752,
            "app_version": "2.33",
            "gpio_inputs_bits": "0x00000000",
            "gpio_outputs_bits": "0x00000000",
            "measurements": {
                "tvcc_v": 3.3,
                "usb_5v": 5.0,
                "ntc_c": -100.0,
                "ch1_v": 0.0,
                "ch2_v": 0.0,
                "high_side_v": 0.0,
                "high_side_a": 0.0,
                "external_power_v": 0.0,
            },
        }
    )
    assert summary["overall"] == "ok" and summary["unknown_count"] == 1
    lua_text = b"H7TOOL_DIAG_BEGIN\nuptime_ms=1\nH7TOOL_DIAG_END\n"
    lua_body = bytes([1, 0x61, 0, 0, 0, 0]) + len(lua_text).to_bytes(2, "big") + lua_text
    lua_report = lua_body + crc16_modbus(lua_body).to_bytes(2, "little")
    assert H7ToolHidModbusAdapter._extract_lua_print(lua_report + b"\xff" * 16) == lua_text
    ack_body = struct.pack(">BBBHIII", 1, 0x64, 0, 0, len(lua_text), 0, len(lua_text))
    ack_report = ack_body + crc16_modbus(ack_body).to_bytes(2, "little")
    assert H7ToolHidModbusAdapter._extract_lua_ack(ack_report + b"\xff" * 16)
    assert H7ToolHidModbusAdapter._lua_poll_frame(0).hex() == "016100000000100000000000000029ed"
    target = parse_target_probe_output(
        b"H7TOOL_TARGET_BEGIN\nidcode=0x6BA02477\nuid_read=1.0\nuid=3C 00 1E 00\nH7TOOL_TARGET_END\n"
    )
    assert target["data"]["connected"] is True
    assert target["data"]["uid_bytes"] == ["3C", "00", "1E", "00"]
    memory = parse_read_memory_output(
        b"H7TOOL_MEM_BEGIN\naddress=0x20000000\nlength=4\nread=1.0\ndata[0]=12 34 AB CD \nH7TOOL_MEM_END\n"
    )
    assert memory["data"]["ok"] is True
    assert memory["data"]["data_bytes"] == ["12", "34", "AB", "CD"]
    ob = parse_option_bytes_output(
        b"H7TOOL_OB_BEGIN\nread_count=2\nob[0]=0x52002020 1.0 F0\nob[1]=0x52002021 1.0 AA\nH7TOOL_OB_END\n"
    )
    assert ob["data"]["ok"] is True
    assert ob["data"]["data_hex"] == "F0 AA"
    profile = parse_lua_target_profile(
        Path("Device/ST/STM32H7xx/STM32H7x_2M.lua"),
        'CHIP_TYPE = "SWD"\nMCU_ID = 0x6BA02477\nUID_ADDR = 0x1FF1E800\nUID_BYTES = 12\n'
        'FLASH_ADDRESS = 0x08000000\nRAM_ADDRESS = 0x20000000\nAlgoRamSize = 128*1024\n'
        "OB_WRP_ADDRESS = {0x5200201D, 0x52002038}\nOB_WRP_MASK = {0xFF, 0xFF}\nOB_WRP_VALUE = {0xAA, 0xFF}\n",
    )
    assert profile["expected_idcode"] == "0x6BA02477"
    assert profile["uid_address"] == "0x1FF1E800"
    assert profile["algorithm_ram_size_bytes"] == 128 * 1024
    assert profile["protection_checks"][0] == {
        "address": "0x5200201D",
        "mask": "0xFF",
        "unprotected_value": "0xAA",
    }
    assert parse_ob_address_string("52002020 52002021") == ["0x52002020", "0x52002021"]
    vendors = device_vendors()
    assert vendors["total_lua"] > 1000
    assert any(item["vendor"] == "ST" for item in vendors["vendors"])
    search = search_device_library("STM32H7x_2M", vendor="ST", limit=20)
    assert any(item["relative_path"] == "ST/STM32H7xx/STM32H7x_2M.lua" for item in search["matches"])
    fuzzy_search = search_device_library("STM32H743", vendor="ST", limit=10)
    assert any(item["relative_path"] == "ST/STM32H7xx/STM32H7x_2M.lua" for item in fuzzy_search["matches"])
    device_profile = read_device_profile({"relative_path": "ST/STM32H7xx/STM32H7x_2M.lua"})
    assert device_profile["expected_idcode"] == "0x6BA02477"
    caps = device_capabilities({"relative_path": "ST/STM32H7xx/STM32H7x_2M.lua"})
    assert any(item["name"] == "uid" for item in caps["read_only_capabilities"])
    assert any(item["name"] == "option_bytes_read" for item in caps["read_only_capabilities"])
    assert any(item["name"] == "flash_or_ob_program" for item in caps["dangerous_capabilities"])
    selected_profile = read_selected_target_profile(
        {"adapter": {}},
        {"relative_path": "ST/STM32H7xx/STM32H7x_2M.lua"},
    )
    assert selected_profile["relative_path"] == "ST/STM32H7xx/STM32H7x_2M.lua"
    synthetic_summary = summarize_target_identity(
        {
            "profile": {
                "relative_path": "ST/STM32H7xx/STM32H7x_2M.lua",
                "vendor": "ST",
                "series": "STM32H7xx",
                "device": "STM32H7x_2M",
                "algorithm_files": [{"file": "STM32H7x_2M.FLM", "address": "0x08000000", "size_bytes": 2097152}],
                "option_byte_addresses": ["0x52002020"],
                "protection_checks": [{"address": "0x5200201D"}],
                "include_list": ["0:/H7-TOOL/Programmer/Device/ST/STM32H7xx/Lib/STM32H7xx.lua"],
            },
            "identity": {
                "connected": True,
                "interface": "SWD",
                "idcode": "0x6BA02477",
                "expected_idcode": "0x6BA02477",
                "idcode_match": True,
                "uid_hex": "3C 00 1E 00",
                "flash_address": "0x08000000",
                "ram_address": "0x20000000",
            },
        }
    )
    assert synthetic_summary["target"]["idcode_match"] is True
    assert synthetic_summary["profile_support"]["option_byte_address_count"] == 1
    assert "protection_status" in synthetic_summary["next_tools"]
    flash_info = summarize_flash_info(
        {
            "relative_path": "ST/STM32H7xx/STM32H7x_2M.lua",
            "vendor": "ST",
            "series": "STM32H7xx",
            "device": "STM32H7x_2M",
            "flash_address": "0x08000000",
            "algorithm_files": [{"address": "0x08000000", "size_bytes": 2 * 1024 * 1024}],
        },
        {
            "result": {
                "data": {
                    "data_hex": "80 00 00 00",
                    "data_bytes": ["80", "00", "00", "00"],
                }
            }
        },
        0x1FF1E880,
    )
    assert flash_info["register"]["size_kb"] == 128
    assert flash_info["register"]["size_bytes"] == 128 * 1024
    assert flash_info["profile_flash"]["size_match"] is False
    assert default_flash_size_register({"vendor": "ST", "series": "STM32H7xx"}) == 0x1FF1E880
    try:
        server.call_tool("read_memory", {"address": "0x20000000", "length": 4096})
    except BridgeError:
        pass
    else:
        raise AssertionError("memory read limit was not enforced")
    print("Self-test passed: MCP bridge is running in safe mock mode.")
    return 0


def main() -> int:
    # MCP stdio is UTF-8 JSON regardless of the active Windows console codepage.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("H7TOOL_MCP_CONFIG", DEFAULT_CONFIG_PATH)))
    parser.add_argument("--list-serial-ports", action="store_true", help="List Windows serial devices and exit")
    parser.add_argument("--list-hid-devices", action="store_true", help="List matching H7-TOOL USB HID interfaces and exit")
    parser.add_argument("--device-vendors", action="store_true", help="List local H7-TOOL device-library vendors and Lua counts")
    parser.add_argument("--device-search", metavar="QUERY", help="Search local H7-TOOL device Lua scripts")
    parser.add_argument("--device-vendor", metavar="VENDOR", help="Restrict --device-search to one vendor")
    parser.add_argument("--include-libraries", action="store_true", help="Include shared Lib scripts in --device-search results")
    parser.add_argument("--device-profile", metavar="RELATIVE_PATH", help="Parse one local H7-TOOL device Lua profile")
    parser.add_argument("--device-capabilities", metavar="RELATIVE_PATH", help="Inspect one local H7-TOOL device Lua profile and summarize inferred capabilities")
    parser.add_argument("--self-test", action="store_true", help="Test MCP logic using only the built-in mock adapter")
    parser.add_argument("--probe-h7tool", action="store_true", help="Run the configured tool_status probe and print JSON")
    parser.add_argument("--health-summary", action="store_true", help="Run the configured H7-TOOL health assessment and print JSON")
    parser.add_argument("--lua-health", action="store_true", help="Run the bundled Lua health check through the configured HID adapter")
    parser.add_argument("--target-probe", action="store_true", help="Run the configured target probe and print JSON")
    parser.add_argument("--target-identity", nargs="?", const="", metavar="RELATIVE_PATH", help="Build the target identity profile; optionally select a local device Lua relative path")
    parser.add_argument("--target-summary", nargs="?", const="", metavar="RELATIVE_PATH", help="Build a concise target summary; optionally select a local device Lua relative path")
    parser.add_argument("--include-protection-status", action="store_true", help="With --target-summary, also include protection status when available")
    parser.add_argument("--include-flash-info", action="store_true", help="With --target-summary, also include target flash-size register information when available")
    parser.add_argument("--target-flash-info", nargs="?", const="", metavar="RELATIVE_PATH", help="Read target flash-size information; optionally select a local device Lua relative path")
    parser.add_argument("--flash-size-address", metavar="ADDRESS", help="Override the target flash-size register address for --target-flash-info or --target-summary")
    parser.add_argument("--read-option-bytes", nargs="?", const="", metavar="RELATIVE_PATH", help="Read option bytes using a selected local device Lua profile")
    parser.add_argument("--protection-status", nargs="?", const="", metavar="RELATIVE_PATH", help="Read and summarize protection status using a selected local device Lua profile")
    parser.add_argument("--read-memory", nargs=2, metavar=("ADDRESS", "LENGTH"), help="Read a bounded target memory range through the configured adapter")
    parser.add_argument("--tool-registers", nargs=2, metavar=("ADDRESS", "COUNT"), help="Read bounded H7-TOOL holding registers through the configured Modbus adapter")
    args = parser.parse_args()
    if args.list_serial_ports:
        print(json.dumps(list_windows_serial_ports(), ensure_ascii=False, indent=2))
        return 0
    if args.list_hid_devices:
        print(json.dumps(list_h7tool_hid_devices(), ensure_ascii=False, indent=2))
        return 0
    if args.device_vendors:
        print(json.dumps(device_vendors(), ensure_ascii=False, indent=2))
        return 0
    if args.device_search is not None:
        print(
            json.dumps(
                search_device_library(args.device_search, args.device_vendor, include_libraries=args.include_libraries),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.device_profile is not None:
        print(json.dumps(read_device_profile({"relative_path": args.device_profile}), ensure_ascii=False, indent=2))
        return 0
    if args.device_capabilities is not None:
        print(json.dumps(device_capabilities({"relative_path": args.device_capabilities}), ensure_ascii=False, indent=2))
        return 0
    config = load_config(args.config)
    server = H7ToolMcp(config, args.config)
    if args.self_test:
        return self_test(server)
    if args.probe_h7tool:
        try:
            print(json.dumps(server.call_tool("tool_status", {}), ensure_ascii=False, indent=2))
            return 0
        except BridgeError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    if args.health_summary:
        try:
            print(json.dumps(server.call_tool("health_summary", {}), ensure_ascii=False, indent=2))
            return 0
        except BridgeError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    if args.lua_health:
        try:
            print(json.dumps(server.call_tool("lua_health", {}), ensure_ascii=False, indent=2))
            return 0
        except BridgeError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    if args.target_probe:
        try:
            print(json.dumps(server.call_tool("target_probe", {}), ensure_ascii=False, indent=2))
            return 0
        except BridgeError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    if args.target_identity is not None:
        try:
            identity_args = {"relative_path": args.target_identity} if args.target_identity else {}
            print(json.dumps(server.call_tool("target_identity", identity_args), ensure_ascii=False, indent=2))
            return 0
        except BridgeError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    if args.target_summary is not None:
        try:
            summary_args = {"relative_path": args.target_summary} if args.target_summary else {}
            if args.include_protection_status:
                summary_args["include_protection"] = True
            if args.include_flash_info:
                summary_args["include_flash_info"] = True
            if args.flash_size_address:
                summary_args["flash_size_address"] = args.flash_size_address
            print(json.dumps(server.call_tool("target_summary", summary_args), ensure_ascii=False, indent=2))
            return 0
        except BridgeError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    if args.target_flash_info is not None:
        try:
            flash_args = {"relative_path": args.target_flash_info} if args.target_flash_info else {}
            if args.flash_size_address:
                flash_args["address"] = args.flash_size_address
            print(json.dumps(server.call_tool("target_flash_info", flash_args), ensure_ascii=False, indent=2))
            return 0
        except BridgeError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    if args.read_option_bytes is not None:
        try:
            ob_args = {"relative_path": args.read_option_bytes} if args.read_option_bytes else {}
            print(json.dumps(server.call_tool("read_option_bytes", ob_args), ensure_ascii=False, indent=2))
            return 0
        except BridgeError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    if args.protection_status is not None:
        try:
            protection_args = {"relative_path": args.protection_status} if args.protection_status else {}
            print(json.dumps(server.call_tool("protection_status", protection_args), ensure_ascii=False, indent=2))
            return 0
        except BridgeError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    if args.read_memory:
        try:
            address, length = args.read_memory
            print(json.dumps(server.call_tool("read_memory", {"address": address, "length": int(length)}), ensure_ascii=False, indent=2))
            return 0
        except (BridgeError, ValueError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    if args.tool_registers:
        try:
            address, count = args.tool_registers
            print(json.dumps(server.call_tool("tool_registers", {"address": address, "count": int(count)}), ensure_ascii=False, indent=2))
            return 0
        except (BridgeError, ValueError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
    return serve(server)


if __name__ == "__main__":
    raise SystemExit(main())
