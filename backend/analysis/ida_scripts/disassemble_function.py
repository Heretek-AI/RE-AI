#!/usr/bin/env python3
"""IDAPython script — disassemble a code region.

Reads environment variables from the parent process:
  IDA_ANALYSIS_BIN_PATH  — binary to analyse
  IDA_OUTPUT_PATH        — path for JSON output
  IDA_SECTION_NAME       — section containing the code (e.g. ``.text``)
  IDA_OFFSET             — byte offset *within the section* to start
  IDA_SIZE               — number of instructions to disassemble (default 256)

Result keys match ``DisassemblyResult`` in ``base.py``.
"""

from __future__ import annotations

import json
import os
import sys

try:
    import ida_auto
    import ida_bytes
    import ida_idaapi
    import ida_segment
    import ida_ua
except ImportError:
    sys.exit("This script must be run inside IDA Pro (idat64 / idal64).")


def _arch_str() -> str:
    """Return a short architecture string."""
    info = ida_idaapi.get_inf_structure()
    if info is None:
        return "unknown"
    proc = info.procname.lower() if info.procname else ""
    if "arm" in proc:
        return "ARM" if "64" not in proc else "AARCH64"
    if "mips" in proc:
        return "MIPS"
    if "8051" in proc:
        return "8051"
    # x86/x64
    if "metapc" in proc or "x86" in proc or "80386" in proc:
        if info.is_64bit():
            return "x86-64"
        return "x86"
    return proc.upper() if proc else "unknown"


def _mode_str() -> str:
    info = ida_idaapi.get_inf_structure()
    if info is None:
        return "unknown"
    if info.is_64bit():
        return "64-bit"
    if info.is_32bit():
        return "32-bit"
    return "16-bit"


def _get_instruction_name(ea: int) -> str:
    """Get canonical instruction mnemonics."""
    try:
        from ida_ua import print_insn_mnem
        return print_insn_mnem(ea)
    except Exception:
        return ""


def _get_operand_str(ea: int, n: int) -> str:
    """Get operand text."""
    try:
        from ida_ua import print_operand
        return print_operand(ea, n)
    except Exception:
        return ""


def main() -> None:
    bin_path = os.environ.get("IDA_ANALYSIS_BIN_PATH")
    output_path = os.environ.get("IDA_OUTPUT_PATH")
    section_name = os.environ.get("IDA_SECTION_NAME", ".text")
    offset_str = os.environ.get("IDA_OFFSET", "0")
    size_str = os.environ.get("IDA_SIZE", "256")

    if not bin_path or not output_path:
        sys.exit("ERROR: IDA_ANALYSIS_BIN_PATH and IDA_OUTPUT_PATH must be set.")

    try:
        offset = int(offset_str)
    except ValueError:
        offset = 0

    try:
        max_instructions = int(size_str)
    except ValueError:
        max_instructions = 256

    ida_idaapi.open_database(bin_path, True)
    ida_auto.auto_wait()

    # Locate the target section
    seg = ida_segment.get_segm_by_name(section_name)
    if seg is None:
        result: dict = {
            "architecture": _arch_str(),
            "mode": _mode_str(),
            "section_name": section_name,
            "offset": offset,
            "bytes_count": 0,
            "instructions": [],
            "truncated": False,
            "_error": f"Section '{section_name}' not found",
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        ida_idaapi.close_database(True)
        return

    start_ea = seg.start_ea + offset
    end_ea = min(start_ea + (max_instructions * 16), seg.end_ea)

    instructions: list[dict] = []
    ea = start_ea
    insn = ida_ua.insn_t()
    count = 0
    truncated = False

    while ea < end_ea and count < max_instructions:
        insn_len = ida_ua.create_insn(ea, insn)
        if insn_len == 0:
            # Could not decode — skip a byte
            ea += 1
            continue

        # Read raw bytes
        raw = ida_bytes.get_bytes(ea, insn.size) or b""

        operands: list[str] = []
        for n in range(6):  # max 6 operands on x86
            op_str = _get_operand_str(ea, n)
            if op_str:
                operands.append(op_str)
            else:
                break

        instructions.append({
            "address": ea,
            "mnemonic": insn.get_canon_mnem(),
            "size": insn.size,
            "bytes": raw.hex(),
            "operands": operands,
        })

        count += 1
        ea += insn.size

    if ea >= seg.end_ea or count >= max_instructions:
        truncated = True

    result = {
        "architecture": _arch_str(),
        "mode": _mode_str(),
        "section_name": section_name,
        "offset": offset,
        "bytes_count": sum(insn["size"] for insn in instructions),
        "instructions": instructions,
        "truncated": truncated,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    ida_idaapi.close_database(True)


if __name__ == "__main__":
    main()
