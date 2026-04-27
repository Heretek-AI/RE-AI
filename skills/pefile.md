---
name: pefile
description: PE parsing via pefile — headers, sections, imports/exports, imphash, error handling
tool_id: extract_pe_info
command_hint: extract_pe_info path=file_path
---

## pefile Usage Guide

The backend uses `pefile` (Python PE parsing library) for all PE structure analysis. The `extract_pe_info` tool delegates to the PE analysis backend which wraps pefile internally. Understanding how pefile works helps you interpret results and diagnose issues.

### Loading Strategies

- **`fast_load` mode** (default in the backend): Reads only DOS and NT headers without parsing data directories. Use when you only need machine type, characteristics, or entry point. Faster and safer for malformed files.
- **`parse_data_directories`** (full parse): Parses import tables, export tables, resources, and other data directories. Required for `list_imports_exports` and detailed section analysis. The backend calls this automatically when needed.

### PE Characteristics Checks

- **`is_dll()`** / **`is_exe()`**: The backend exposes these as `is_dll` and `is_exe` boolean fields. A PE can be neither (e.g. `.sys` driver files are IMAGE_FILE_EXECUTABLE_IMAGE without either subsystem flag).
- **`IMAGE_FILE_DLL`** (0x2000): Set on DLL files.
- **`IMAGE_FILE_EXECUTABLE_IMAGE`** (0x0002): Set on all executable images.

### Import/Export Guard Pattern

Always guard import table access:

```python
if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
    for entry in pe.DIRECTORY_ENTRY_IMPORT:
        ...
```

Not all PEs have import tables — packed or statically linked executables may omit them. Export tables follow the same pattern with `DIRECTORY_ENTRY_EXPORT`.

### Imphash

- **Imphash** (Import Hash): MD5 hash of the normalized import table. Used for malware variant identification — same family typically has the same imphash.
- The backend exposes imphash in `extract_pe_info` output as `imphash`.
- Imphash is order-dependent: import table ordering varies between linkers, so identical imports from different compilers may produce different hashes.
- Impfuzzy (fuzzy imphash via ssdeep) is not computed by the backend — rely on imphash for exact matching.

### Section Name Normalization

pefile returns section names as 8-byte null-terminated strings from the COFF section table. The backend strips null bytes automatically, so names like `b".text\x00\x00\x00"` become `".text"`. However, if you see truncated names (e.g. `.rsrc` vs `.rsrc\0\0\0`), this is normal PE behavior — section names are at most 8 characters in the COFF header.

### Error Handling

- **`PEFormatError`**: Raised when the file is not a valid PE (non-PE files, corrupted headers). The backend wraps this as `AnalysisError` with the message "Not a valid PE file: <path>".
- **Truncated files**: pefile reads directly from disk — a truncated PE raises `PEFormatError` rather than returning partial data.
- **Large files**: pefile loads the entire PE into memory. For files over ~100MB, expect increased memory usage.

### Machine Type Mapping

The backend translates pefile machine IDs to human-readable strings:

| Machine ID | Architecture | Notes |
|------------|-------------|-------|
| `0x8664` | AMD64 | x86-64 (x64) |
| `0x14c` | I386 | x86-32 (i386) |
| `0x1c0` | ARM | ARM Little Endian (ARMv7) |
| `0xaa64` | ARM64 | AArch64 |
| `0x1c4` | ARM Thumb | ARMv7 Thumb mode |
| `0x5032` | IA64 | Itanium (rare) |
| `0x8664` → AMD64 is the most common for modern Windows malware |

### PE Timestamp Caveats

- The IMAGE_FILE_HEADER.TimeDateStamp field is **not reliable** for dating a binary:
  - Often set to the compile timestamp (not the linker timestamp).
  - Can be zeroed by intentional stripping or tools like `editbin`.
  - Some compilers (e.g. MSVC with deterministic builds) set it to a fixed value.
  - Malware authors routinely manipulate this field.
- The backend does **not** expose this field directly to avoid misleading analysis.

### Section Characteristics Flags

Section headers have a `Characteristics` bitmask. Key flags to check in the backend output:

| Flag Value | Name | Meaning |
|-----------|------|---------|
| `0x20000000` | IMAGE_SCN_MEM_EXECUTE | Section contains executable code (`.text` should have this) |
| `0x40000000` | IMAGE_SCN_MEM_READ | Section is readable (almost all sections) |
| `0x80000000` | IMAGE_SCN_MEM_WRITE | Section is writable (`.data`, `.rsrc` — suspicious on `.text`) |
| `0x02000000` | IMAGE_SCN_CNT_CODE | Section contains code |
| `0x04000000` | IMAGE_SCN_CNT_INITIALIZED_DATA | Section contains initialized data |
| `0x08000000` | IMAGE_SCN_CNT_UNINITIALIZED_DATA | Section contains uninitialized data (`.bss`) |

A section with **W^X violation** (both EXECUTE and WRITE set) is suspicious — it suggests self-modifying code or a packer.

### Resource Section Pattern

The IMAGE_DIRECTORY_ENTRY_RESOURCE data directory (index 2) describes the resource tree. The backend doesn't parse resources directly — use `extract_strings` to find embedded content in the `.rsrc` section instead. Resource directories are structured as a 3-level tree: Type → Name → Language ID.
