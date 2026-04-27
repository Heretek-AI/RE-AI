"""Generate minimal but valid PE DLL files for testing the analysis backend.

Provides ``make_minimal_pe`` (AMD64 DLL) and ``make_arm_pe`` (ARM DLL)
for use in fixture setup and unit tests.

Both generators construct PEs using raw struct packing (no pefile dependency
for construction -- pefile is only needed for verification). This avoids
relying on pefile's internal section construction API, which differs across
versions.

Usage
-----
    from tests.fixtures.make_test_pe import make_minimal_pe, make_arm_pe

    make_minimal_pe("/tmp/test.dll")
    make_arm_pe("/tmp/test_arm.dll")
"""

import struct
import uuid
from pathlib import Path
from typing import Optional

# ── Constants ────────────────────────────────────────────────────────────────

IMAGE_DOS_SIGNATURE = 0x5A4D  # MZ
IMAGE_NT_SIGNATURE = 0x00004550  # PE\0\0
IMAGE_NT_OPTIONAL_HDR32_MAGIC = 0x10B
IMAGE_NT_OPTIONAL_HDR64_MAGIC = 0x20B
IMAGE_SUBSYSTEM_WINDOWS_GUI = 2
IMAGE_FILE_MACHINE_AMD64 = 0x8664
IMAGE_FILE_MACHINE_ARMNT = 0x01C4  # ARM Thumb-2
IMAGE_FILE_RELOCS_STRIPPED = 0x0001
IMAGE_FILE_EXECUTABLE_IMAGE = 0x0002
IMAGE_FILE_LINE_NUMS_STRIPPED = 0x0004
IMAGE_FILE_LOCAL_SYMS_STRIPPED = 0x0008
IMAGE_FILE_LARGE_ADDRESS_AWARE = 0x0020
IMAGE_FILE_32BIT_MACHINE = 0x0100
IMAGE_FILE_DLL = 0x2000
IMAGE_FILE_DEBUG_STRIPPED = 0x0200

IMAGE_SCN_CNT_CODE = 0x00000020
IMAGE_SCN_CNT_INITIALIZED_DATA = 0x00000040
IMAGE_SCN_MEM_EXECUTE = 0x20000000
IMAGE_SCN_MEM_READ = 0x40000000
IMAGE_SCN_MEM_WRITE = 0x80000000

# DLL characteristics
IMAGE_DLLCHARACTERISTICS_HIGH_ENTROPY_VA = 0x0020
IMAGE_DLLCHARACTERISTICS_DYNAMIC_BASE = 0x0040
IMAGE_DLLCHARACTERISTICS_NX_COMPAT = 0x0100

# ── Embedded strings (for string extraction tests) ──────────────────────────
# Each is null-terminated and placed at a known offset in the binary

EMBEDDED_STRINGS = [
    b"HelloFromREAI\x00",
    b"REAI_ANALYSIS\x00",
    b"REAI_v1.0\x00",
    b"REAI_EntryPoint\x00",
]


def _build_embedded_bytes(min_str_length: int, text_block: bytes) -> bytes:
    """Append embedded strings to *text_block*, zeroing those under threshold."""
    for s in EMBEDDED_STRINGS:
        stripped = s.rstrip(b"\x00")
        if len(stripped) >= min_str_length:
            text_block += s
        else:
            text_block += b"\x00" * len(s)
    return text_block


def _align(value: int, alignment: int) -> int:
    """Round *value* up to the next *alignment* boundary."""
    return ((value + alignment - 1) // alignment) * alignment


# ── PE struct layouts (little-endian) ────────────────────────────────────────

# IMAGE_DOS_HEADER (64 bytes)
# e_magic(2) e_cblp(2) e_cp(2) e_crlc(2) e_cparhdr(2) e_minalloc(2)
# e_maxalloc(2) e_ss(2) e_sp(2) e_csum(2) e_ip(2) e_cs(2) e_lfarlc(2)
# e_ovno(2) e_res[4](8) e_oemid(2) e_oeminfo(2) e_res2[10](20) e_lfanew(4)
DOS_HEADER_FMT = "<14H4H2H10HI"
DOS_STUB = b"This program cannot be run in DOS mode.\r\n\r\n$"

# IMAGE_FILE_HEADER (20 bytes)
# Machine(2) NumberOfSections(2) TimeDateStamp(4) PointerToSymbolTable(4)
# NumberOfSymbols(4) SizeOfOptionalHeader(2) Characteristics(2)
FILE_HEADER_FMT = "<HHI2I2H"

# IMAGE_OPTIONAL_HEADER64 (112 bytes for PE32+, data dirs count at end)
# Magic(2) MajorLinkerVersion(1) MinorLinkerVersion(1) SizeOfCode(4)
# SizeOfInitializedData(4) SizeOfUninitializedData(4) AddressOfEntryPoint(4)
# BaseOfCode(4) ImageBase(8) SectionAlignment(4) FileAlignment(4)
# MajorOperatingSystemVersion(2) MinorOperatingSystemVersion(2)
# MajorImageVersion(2) MinorImageVersion(2) MajorSubsystemVersion(2)
# MinorSubsystemVersion(2) Win32VersionValue(4) SizeOfImage(4)
# SizeOfHeaders(4) CheckSum(4) Subsystem(2) DllCharacteristics(2)
# SizeOfStackReserve(8) SizeOfStackCommit(8) SizeOfHeapReserve(8)
# SizeOfHeapCommit(8) LoaderFlags(4) NumberOfRvaAndSizes(4)
# Then 16 IMAGE_DATA_DIRECTORY entries (8 bytes each: VirtualAddress(4) Size(4))
OPT_HDR64_FMT = "<HBBIIIIIQIIHHHHHHIIIIHHQQQQII"

# IMAGE_SECTION_HEADER (40 bytes)
# Name(8) VirtualSize(4) VirtualAddress(4) SizeOfRawData(4)
# PointerToRawData(4) PointerToRelocations(4) PointerToLinenumbers(4)
# NumberOfRelocations(2) NumberOfLinenumbers(2) Characteristics(4)
SECTION_HEADER_FMT = "<8s6I2HI"


def make_minimal_pe(path: str, min_str_length: int = 3) -> None:
    """Write a minimal but valid AMD64 PE DLL to *path*.

    The PE contains ``.text`` (executable code) and ``.data`` (readable/
    writable) sections with embedded printable ASCII strings for
    string-extraction testing.
    """
    file_alignment = 0x200
    section_alignment = 0x1000  # standard for PE32+

    # ── Section content ─────────────────────────────────────────────────
    # .text: x86-64 code (just `ret` = 0xC3) plus embedded strings
    text_code_core = b"\xC3"  # ret
    text_code = _build_embedded_bytes(min_str_length, text_code_core)
    text_raw_size = _align(len(text_code), file_alignment)
    text_code = text_code.ljust(text_raw_size, b"\x00")

    # .data: empty (readable/writable)
    data_content = b"\x00" * file_alignment

    # ── Layout calculation ─────────────────────────────────────────────-
    dos_header_size = 64
    dos_stub_size = _align(len(DOS_STUB) + 1, file_alignment)
    pe_sig_offset = dos_header_size + dos_stub_size
    nt_signature_size = 4
    file_header_size = 20
    opt_header_size = 112 + 16 * 8  # PE32+ optional + 16 data directories
    section_headers_size = 2 * 40  # 2 sections
    headers_size = _align(
        pe_sig_offset
        + nt_signature_size
        + file_header_size
        + opt_header_size
        + section_headers_size,
        file_alignment,
    )

    text_rva = 0x1000
    text_rva_aligned = _align(text_rva, section_alignment)
    data_rva = text_rva_aligned + _align(text_raw_size, section_alignment)
    data_rva_aligned = _align(data_rva, section_alignment)

    text_fo = headers_size
    data_fo = text_fo + text_raw_size

    image_size = data_rva_aligned + _align(file_alignment, section_alignment)

    # ── DOS Header ──────────────────────────────────────────────────────
    dos = struct.pack(
        DOS_HEADER_FMT,
        0x5A4D,  # e_magic (MZ)
        0x90,    # e_cblp
        3,       # e_cp
        0,       # e_crlc
        4,       # e_cparhdr
        0xFFFF,  # e_minalloc
        0xFFFF,  # e_maxalloc
        0,       # e_ss
        0xB8,    # e_sp
        0,       # e_csum
        0,       # e_ip
        0,       # e_cs
        0x40,    # e_lfarlc
        0,       # e_ovno
        0, 0, 0, 0,   # e_res[4]
        0,       # e_oemid
        0,       # e_oeminfo
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  # e_res2[10]
        pe_sig_offset,  # e_lfanew
    )

    # ── DOS stub ────────────────────────────────────────────────────────
    stub = DOS_STUB.ljust(dos_stub_size, b"\x00")

    # ── PE signature ────────────────────────────────────────────────────
    sig = b"PE\x00\x00"

    # ── File Header ─────────────────────────────────────────────────────
    time_date_stamp = 0x66000000  # fixed timestamp for reproducibility
    file_hdr = struct.pack(
        FILE_HEADER_FMT,
        IMAGE_FILE_MACHINE_AMD64,
        2,  # NumberOfSections
        time_date_stamp,
        0,  # PointerToSymbolTable
        0,  # NumberOfSymbols
        opt_header_size,  # SizeOfOptionalHeader
        IMAGE_FILE_EXECUTABLE_IMAGE
        | IMAGE_FILE_LARGE_ADDRESS_AWARE
        | IMAGE_FILE_DLL
        | IMAGE_FILE_LINE_NUMS_STRIPPED
        | IMAGE_FILE_LOCAL_SYMS_STRIPPED
        | IMAGE_FILE_RELOCS_STRIPPED
        | IMAGE_FILE_DEBUG_STRIPPED,
    )

    # ── Optional Header (PE32+) ─────────────────────────────────────────
    opt_hdr = struct.pack(
        OPT_HDR64_FMT,
        IMAGE_NT_OPTIONAL_HDR64_MAGIC,
        14,  # MajorLinkerVersion
        32,  # MinorLinkerVersion
        text_raw_size,  # SizeOfCode
        file_alignment,  # SizeOfInitializedData
        0,  # SizeOfUninitializedData
        text_rva_aligned,  # AddressOfEntryPoint
        text_rva_aligned,  # BaseOfCode
        0x180000000,  # ImageBase (typical DLL base)
        section_alignment,
        file_alignment,
        6,  # MajorOSVersion
        0,  # MinorOSVersion
        0,  # MajorImageVersion
        0,  # MinorImageVersion
        6,  # MajorSubsystemVersion
        0,  # MinorSubsystemVersion
        0,  # Win32VersionValue
        image_size,  # SizeOfImage
        headers_size,  # SizeOfHeaders
        0,  # CheckSum
        IMAGE_SUBSYSTEM_WINDOWS_GUI,
        IMAGE_DLLCHARACTERISTICS_HIGH_ENTROPY_VA
        | IMAGE_DLLCHARACTERISTICS_DYNAMIC_BASE
        | IMAGE_DLLCHARACTERISTICS_NX_COMPAT,
        0x100000,  # SizeOfStackReserve
        0x1000,  # SizeOfStackCommit
        0x100000,  # SizeOfHeapReserve
        0x1000,  # SizeOfHeapCommit
        0,  # LoaderFlags
        16,  # NumberOfRvaAndSizes
    )

    # ── Data directories (all empty) ─────────────────────────────────────
    data_dirs = struct.pack("<" + "II" * 16, *([0] * 32))

    # ── Section Headers ─────────────────────────────────────────────────
    text_hdr = struct.pack(
        SECTION_HEADER_FMT,
        b".text\x00\x00\x00",
        text_raw_size,  # VirtualSize
        text_rva_aligned,  # VirtualAddress
        text_raw_size,  # SizeOfRawData
        text_fo,  # PointerToRawData
        0,  # PointerToRelocations
        0,  # PointerToLinenumbers
        0,  # NumberOfRelocations
        0,  # NumberOfLinenumbers
        IMAGE_SCN_CNT_CODE | IMAGE_SCN_MEM_EXECUTE | IMAGE_SCN_MEM_READ,
    )
    data_hdr = struct.pack(
        SECTION_HEADER_FMT,
        b".data\x00\x00\x00",
        file_alignment,  # VirtualSize
        data_rva_aligned,  # VirtualAddress
        file_alignment,  # SizeOfRawData
        data_fo,  # PointerToRawData
        0,  # PointerToRelocations
        0,  # PointerToLinenumbers
        0,  # NumberOfRelocations
        0,  # NumberOfLinenumbers
        IMAGE_SCN_CNT_INITIALIZED_DATA | IMAGE_SCN_MEM_READ | IMAGE_SCN_MEM_WRITE,
    )

    section_hdrs = text_hdr + data_hdr

    # ── Assemble ────────────────────────────────────────────────────────
    buf = bytearray()
    buf.extend(dos)
    buf.extend(stub)
    buf.extend(sig)
    buf.extend(file_hdr)
    buf.extend(opt_hdr)
    buf.extend(data_dirs)
    buf.extend(section_hdrs)

    # Pad to headers_size
    while len(buf) < headers_size:
        buf.append(0)

    # Section data
    buf.extend(text_code)
    buf.extend(data_content)

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(buf)


def make_arm_pe(path: str, min_str_length: int = 3) -> None:
    """Write a minimal ARM PE DLL (Thumb mode) to *path*.

    Uses the same layout as ``make_minimal_pe`` but with ARM machine type
    (0x01C4), 32-bit machine flag, and ARM Thumb code (BX LR = 0x4770).
    """
    file_alignment = 0x200
    section_alignment = 0x1000

    # ── Section content ─────────────────────────────────────────────────
    text_code_core = b"\x70\x47"  # BX LR (ARM Thumb return)
    text_code = _build_embedded_bytes(min_str_length, text_code_core)
    text_raw_size = _align(len(text_code), file_alignment)
    text_code = text_code.ljust(text_raw_size, b"\x00")

    data_content = b"\x00" * file_alignment

    # ── Layout ──────────────────────────────────────────────────────────
    dos_header_size = 64
    dos_stub_size = _align(len(DOS_STUB) + 1, file_alignment)
    pe_sig_offset = dos_header_size + dos_stub_size
    nt_signature_size = 4
    file_header_size = 20
    opt_header_size = 112 + 16 * 8
    section_headers_size = 2 * 40
    headers_size = _align(
        pe_sig_offset
        + nt_signature_size
        + file_header_size
        + opt_header_size
        + section_headers_size,
        file_alignment,
    )

    text_rva = 0x1000
    text_rva_aligned = _align(text_rva, section_alignment)
    data_rva = text_rva_aligned + _align(text_raw_size, section_alignment)
    data_rva_aligned = _align(data_rva, section_alignment)
    text_fo = headers_size
    data_fo = text_fo + text_raw_size
    image_size = data_rva_aligned + _align(file_alignment, section_alignment)

    # ── DOS ─────────────────────────────────────────────────────────────
    dos = struct.pack(
        DOS_HEADER_FMT,
        0x5A4D,  # e_magic
        0x90, 3, 0, 4, 0xFFFF, 0xFFFF, 0, 0xB8, 0, 0, 0, 0x40, 0,
        0, 0, 0, 0,  # e_res[4]
        0, 0,  # e_oemid, e_oeminfo
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0,  # e_res2[10]
        pe_sig_offset,
    )
    stub = DOS_STUB.ljust(dos_stub_size, b"\x00")

    # ── Signature ───────────────────────────────────────────────────────
    sig = b"PE\x00\x00"

    # ── File Header ─────────────────────────────────────────────────────
    file_hdr = struct.pack(
        FILE_HEADER_FMT,
        IMAGE_FILE_MACHINE_ARMNT,
        2, 0x66000000, 0, 0,
        opt_header_size,
        IMAGE_FILE_EXECUTABLE_IMAGE
        | IMAGE_FILE_LARGE_ADDRESS_AWARE
        | IMAGE_FILE_DLL
        | IMAGE_FILE_32BIT_MACHINE
        | IMAGE_FILE_LINE_NUMS_STRIPPED
        | IMAGE_FILE_LOCAL_SYMS_STRIPPED
        | IMAGE_FILE_RELOCS_STRIPPED
        | IMAGE_FILE_DEBUG_STRIPPED,
    )

    # ── Optional Header ─────────────────────────────────────────────────
    opt_hdr = struct.pack(
        OPT_HDR64_FMT,
        IMAGE_NT_OPTIONAL_HDR64_MAGIC,
        14, 32,
        text_raw_size,
        file_alignment,
        0,
        text_rva_aligned,
        text_rva_aligned,
        0x180000000,
        section_alignment,
        file_alignment,
        6, 0, 0, 0, 6, 0,
        0,
        image_size,
        headers_size,
        0,
        IMAGE_SUBSYSTEM_WINDOWS_GUI,
        IMAGE_DLLCHARACTERISTICS_HIGH_ENTROPY_VA
        | IMAGE_DLLCHARACTERISTICS_DYNAMIC_BASE
        | IMAGE_DLLCHARACTERISTICS_NX_COMPAT,
        0x100000, 0x1000, 0x100000, 0x1000,
        0, 16,
    )

    data_dirs = struct.pack("<" + "II" * 16, *([0] * 32))

    text_hdr = struct.pack(
        SECTION_HEADER_FMT,
        b".text\x00\x00\x00",
        text_raw_size, text_rva_aligned, text_raw_size, text_fo,
        0, 0, 0, 0,
        IMAGE_SCN_CNT_CODE | IMAGE_SCN_MEM_EXECUTE | IMAGE_SCN_MEM_READ,
    )
    data_hdr = struct.pack(
        SECTION_HEADER_FMT,
        b".data\x00\x00\x00",
        file_alignment, data_rva_aligned, file_alignment, data_fo,
        0, 0, 0, 0,
        IMAGE_SCN_CNT_INITIALIZED_DATA | IMAGE_SCN_MEM_READ | IMAGE_SCN_MEM_WRITE,
    )

    buf = bytearray()
    buf.extend(dos)
    buf.extend(stub)
    buf.extend(sig)
    buf.extend(file_hdr)
    buf.extend(opt_hdr)
    buf.extend(data_dirs)
    buf.extend(text_hdr + data_hdr)
    while len(buf) < headers_size:
        buf.append(0)
    buf.extend(text_code)
    buf.extend(data_content)

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(buf)


if __name__ == "__main__":
    out_dir = Path(__file__).resolve().parent
    make_minimal_pe(str(out_dir / "minimal_test.dll"))
    print(f"Generated: {out_dir / 'minimal_test.dll'}")
    make_arm_pe(str(out_dir / "test_arm.dll"))
    print(f"Generated: {out_dir / 'test_arm.dll'}")
