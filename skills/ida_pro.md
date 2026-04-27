---
name: ida_pro
description: Headless IDA Pro analysis — subprocess invocation, env-var parameter passing, auto-analysis, string scanning, error handling
tool_id: extract_pe_info
command_hint: extract_pe_info path=file_path (uses IDA Pro when configured)
---

## IDA Pro Headless Usage Guide

The backend can delegate to headless IDA Pro (`idat64`/`idal64`) for PE analysis when configured. IDA Pro provides deeper analysis than pefile — full auto-analysis with cross-references, decompilation, and robust string scanning. This guide covers subprocess invocation, parameter passing, output lifecycle, and common pitfalls.

### Headless Subprocess Invocation

The backend launches IDA Pro headless as:

```bash
idat64 -A -S<script> <binary>
```

- `-A`: Auto-mode — no GUI dialogs, no user interaction.
- `-S<script>`: IDAPython script to execute after loading the binary.
- `<binary>`: Path to the PE or DLL to analyse.

The binary path is read from `config["tool_configs"]["ida_pro"]`. If `None` (not configured), all analysis methods raise `AnalysisError` with the message "IDA Pro is not configured — set tool_configs.ida_pro".

The script path is resolved relative to `backend/analysis/ida_scripts/`. Available scripts:

| Script | Analysis Method |
|--------|-----------------|
| `analyze_pe_structure.py` | PE headers, sections, characteristics |
| `get_imports_exports.py` | Import/export tables |
| `extract_strings.py` | String extraction |
| `disassemble_function.py` | Code disassembly by section |
| `get_file_info.py` | File-level metadata, hashes |

### Parameter Passing via Environment Variables

Parameters are passed to IDAPython scripts **exclusively through environment variables** — never CLI arguments. This is the established backend pattern:

| Env Variable | Used By | Description |
|-------------|---------|-------------|
| `IDA_ANALYSIS_BIN_PATH` | All scripts | Path to the binary being analysed |
| `IDA_OUTPUT_PATH` | All scripts | Path for the JSON result file (written by script, read by backend, then deleted) |
| `IDA_MIN_LENGTH` | `extract_strings.py` | Minimum string length (integer, default depends on script) |
| `IDA_SECTION_NAME` | `disassemble_function.py` | Section name to disassemble (e.g. `.text`) |
| `IDA_OFFSET` | `disassemble_function.py` | Byte offset within section |
| `IDA_SIZE` | `disassemble_function.py` | Number of bytes / max instructions to disassemble |

### Temp Output File Lifecycle

1. Backend sets `IDA_OUTPUT_PATH` to `binary_path + ".ida_temp.json"`
2. IDAPython script writes JSON analysis result to this path
3. Backend reads and parses the JSON
4. Backend deletes the temp file in a `finally`-style block (best-effort — failures to delete are silently ignored)

If the expected output file is missing after the subprocess completes, the backend raises `AnalysisError` with the path. This can happen if the script crashed before writing or had a bug.

### Auto-Analysis Is Slow but Thorough

- IDA's auto-analysis (`idaapi.auto_wait()`) runs to completion before scripts produce output.
- This includes: function detection (FLIRT), cross-reference building, type propagation, string discovery.
- Expect **longer execution time** for large binaries (seconds to minutes depending on binary size).
- The backend enforces a **300-second timeout** (`_IDA_TIMEOUT = 300`). If exceeded, `AnalysisError` with timeout message is raised.

### Brute-Force ASCII/UTF-16LE String Scanning

The backend's IDA Pro string extraction uses explicit byte-by-byte brute-force scanning of memory. **Do not assume `idaapi.extract_strings()` or similar IDA API calls are used** — `extract_strings.py` does its own scanning because the built-in string API has inconsistent batch-mode availability across IDA versions.

The brute-force scan:

1. Iterates every byte in each memory section
2. Builds runs of consecutive printable ASCII (0x20–0x7E) — any non-printable byte breaks the run
3. Builds runs of UTF-16LE (printable ASCII + null byte pairs)
4. Filters to runs >= `IDA_MIN_LENGTH` characters
5. Returns a `strings` array of `{address, value, length, type}` objects
6. Capped at **5000 candidates** to manage output size

This means any encoded, obfuscated, or XOR-masked strings will likely be missed — they won't appear as contiguous printable runs in memory.

### Section Characteristics Human-Readable Lookup

The IDA Pro scripts don't use the PE section Characteristics bitmask directly — instead, they use the `idaapi.segattr_t` API:

| Attribute | Meaning |
|-----------|---------|
| `SEG_PERM_EXEC` | Section is executable (code) |
| `SEG_PERM_WRITE` | Section is writable |
| `SEG_PERM_READ` | Section is readable |

The output maps these to `"rwx"` format strings in the `sections` array. A section with both `EXEC` and `WRITE` (W^X violation) is suspicious and worth noting in analysis.

### Error Handling Modes

The `IdaProBackend._run_headless()` method handles errors in four distinct modes:

| Failure Mode | Error Type | Description |
|-------------|-----------|-------------|
| **Not configured** | `AnalysisError` | `self._ida_path is None` — "IDA Pro is not configured — set tool_configs.ida_pro" |
| **Timeout** | `AnalysisError` | `subprocess.TimeoutExpired` caught after `_IDA_TIMEOUT` (300s) |
| **Binary not found** | `AnalysisError` | `FileNotFoundError` from `subprocess.run` — "IDA Pro binary not found: <path>" |
| **Script failure** | `AnalysisError` | Non-zero return code — raises with stderr excerpt (first 2000 chars) |
| **Missing output** | `AnalysisError` | Output JSON file does not exist after subprocess exits |

All errors are logged at `logging.ERROR` with full traceback before re-raising as `AnalysisError`.

### Disassembly via IDA Pro

`disassemble_function` in IDA Pro mode uses the IDAPython disassembly API (`idaapi.decompile()` for decompilation, `idautils.FuncItems()` for instruction iteration). The output includes:

- `instructions`: Array of `{address, mnemonic, operands, bytes}` objects
- Truncation cap: **500 instructions max**
- Decompilation available (unlike the capstone backend) — the `pseudocode` field contains C-like decompilation output when Hex-Rays is available

### File Info

`get_file_info` via IDA Pro provides richer metadata than pefile:
- MD5 and SHA256 hashes (via IDA's `retrieve_input_file_md5()` / `retrieve_input_file_sha256()`)
- File type and format detection
- Compile timestamp (when available through PE header — same caveats as pefile apply)
