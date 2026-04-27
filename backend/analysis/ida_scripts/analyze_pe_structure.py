#!/usr/bin/env python3
"""IDAPython script — PE header structure analysis.

Reads ``IDA_ANALYSIS_BIN_PATH`` and ``IDA_OUTPUT_PATH`` from the
environment, opens the database, extracts PE header information,
and writes a JSON result.

Result keys match ``PeStructureResult`` in ``base.py``.
"""

from __future__ import annotations

import json
import os
import sys

# ---- IDA SDK imports (available only inside IDA) ---------------------------
try:
    import ida_auto
    import ida_ida
    import ida_idaapi
    import ida_nalt
    import ida_pe
    import ida_segment
    import ida_type
except ImportError:
    sys.exit("This script must be run inside IDA Pro (idat64 / idal64).")


def _section_characteristics_str(chars: int) -> str:
    """Return a human-readable summary of section characteristics."""
    flags: list[str] = []
    mapping = {
        0x00000020: "CODE",
        0x00000040: "INITIALIZED_DATA",
        0x00000080: "UNINITIALIZED_DATA",
        0x02000000: "DISCARDABLE",
        0x10000000: "SHARED",
        0x20000000: "EXECUTE",
        0x40000000: "READ",
        0x80000000: "WRITE",
    }
    for mask, label in mapping.items():
        if chars & mask:
            flags.append(label)
    return " | ".join(flags) if flags else "unknown"


def _machine_type_str(machine: int) -> str:
    mapping = {
        0x014c: "I386",
        0x0164: "IA64",
        0x01c0: "ARM",
        0x01c2: "ARM64",
        0x01c4: "THUMB",
        0x0200: "AMD64",
        0x8664: "AMD64",
        0x5032: "RISCV32",
        0x5064: "RISCV64",
        0x00e0: "MIPS",
    }
    return mapping.get(machine, f"0x{machine:04x}")


def _subsystem_str(sub: int) -> str:
    mapping = {
        0:  "UNKNOWN",
        1:  "NATIVE",
        2:  "WINDOWS_GUI",
        3:  "WINDOWS_CUI",
        5:  "WINDOWS_CE_GUI",
        7:  "WINDOWS_CE_GUI",
        10: "EFI_APPLICATION",
        11: "EFI_BOOT_SERVICE_DRIVER",
        12: "EFI_RUNTIME_DRIVER",
        13: "EFI_ROM",
        14: "XBOX",
        16: "WINDOWS_BOOT_APPLICATION",
    }
    return mapping.get(sub, f"0x{sub:04x}")


def main() -> None:
    bin_path = os.environ.get("IDA_ANALYSIS_BIN_PATH")
    output_path = os.environ.get("IDA_OUTPUT_PATH")

    if not bin_path or not output_path:
        sys.exit("ERROR: IDA_ANALYSIS_BIN_PATH and IDA_OUTPUT_PATH must be set.")

    ida_idaapi.open_database(bin_path, True)
    ida_auto.auto_wait()

    result: dict = {}

    # Image base
    image_base = ida_idaapi.get_imagebase()
    result["image_base"] = image_base

    # PE header
    pe_hdr = ida_pe.peheader_t()
    if pe_hdr:
        try:
            result["machine_type"] = _machine_type_str(pe_hdr.machine)
            result["characteristics"] = _section_characteristics_str(
                pe_hdr.characteristics
            )
            is_dll = bool(pe_hdr.characteristics & 0x2000)
            is_exe = bool(pe_hdr.characteristics & 0x0002)
            result["is_dll"] = is_dll
            result["is_exe"] = is_exe
            result["subsystems"] = [
                _subsystem_str(pe_hdr.subsystem)
            ]
            result["entry_point"] = pe_hdr.AddressOfEntryPoint + image_base
            result["size_of_image"] = pe_hdr.SizeOfImage
        except Exception as exc:
            result["_pe_header_error"] = str(exc)
    else:
        result["_pe_header_error"] = "Could not read PE header"

    # Sections
    sections: list[dict] = []
    seg_qty = ida_segment.get_segm_qty()
    for idx in range(seg_qty):
        seg = ida_segment.getnseg(idx)
        if seg is None:
            continue
        sections.append({
            "name": seg.name or "",
            "start_ea": seg.start_ea,
            "end_ea": seg.end_ea,
            "size": seg.end_ea - seg.start_ea,
            "characteristics": _section_characteristics_str(seg.perm),
        })
    result["sections"] = sections

    # Imphash (MD5 of imports)
    try:
        result["imphash"] = ida_nalt.get_input_file_md5()
    except Exception:
        result["imphash"] = None

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    ida_idaapi.close_database(True)


if __name__ == "__main__":
    main()
