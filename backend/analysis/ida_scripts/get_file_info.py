#!/usr/bin/env python3
"""IDAPython script — file-level metadata extraction.

Reads ``IDA_ANALYSIS_BIN_PATH`` and ``IDA_OUTPUT_PATH`` from the
environment, opens the database, extracts file metadata (name,
hashes, PE flags, architecture, timestamps) and writes a JSON
result.

Result keys match ``FileInfoResult`` in ``base.py``.
"""

from __future__ import annotations

import json
import os
import sys
import time

try:
    import ida_auto
    import ida_idaapi
    import ida_nalt
    import ida_pe
except ImportError:
    sys.exit("This script must be run inside IDA Pro (idat64 / idal64).")


def _arch_str() -> str | None:
    """Return short architecture string from PE header or procname."""
    pe_hdr = ida_pe.peheader_t()
    if pe_hdr:
        machine = pe_hdr.machine
        mapping = {
            0x014c: "I386",
            0x0164: "IA64",
            0x01c0: "ARM",
            0x01c2: "ARM64",
            0x0200: "AMD64",
            0x8664: "AMD64",
            0x5032: "RISCV32",
            0x5064: "RISCV64",
        }
        arch = mapping.get(machine)
        if arch:
            return arch

    # Fallback: procname
    info = ida_idaapi.get_inf_structure()
    if info and info.procname:
        return info.procname.upper()
    return None


def _subsystem_str() -> str | None:
    pe_hdr = ida_pe.peheader_t()
    if not pe_hdr:
        return None
    mapping = {
        0:  "UNKNOWN",
        1:  "NATIVE",
        2:  "WINDOWS_GUI",
        3:  "WINDOWS_CUI",
        5:  "WINDOWS_CE_GUI",
        10: "EFI_APPLICATION",
        11: "EFI_BOOT_SERVICE_DRIVER",
        12: "EFI_RUNTIME_DRIVER",
        13: "EFI_ROM",
        14: "XBOX",
        16: "WINDOWS_BOOT_APPLICATION",
    }
    return mapping.get(pe_hdr.subsystem, f"0x{pe_hdr.subsystem:04x}")


def _timestamp_str() -> str | None:
    """Convert PE header timestamp to ISO string."""
    pe_hdr = ida_pe.peheader_t()
    if not pe_hdr:
        return None
    ts = pe_hdr.TimeDateStamp
    if ts == 0:
        return None
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
    except (OSError, ValueError):
        return str(ts)


def main() -> None:
    bin_path = os.environ.get("IDA_ANALYSIS_BIN_PATH")
    output_path = os.environ.get("IDA_OUTPUT_PATH")

    if not bin_path or not output_path:
        sys.exit("ERROR: IDA_ANALYSIS_BIN_PATH and IDA_OUTPUT_PATH must be set.")

    ida_idaapi.open_database(bin_path, True)
    ida_auto.auto_wait()

    # File path (canonicalized)
    try:
        import ida_diskio
        base_path = ida_diskio.get_input_file_path()
    except Exception:
        base_path = bin_path

    # File size
    size_bytes = 0
    try:
        size_bytes = os.path.getsize(bin_path)
    except OSError:
        pass

    # Hashes
    md5 = ida_nalt.get_input_file_md5() or ""
    sha256 = ida_nalt.get_input_file_sha256() or ""

    # PE detection + entry point
    is_pe = bool(ida_pe.peheader_t())
    ep: int | None = None
    is_dll: bool | None = None
    is_exe: bool | None = None
    if is_pe:
        pe_hdr = ida_pe.peheader_t()
        image_base = ida_idaapi.get_imagebase()
        ep = pe_hdr.AddressOfEntryPoint + image_base
        is_dll = bool(pe_hdr.characteristics & 0x2000)
        is_exe = bool(pe_hdr.characteristics & 0x0002)
    else:
        ep = None
        is_dll = None
        is_exe = None

    result: dict = {
        "path": base_path,
        "size_bytes": size_bytes,
        "md5": md5,
        "sha256": sha256,
        "is_pe": is_pe,
        "subsystem": _subsystem_str(),
        "architecture": _arch_str(),
        "is_dll": is_dll,
        "is_exe": is_exe,
        "entry_point": ep,
        "timestamp": _timestamp_str(),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    ida_idaapi.close_database(True)


if __name__ == "__main__":
    main()
