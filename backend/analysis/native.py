"""Native Python analysis backend using pefile + capstone.

Implements :class:`AbstractAnalysisBackend` with pure-Python libraries —
no external reverse-engineering tooling required.  This is the baseline
backend that works without IDA Pro or Ghidra.
"""

from __future__ import annotations

import hashlib
import logging
import os
import traceback
from typing import Any

import anyio
import capstone
import pefile

from backend.analysis.base import AbstractAnalysisBackend, AnalysisError

logger = logging.getLogger("backend.analysis.native")

# ── Machine-type → human-readable mapping ────────────────────────────────

_MACHINE_NAMES: dict[int, str] = {
    0x8664: "AMD64",
    0x14C: "I386",
    0x1C4: "ARM",
    0xAA64: "ARM64",
}


def _machine_name(machine: int) -> str:
    return _MACHINE_NAMES.get(machine, "UNKNOWN")


# ── Subsystem → human-readable mapping ───────────────────────────────────

_SUBSYSTEM_NAMES: dict[int, str] = {
    1: "NATIVE",
    2: "WINDOWS_GUI",
    3: "WINDOWS_CUI",
    5: "OS2_CUI",
    7: "POSIX_CUI",
    9: "WINDOWS_CE_GUI",
    10: "EFI_APPLICATION",
    11: "EFI_BOOT_SERVICE_DRIVER",
    12: "EFI_RUNTIME_DRIVER",
    13: "EFI_ROM",
    14: "XBOX",
    16: "WINDOWS_BOOT_APPLICATION",
}


def _subsystem_name(subsystem: int) -> str:
    return _SUBSYSTEM_NAMES.get(subsystem, f"UNKNOWN({subsystem})")


# ── Architecture → capstone mapping ──────────────────────────────────────

_CAPSTONE_MAP: dict[int, tuple[int, int]] = {
    0x8664: (capstone.CS_ARCH_X86, capstone.CS_MODE_64),
    0x14C: (capstone.CS_ARCH_X86, capstone.CS_MODE_32),
    0x1C4: (capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM),
    0xAA64: (capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM),
}


def _capstone_arch(machine: int) -> tuple[int, int]:
    """Return ``(arch, mode)`` for *machine*, defaulting to x86-64."""
    return _CAPSTONE_MAP.get(machine, (capstone.CS_ARCH_X86, capstone.CS_MODE_64))


# ── Helper: section name stripping ───────────────────────────────────────

def _section_name(section: pefile.SectionStructure) -> str:
    """Return the section name with null-bytes stripped."""
    raw = getattr(section, "Name", b"")
    return raw.rstrip(b"\x00").decode("ascii", errors="replace")


# ── String extraction helpers ────────────────────────────────────────────

def _extract_ascii_strings(data: bytes, min_length: int) -> list[dict[str, Any]]:
    """Find ASCII strings (bytes 0x20-0x7E) of at least *min_length*."""
    results: list[dict[str, Any]] = []
    current: list[bytes] = []
    for i, byte in enumerate(data):
        if 0x20 <= byte <= 0x7E:
            current.append(bytes([byte]))
        else:
            if current:
                s = b"".join(current)
                if len(s) >= min_length:
                    offset = i - len(s)
                    results.append({"string": s.decode("ascii"), "offset": offset})
                current = []
    # Handle trailing string
    if current:
        s = b"".join(current)
        if len(s) >= min_length:
            offset = len(data) - len(s)
            results.append({"string": s.decode("ascii"), "offset": offset})
    return results


def _extract_unicode_strings(data: bytes, min_length: int) -> list[dict[str, Any]]:
    """Find UTF-16LE strings where every char is printable ASCII."""
    results: list[dict[str, Any]] = []
    # Work in pairs (2-byte units)
    i = 0
    while i < len(data) - 1:
        lo = data[i]
        hi = data[i + 1]
        # Printable ASCII char (0x0020-0x007E) followed by \x00
        if 0x20 <= lo <= 0x7E and hi == 0x00:
            # Start of a potential unicode string
            start = i
            chars: list[bytes] = [bytes([lo, hi])]
            i += 2
            while i < len(data) - 1:
                lo2 = data[i]
                hi2 = data[i + 1]
                if lo2 == 0x00 and hi2 == 0x00:
                    break  # null terminator
                if 0x20 <= lo2 <= 0x7E and hi2 == 0x00:
                    chars.append(bytes([lo2, hi2]))
                    i += 2
                else:
                    break
            s_raw = b"".join(chars)
            s = s_raw.decode("utf-16-le", errors="replace")
            if len(s) >= min_length:
                results.append({"string": s, "offset": start})
        else:
            i += 2
    return results


# ═══════════════════════════════════════════════════════════════════════════
# NativePythonBackend
# ═══════════════════════════════════════════════════════════════════════════


class NativePythonBackend(AbstractAnalysisBackend):
    """Analysis backend that uses pefile + capstone directly.

    All pefile I/O is offloaded to a thread pool via ``anyio.to_thread``
    to avoid blocking the async event loop.  Capstone operations are
    synchronous and fast enough to run in the calling task.
    """

    # ── Constructor ──────────────────────────────────────────────────────

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Backward-compatible constructor.

        Accepts an optional *config* dict for API compatibility with
        ``IdaProBackend`` but ignores it — this backend needs no
        configuration.
        """
        super().__init__()
        # config is accepted but ignored

    # ── PE loading helper ──────────────────────────────────────────────────

    @staticmethod
    def _load_pe_sync(path: str) -> pefile.PE:
        """Synchronous helper that loads a PE file (called in thread pool)."""
        return pefile.PE(path, fast_load=True)

    # ── analyze_pe_structure ───────────────────────────────────────────────

    async def analyze_pe_structure(self, path: str) -> dict[str, Any]:
        logger.debug("analyze_pe_structure: %s", path)
        try:
            pe = await anyio.to_thread.run_sync(self._load_pe_sync, path)
            result = self._analyze_pe_body(pe)
            logger.debug("analyze_pe_structure OK: %s", path)
            return result
        except pefile.PEFormatError as exc:
            logger.error("analyze_pe_structure PEFormatError: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc
        except FileNotFoundError as exc:
            logger.error("analyze_pe_structure FileNotFoundError: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc
        except Exception as exc:
            logger.error("analyze_pe_structure error: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc

    def _analyze_pe_body(self, pe: pefile.PE) -> dict[str, Any]:
        sections: list[dict[str, Any]] = []
        for section in pe.sections:
            sections.append({
                "name": _section_name(section),
                "virtual_address": section.VirtualAddress,
                "virtual_size": section.Misc_VirtualSize,
                "size_of_raw_data": section.SizeOfRawData,
                "pointer_to_raw_data": section.PointerToRawData,
                "characteristics": hex(section.Characteristics),
            })

        machine = pe.FILE_HEADER.Machine
        subsystem = pe.OPTIONAL_HEADER.Subsystem

        return {
            "machine_type": _machine_name(machine),
            "characteristics": hex(pe.FILE_HEADER.Characteristics),
            "is_dll": pe.is_dll(),
            "is_exe": pe.is_exe(),
            "subsystems": [_subsystem_name(subsystem)],
            "sections": sections,
            "entry_point": pe.OPTIONAL_HEADER.AddressOfEntryPoint,
            "image_base": pe.OPTIONAL_HEADER.ImageBase,
            "size_of_image": pe.OPTIONAL_HEADER.SizeOfImage,
            "imphash": pe.get_imphash(),
        }

    # ── get_imports_exports ────────────────────────────────────────────────

    async def get_imports_exports(self, path: str) -> dict[str, Any]:
        logger.debug("get_imports_exports: %s", path)
        try:
            pe = await anyio.to_thread.run_sync(self._load_pe_sync, path)
            result = await anyio.to_thread.run_sync(self._parse_imports_exports, pe)
            logger.debug("get_imports_exports OK: %s", path)
            return result
        except pefile.PEFormatError as exc:
            logger.error("get_imports_exports PEFormatError: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc
        except FileNotFoundError as exc:
            logger.error("get_imports_exports FileNotFoundError: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc
        except Exception as exc:
            logger.error("get_imports_exports error: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc

    @staticmethod
    def _parse_imports_exports(pe: pefile.PE) -> dict[str, Any]:
        pe.parse_data_directories()

        imports: list[dict[str, Any]] = []
        if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
            for entry in pe.DIRECTORY_ENTRY_IMPORT:
                dll_name = entry.dll.decode("utf-8", errors="replace") if entry.dll else ""
                funcs: list[dict[str, Any]] = []
                for imp in entry.imports:
                    func_name: str | None = None
                    if imp.name:
                        func_name = imp.name.decode("utf-8", errors="replace")
                    funcs.append({
                        "name": func_name,
                        "hint": imp.hint,
                        "ordinal": imp.ordinal,
                        "address": imp.address,
                        "import_by_ordinal": imp.import_by_ordinal(),
                    })
                imports.append({"dll": dll_name, "imports": funcs})

        exports: list[dict[str, Any]] = []
        has_exceptions = False
        if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
            export_dir = pe.DIRECTORY_ENTRY_EXPORT
            for exp in export_dir.symbols:
                exp_name: str | None = None
                if exp.name:
                    exp_name = exp.name.decode("utf-8", errors="replace")
                forwarder: str | None = None
                if exp.forwarder:
                    forwarder = exp.forwarder.decode("utf-8", errors="replace")
                exports.append({
                    "name": exp_name,
                    "ordinal": exp.ordinal,
                    "address": exp.address,
                    "forwarder_string": forwarder,
                })

        if hasattr(pe, "DIRECTORY_ENTRY_EXCEPTION"):
            has_exceptions = True

        return {
            "imports": imports,
            "exports": exports,
            "has_exceptions": has_exceptions,
        }

    # ── extract_strings ────────────────────────────────────────────────────

    async def extract_strings(self, path: str, min_length: int = 5) -> dict[str, Any]:
        logger.debug("extract_strings: %s (min_length=%d)", path, min_length)
        try:
            pe = await anyio.to_thread.run_sync(self._load_pe_sync, path)
            result = await anyio.to_thread.run_sync(
                self._extract_strings_from_pe, pe, min_length
            )
            logger.debug("extract_strings OK: %s (total=%d)", path, result["total_count"])
            return result
        except pefile.PEFormatError as exc:
            logger.error("extract_strings PEFormatError: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc
        except FileNotFoundError as exc:
            logger.error("extract_strings FileNotFoundError: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc
        except Exception as exc:
            logger.error("extract_strings error: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc

    @staticmethod
    def _extract_strings_from_pe(pe: pefile.PE, min_length: int) -> dict[str, Any]:
        # Collect all section data
        section_data: list[bytes] = []
        for section in pe.sections:
            section_data.append(section.get_data())

        all_bytes = b"".join(section_data)

        # Extract strings
        ascii_strs = _extract_ascii_strings(all_bytes, min_length)
        unicode_strs = _extract_unicode_strings(all_bytes, min_length)

        # Merge and deduplicate: same string text → keep first offset
        seen: dict[str, int] = {}
        for entry in ascii_strs + unicode_strs:
            text = entry["string"]
            if text not in seen:
                seen[text] = entry["offset"]

        # Build result list
        all_strings: list[dict[str, Any]] = [
            {"string": text, "offset": offset}
            for text, offset in seen.items()
        ]

        total_count = len(all_strings)

        # Sort: longest first, then alphabetically
        all_strings.sort(key=lambda x: (-len(x["string"]), x["string"]))

        # Cap at 200
        displayed = all_strings[:200]
        truncated = total_count > 200

        return {
            "strings": displayed,
            "total_count": total_count,
            "displayed_count": len(displayed),
            "truncated": truncated,
        }

    # ── disassemble_function ───────────────────────────────────────────────

    async def disassemble_function(
        self,
        path: str,
        section_name: str,
        offset: int,
        size: int = 256,
    ) -> dict[str, Any]:
        logger.debug(
            "disassemble_function: %s section=%s offset=%d size=%d",
            path, section_name, offset, size,
        )
        try:
            pe = await anyio.to_thread.run_sync(self._load_pe_sync, path)
            result = self._disassemble_body(pe, section_name, offset, size)
            logger.debug(
                "disassemble_function OK: %s (%d instructions)",
                path, len(result["instructions"]),
            )
            return result
        except pefile.PEFormatError as exc:
            logger.error("disassemble_function PEFormatError: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc
        except FileNotFoundError as exc:
            logger.error("disassemble_function FileNotFoundError: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc
        except Exception as exc:
            logger.error("disassemble_function error: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc

    def _disassemble_body(
        self,
        pe: pefile.PE,
        section_name: str,
        offset: int,
        size: int,
    ) -> dict[str, Any]:
        # Find section by name
        target = section_name.encode("ascii")
        matched_section: pefile.SectionStructure | None = None
        for section in pe.sections:
            name_raw = getattr(section, "Name", b"")
            name_stripped = name_raw.rstrip(b"\x00")
            if name_stripped == target:
                matched_section = section
                break

        if matched_section is None:
            raise AnalysisError(
                f"Section {section_name!r} not found in {pe.filename!r}"
            )

        # Read bytes, clamped to available data
        section_data = matched_section.get_data()
        available = len(section_data) - offset
        if available <= 0:
            raise AnalysisError(
                f"Offset {offset} is beyond section {section_name!r} data "
                f"(size={len(section_data)})"
            )
        actual_size = min(size, available)
        code_bytes = section_data[offset : offset + actual_size]

        # Detect architecture
        machine = pe.FILE_HEADER.Machine
        arch, mode = _capstone_arch(machine)

        # Map names
        arch_name = _machine_name(machine)
        mode_name = {capstone.CS_MODE_64: "64-bit", capstone.CS_MODE_32: "32-bit", capstone.CS_MODE_ARM: "ARM"}.get(mode, str(mode))

        # Disassemble
        base_address = matched_section.VirtualAddress + offset
        md = capstone.Cs(arch, mode)
        md.detail = False  # skip detailed operand info for speed
        instructions: list[dict[str, Any]] = []
        for insn in md.disasm(code_bytes, base_address):
            instructions.append({
                "address": insn.address,
                "mnemonic": insn.mnemonic,
                "operands": insn.op_str,
                "bytes": insn.bytes.hex(),
                "size": insn.size,
            })

        truncated = len(instructions) > 500
        if truncated:
            instructions = instructions[:500]

        return {
            "architecture": arch_name,
            "mode": mode_name,
            "section_name": section_name,
            "offset": offset,
            "bytes_count": len(code_bytes),
            "instructions": instructions,
            "truncated": truncated,
        }

    # ── get_file_info ──────────────────────────────────────────────────────

    async def get_file_info(self, path: str) -> dict[str, Any]:
        logger.debug("get_file_info: %s", path)
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"File not found: {path}")

            size_bytes = os.path.getsize(path)

            # Compute hashes
            md5 = hashlib.md5()
            sha256 = hashlib.sha256()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    md5.update(chunk)
                    sha256.update(chunk)

            # Try to load as PE
            try:
                pe = await anyio.to_thread.run_sync(
                    lambda: pefile.PE(path, fast_load=True)
                )
            except pefile.PEFormatError:
                # Not a PE file — return basic info
                logger.debug("get_file_info not PE: %s", path)
                return {
                    "path": path,
                    "size_bytes": size_bytes,
                    "md5": md5.hexdigest(),
                    "sha256": sha256.hexdigest(),
                    "is_pe": False,
                    "subsystem": None,
                    "architecture": None,
                    "is_dll": None,
                    "is_exe": None,
                    "entry_point": None,
                    "timestamp": None,
                }

            # PE detected
            machine = pe.FILE_HEADER.Machine
            subsystem = pe.OPTIONAL_HEADER.Subsystem
            result = {
                "path": path,
                "size_bytes": size_bytes,
                "md5": md5.hexdigest(),
                "sha256": sha256.hexdigest(),
                "is_pe": True,
                "subsystem": _subsystem_name(subsystem),
                "architecture": _machine_name(machine),
                "is_dll": pe.is_dll(),
                "is_exe": pe.is_exe(),
                "entry_point": pe.OPTIONAL_HEADER.AddressOfEntryPoint,
                "timestamp": None,
            }
            logger.debug("get_file_info OK PE: %s", path)
            return result

        except FileNotFoundError as exc:
            logger.error("get_file_info FileNotFoundError: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc
        except Exception as exc:
            logger.error("get_file_info error: %s\n%s", path, traceback.format_exc())
            raise AnalysisError(str(exc)) from exc
