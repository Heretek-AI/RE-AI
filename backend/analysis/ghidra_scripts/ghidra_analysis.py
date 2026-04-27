#!/usr/bin/env python
"""Ghidra analysis script with mode dispatch.

Runs inside Ghidra's Jython 2.7 interpreter, invoked by
``analyzeHeadless`` with ``-postScript``.  Reads the analysis
mode from the ``GHIDRA_MODE`` environment variable and writes
a JSON result to ``GHIDRA_OUTPUT``.

Modes
-----
structure         PE header structure matching PeStructureResult
imports-exports   Import / export tables matching ImportsExportsResult
strings           ASCII + UTF-16LE string extraction (by brute force)
disassembly       Code disassembly by section name
file-info         File-level metadata matching FileInfoResult
"""

import json
import os
import sys

# ---------------------------------------------------------------------------
# Ghidra / Java imports -- guarded so script passes py_compile outside Ghidra
# ---------------------------------------------------------------------------
_ghidra_imports_ok = False
try:
    from ghidra.program.model.listing import Program, Function, CodeUnit
    from ghidra.program.model.symbol import SymbolType, Symbol  # @UnusedImport
    from ghidra.program.model.mem import MemoryBlock  # @UnusedImport
    from ghidra.program.model.address import Address  # @UnusedImport
    from ghidra.program.model.lang import Processor  # @UnusedImport
    from ghidra.util.task import ConsoleTaskMonitor  # @UnusedImport
    from ghidra.util.task import TaskMonitor
    from java.io import File
    from java.lang import Long, Integer
    _ghidra_imports_ok = True
except ImportError:
    pass

if not _ghidra_imports_ok:
    sys.exit("This script must be run inside Ghidra's analyzeHeadless.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mem_permissions_str(block):
    """Return rwx-style permission string for a MemoryBlock."""
    parts = []
    if block.isExecute():
        parts.append("x")
    else:
        parts.append("-")
    if block.isWrite():
        parts.append("w")
    else:
        parts.append("-")
    if block.isRead():
        parts.append("r")
    else:
        parts.append("-")
    return "".join(reversed(parts))


def _is_printable(data):
    """Return True if all bytes in *data* are printable ASCII."""
    for b in data:
        if b < 0x20 or b > 0x7E:
            return False
    return True


def _get_monitor():
    """Return a TaskMonitor instance."""
    try:
        return ConsoleTaskMonitor()
    except Exception:
        return TaskMonitor.DUMMY


# ---------------------------------------------------------------------------
# Mode: structure  (PE header structure)
# ---------------------------------------------------------------------------

def _mode_structure(program):
    """Analyse PE header structure."""
    result = {}

    # Processor / language
    lang = program.getLanguage()
    proc = lang.getProcessor()
    result["machine_type"] = str(proc)

    # Image base
    image_base = program.getImageBase()
    result["image_base"] = image_base.getOffset() if image_base else 0

    # Entry point
    entry_point = None
    min_addr = program.getMinAddress()
    if min_addr is not None:
        # Try function at min address first
        fm = program.getFunctionManager()
        ep_func = fm.getFunctionAt(min_addr)
        if ep_func is not None:
            entry_point = ep_func.getEntryPoint().getOffset()
        else:
            # Try symbol table for "entry" symbol
            st = program.getSymbolTable()
            for sym in st.getAllSymbols(True):
                sym_name = sym.getName().lower()
                if sym_name == "entry" or sym_name == "_start":
                    entry_point = sym.getAddress().getOffset()
                    break
            if entry_point is None:
                # Fallback: first instruction address
                listing = program.getListing()
                inst = listing.getInstructionAt(min_addr)
                if inst is not None:
                    entry_point = inst.getAddress().getOffset()
                else:
                    entry_point = min_addr.getOffset()
    result["entry_point"] = entry_point

    # Try PE header info (available if Ghidra's PE parser ran)
    characteristics = None
    is_dll = False
    is_exe = False
    subsystems = []
    size_of_image = None
    pe_parse_error = None

    try:
        from ghidra.app.util.bin.format.pe import NTHeader
        from ghidra.app.util.bin.format.pe import ImageDosHeader

        dos = ImageDosHeader(program.getMemory())
        nt = NTHeader(dos)

        pe_hdr = nt.getPEHeader()
        if pe_hdr is not None:
            # Characteristics
            chars_val = pe_hdr.getCharacteristics()
            characteristics = "0x%08x" % chars_val
            is_dll = bool(chars_val & 0x2000)
            is_exe = bool(chars_val & 0x0002)
            subsys = pe_hdr.getSubsystem()
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
            subsystems.append(mapping.get(subsys, "0x%04x" % subsys))
            size_of_image = pe_hdr.getSizeOfImage()
    except Exception as exc:
        pe_parse_error = str(exc)

    result["characteristics"] = characteristics
    result["is_dll"] = is_dll
    result["is_exe"] = is_exe
    result["subsystems"] = subsystems
    result["size_of_image"] = size_of_image
    if pe_parse_error:
        result["_pe_parse_error"] = pe_parse_error

    # Sections
    sections = []
    blocks = program.getMemory().getBlocks()
    if blocks is not None:
        for block in blocks:
            try:
                start = block.getStart()
                end = block.getEnd()
                sections.append({
                    "name": str(block.getName()),
                    "start_ea": start.getOffset() if start else 0,
                    "end_ea": end.getOffset() if end else 0,
                    "size": block.getSize(),
                    "permissions": _mem_permissions_str(block),
                })
            except Exception:
                pass
    result["sections"] = sections

    # Imphash (program MD5 as proxy -- Ghidra doesn't compute imphash natively)
    md5_hash = None
    try:
        md5_hash = str(program.getExecutableMD5())
    except Exception:
        pass
    result["imphash"] = md5_hash

    return result


# ---------------------------------------------------------------------------
# Mode: imports-exports
# ---------------------------------------------------------------------------

def _mode_imports_exports(program):
    """Extract import and export tables."""
    imports = []
    exports = []

    # --- Imports via ExternalManager ---
    try:
        ext_mgr = program.getExternalManager()
        lib_names = ext_mgr.getExternalLibraries()
        if lib_names is not None:
            for lib_idx in range(len(lib_names)):
                lib_name = str(lib_names[lib_idx])
                symbols = []
                ext_fns = ext_mgr.getExternalFunctions(lib_name)
                if ext_fns is not None:
                    # ext_fns is an iterator of ExternalLocation
                    ext_iter = ext_fns.iterator()
                    while ext_iter.hasNext():
                        eloc = ext_iter.next()
                        sym_addr = eloc.getAddress()
                        addr_val = sym_addr.getOffset() if sym_addr else 0
                        sym_name = str(eloc.getLabel())
                        ordinal = eloc.getOrdinal()
                        symbols.append({
                            "address": addr_val,
                            "name": sym_name if sym_name else "ord_%d" % ordinal,
                            "ordinal": ordinal,
                        })
                imports.append({
                    "module": lib_name,
                    "symbols": symbols,
                })
    except Exception:
        pass

    # --- Exports via symbol table ---
    try:
        st = program.getSymbolTable()
        sym_iter = st.getSymbolIterator()
        from ghidra.program.model.symbol import SymbolType as SymType  # @UnusedImport
        # Symbol types: FUNCTION, LABEL, etc.
        # We look for symbols at global scope that are not external
        ext_mgr = program.getExternalManager()
        while sym_iter.hasNext():
            sym = sym_iter.next()
            sym_type = sym.getSymbolType()
            sym_name = str(sym.getName())
            sym_addr = sym.getAddress()
            if sym_addr is None:
                continue

            # Filter: only global symbols that are functions or labels
            stype_name = str(sym_type)
            if stype_name not in ("Function", "Label", "Class"):
                continue

            # Filter out external symbols
            addr_offset = sym_addr.getOffset()
            is_external = False
            try:
                eloc = ext_mgr.getExternalLocation(sym)
                is_external = eloc is not None
            except Exception:
                pass
            if is_external:
                continue

            # Also filter out section symbols
            if sym_name.startswith("."):
                continue

            exports.append({
                "ordinal": sym.getID(),
                "name": sym_name,
                "target_ea": addr_offset,
            })
    except Exception:
        pass

    # Check for exception handling
    has_exceptions = False
    try:
        from ghidra.app.util.bin.format.pe import NTHeader
        from ghidra.app.util.bin.format.pe import ImageDosHeader
        dos = ImageDosHeader(program.getMemory())
        nt = NTHeader(dos)
        optional_hdr = nt.getOptionalHeader()
        if optional_hdr is not None:
            dll_flags = optional_hdr.getDllFlags()
            if dll_flags is not None:
                # IMAGE_DLLCHARACTERISTICS_NX_COMPAT = 0x0100
                pass  # No direct exception directory flag in OptionalHeader
    except Exception:
        pass

    return {
        "imports": imports,
        "exports": exports,
        "has_exceptions": has_exceptions,
    }


# ---------------------------------------------------------------------------
# Mode: strings
# ---------------------------------------------------------------------------

def _mode_strings(program):
    """Extract strings via brute-force scan over memory blocks."""
    min_length_str = os.environ.get("GHIDRA_MIN_LENGTH", "5")
    try:
        min_length = int(min_length_str)
    except ValueError:
        min_length = 5

    max_candidates = 200
    all_strings = []
    blocks = program.getMemory().getBlocks()
    monitor = _get_monitor()

    from ghidra.app.util import StringSearch

    # Try Ghidra's built-in StringSearch first (faster in auto-analyzed programs)
    try:
        found = StringSearch.findStrings(program, monitor, min_length, -1, True)
        if found is not None:
            for fs in found:
                if len(all_strings) >= max_candidates:
                    break
                addr = fs.getAddress()
                val = str(fs.getValue())
                stype = str(fs.getType())
                all_strings.append({
                    "address": addr.getOffset() if addr else 0,
                    "value": val,
                    "length": len(val),
                    "type": "unicode" if "unicode" in stype.lower() else "ascii",
                })
    except Exception:
        pass

    # If StringSearch returned nothing or threw, fall back to brute force.
    # We always do the brute-force pass to catch strings StringSearch misses
    # in headless mode (the task plan says brute-force is more reliable).
    if not all_strings or len(all_strings) < max_candidates:
        brute_strings = []
        if blocks is not None:
            for block in blocks:
                if block.getSize() == 0:
                    continue
                # Skip blocks that are not initialized
                if block.isInitialized():
                    start = block.getStart()
                    end = block.getEnd()
                    start_off = start.getOffset() if start else 0
                    end_off = end.getOffset() if end else 0
                    # Scan ASCII
                    current_start = None
                    for i in range(int(end_off - start_off)):
                        ea = start_off + i
                        try:
                            b = program.getMemory().getByte(start.add(i))
                        except Exception:
                            b = 0
                        if 0x20 <= (b & 0xFF) <= 0x7E:
                            if current_start is None:
                                current_start = ea
                        else:
                            if current_start is not None:
                                run_len = ea - current_start
                                if run_len >= min_length:
                                    brute_strings.append({
                                        "address": current_start,
                                        "value": None,  # Fill below
                                        "length": run_len,
                                        "type": "ascii",
                                    })
                                current_start = None
                    # Trailing
                    if current_start is not None:
                        run_len = end_off - current_start
                        if run_len >= min_length:
                            brute_strings.append({
                                "address": current_start,
                                "value": None,
                                "length": run_len,
                                "type": "ascii",
                            })

                    # Scan UTF-16LE
                    current_start = None
                    for i in range(int(end_off - start_off) - 1):
                        ea = start_off + i
                        try:
                            lo = program.getMemory().getByte(start.add(i)) & 0xFF
                            hi = program.getMemory().getByte(start.add(i + 1)) & 0xFF
                        except Exception:
                            lo = 0
                            hi = 0
                        if 0x20 <= lo <= 0x7E and hi == 0:
                            if current_start is None:
                                current_start = ea
                        else:
                            if current_start is not None:
                                run_len_bytes = ea - current_start
                                char_count = run_len_bytes // 2
                                if char_count >= min_length:
                                    brute_strings.append({
                                        "address": current_start,
                                        "value": None,
                                        "length": char_count,
                                        "type": "unicode",
                                    })
                                current_start = None

        # Merge: deduplicate by address, preferring StringSearch values
        seen_addrs = set(s["address"] for s in all_strings)
        for s in brute_strings:
            if s["address"] not in seen_addrs and len(all_strings) < max_candidates:
                seen_addrs.add(s["address"])
                all_strings.append(s)

    # Read actual byte values for brute-force entries that have None value
    for s in all_strings:
        if s["value"] is not None:
            continue
        try:
            addr = program.getAddressFactory().getAddress(str(Long(s["address"])))
        except Exception:
            continue
        if addr is None:
            continue
        try:
            if s["type"] == "unicode":
                raw = bytearray()
                for i in range(s["length"] * 2):
                    b = program.getMemory().getByte(addr.add(i))
                    raw.append(b & 0xFF)
                s["value"] = str(raw.decode("utf-16-le", errors="replace"))
            else:
                raw = bytearray()
                for i in range(s["length"]):
                    b = program.getMemory().getByte(addr.add(i))
                    raw.append(b & 0xFF)
                s["value"] = str(raw.decode("ascii", errors="replace"))
        except Exception:
            s["value"] = ""

    # Filter out empty values and sort by length descending
    all_strings = [s for s in all_strings if s.get("value")]
    all_strings.sort(key=lambda x: x["length"], reverse=True)

    # Cap at 200
    displayed = all_strings[:200]

    return {
        "strings": displayed,
        "total_count": len(all_strings),
        "displayed_count": len(displayed),
    }


# ---------------------------------------------------------------------------
# Mode: disassembly
# ---------------------------------------------------------------------------

def _mode_disassembly(program):
    """Disassemble a region of code from a named section."""
    section_name = os.environ.get("GHIDRA_SECTION_NAME", ".text")
    offset_str = os.environ.get("GHIDRA_OFFSET", "0")
    size_str = os.environ.get("GHIDRA_SIZE", "256")

    try:
        offset = int(offset_str)
    except ValueError:
        offset = 0
    try:
        num_instructions = int(size_str)
    except ValueError:
        num_instructions = 256

    max_instructions = min(num_instructions, 500)

    # Architecture / mode
    lang = program.getLanguage()
    arch_str = str(lang.getProcessor())
    mode_str = str(lang.getLanguageDescription().getSize())

    # Find section
    block = program.getMemory().getBlock(section_name)
    if block is None:
        # Fallback: try first initialized executable block
        blocks = program.getMemory().getBlocks()
        if blocks is not None:
            for b in blocks:
                if b.isExecute() and b.isInitialized():
                    block = b
                    section_name = str(b.getName())
                    break

    if block is None:
        return {
            "architecture": arch_str,
            "mode": mode_str,
            "section_name": section_name,
            "offset": offset,
            "bytes_count": 0,
            "instructions": [],
            "truncated": False,
        }

    start = block.getStart()
    start_off = start.getOffset() if start else 0
    base_addr = start.add(offset)

    # Compute how many bytes from offset to end of block
    end_addr = block.getEnd()
    end_off = end_addr.getOffset() if end_addr else start_off + block.getSize()
    available_bytes = end_off - start_off - offset
    if available_bytes < 0:
        available_bytes = 0

    listing = program.getListing()
    instructions = []

    try:
        inst_iter = listing.getInstructions(base_addr, True)
        count = 0
        while inst_iter.hasNext() and count < max_instructions:
            inst = inst_iter.next()
            inst_addr = inst.getAddress()
            addr_off = inst_addr.getOffset() if inst_addr else 0
            mnemonic = str(inst.getMnemonicString())
            operands = str(inst.getOperands(0))
            # Get raw bytes
            try:
                raw_bytes = program.getMemory().getBytes(inst_addr, inst.getLength())
                bytes_str = " ".join("%02x" % (b & 0xFF) for b in raw_bytes)
            except Exception:
                bytes_str = ""
            instructions.append({
                "address": addr_off,
                "mnemonic": mnemonic,
                "operands": operands,
                "bytes": bytes_str,
            })
            count += 1
    except Exception:
        pass

    truncated = len(instructions) >= max_instructions

    return {
        "architecture": arch_str,
        "mode": mode_str,
        "section_name": section_name,
        "offset": offset,
        "bytes_count": available_bytes,
        "instructions": instructions,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Mode: file-info
# ---------------------------------------------------------------------------

def _mode_file_info(program):
    """Extract file-level metadata."""
    result = {}

    # Path
    path = ""
    try:
        path = str(program.getExecutablePath())
    except Exception:
        pass
    result["path"] = path

    # Hashes
    md5_hash = ""
    sha256_hash = ""
    try:
        md5_hash = str(program.getExecutableMD5())
    except Exception:
        pass
    try:
        sha256_hash = str(program.getExecutableSHA256())
    except Exception:
        pass
    result["md5"] = md5_hash
    result["sha256"] = sha256_hash

    # File size via Java File
    size_bytes = 0
    try:
        f = File(path)
        if f.exists():
            size_bytes = f.length()
    except Exception:
        pass
    result["size_bytes"] = size_bytes

    # PE detection
    is_pe = False
    subsystem = None
    is_dll = None
    is_exe = None
    entry_point = None
    architecture = None

    try:
        fmt = str(program.getExecutableFormat())
        is_pe = "PE" in fmt or "Portable" in fmt
    except Exception:
        fmt = ""

    # Architecture
    try:
        proc = program.getLanguage().getProcessor()
        architecture = str(proc)
    except Exception:
        pass

    # Entry point
    try:
        min_addr = program.getMinAddress()
        if min_addr is not None:
            fm = program.getFunctionManager()
            ep_func = fm.getFunctionAt(min_addr)
            if ep_func is not None:
                entry_point = ep_func.getEntryPoint().getOffset()
            else:
                entry_point = min_addr.getOffset()
    except Exception:
        pass

    # PE-specific fields from NT header
    try:
        from ghidra.app.util.bin.format.pe import NTHeader
        from ghidra.app.util.bin.format.pe import ImageDosHeader
        dos = ImageDosHeader(program.getMemory())
        nt = NTHeader(dos)
        pe_hdr = nt.getPEHeader()
        if pe_hdr is not None:
            chars_val = pe_hdr.getCharacteristics()
            is_dll = bool(chars_val & 0x2000)
            is_exe = bool(chars_val & 0x0002)
            subsys = pe_hdr.getSubsystem()
            mapping = {
                0: "UNKNOWN", 1: "NATIVE", 2: "WINDOWS_GUI", 3: "WINDOWS_CUI",
                5: "WINDOWS_CE_GUI", 10: "EFI_APPLICATION", 16: "WINDOWS_BOOT_APPLICATION",
            }
            subsystem = mapping.get(subsys, "0x%04x" % subsys)
    except Exception:
        pass

    result["is_pe"] = is_pe
    result["subsystem"] = subsystem
    result["architecture"] = architecture
    result["is_dll"] = is_dll
    result["is_exe"] = is_exe
    result["entry_point"] = entry_point

    # Timestamp via PE header
    timestamp = None
    try:
        from ghidra.app.util.bin.format.pe import NTHeader
        from ghidra.app.util.bin.format.pe import ImageDosHeader
        import time
        dos = ImageDosHeader(program.getMemory())
        nt = NTHeader(dos)
        file_hdr = nt.getFileHeader()
        if file_hdr is not None:
            ts = file_hdr.getTimeDateStamp()
            if ts != 0:
                timestamp = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)
                )
    except Exception:
        pass
    result["timestamp"] = timestamp

    return result


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

def main():
    mode = os.environ.get("GHIDRA_MODE")
    output_path = os.environ.get("GHIDRA_OUTPUT")

    if not mode:
        sys.exit("ERROR: GHIDRA_MODE environment variable must be set.")
    if not output_path:
        sys.exit("ERROR: GHIDRA_OUTPUT environment variable must be set.")

    program = getCurrentProgram()
    if program is None:
        sys.exit("ERROR: No program loaded in Ghidra.")

    # Dispatch
    if mode == "structure":
        result = _mode_structure(program)
    elif mode == "imports-exports":
        result = _mode_imports_exports(program)
    elif mode == "strings":
        result = _mode_strings(program)
    elif mode == "disassembly":
        result = _mode_disassembly(program)
    elif mode == "file-info":
        result = _mode_file_info(program)
    else:
        sys.exit("ERROR: Unknown GHIDRA_MODE: %s" % mode)

    # Write JSON output
    try:
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
    except IOError as exc:
        sys.exit("ERROR: Failed to write output to %s: %s" % (output_path, str(exc)))


if __name__ == "__main__":
    main()
