---
name: ghidra
description: Headless Ghidra analysis — analyzeHeadless CLI, 5-mode script dispatch, Jython constraints, temp project lifecycle
tool_id: extract_pe_info
command_hint: extract_pe_info path=file_path (uses Ghidra when configured)
---

## Ghidra Headless Usage Guide

The backend can delegate to headless Ghidra (`analyzeHeadless`) for PE analysis when configured. Ghidra provides deep auto-analysis with a different character than IDA Pro — stronger scripting flexibility but slower project creation. This guide covers CLI invocation with temp project management, the 5-mode dispatch, Jython runtime constraints, cleanup patterns, and string extraction strategy.

### `analyzeHeadless` CLI Invocation

The backend launches Ghidra headless with a temporary project:

```bash
analyzeHeadless <temp_dir> TempProject \
    -import <binary> \
    -postScript ghidra_analysis.py \
    -scriptPath <scripts_dir> \
    -deleteProject \
    -readOnly \
    -analysisTimeoutPerFile 360
```

Key flags:
- `<temp_dir> TempProject`: A temporary directory and project name — created fresh for each analysis and **deleted in the `finally` block** via `shutil.rmtree`.
- `-import <binary>`: Binary to import and analyse.
- `-postScript ghidra_analysis.py`: The single Jython script that dispatches to 5 modes via `GHIDRA_MODE` env var.
- `-scriptPath <scripts_dir>`: Points to `backend/analysis/ghidra_scripts/`.
- `-deleteProject`: Ghidra cleans up the project files on exit (belt-and-suspenders with the manual `shutil.rmtree`).
- `-readOnly`: Prevents modification of the original binary — critical for not corrupting the evidence file.
- `-analysisTimeoutPerFile 360`: Per-file analysis timeout in seconds.

The binary path is read from `config["tool_configs"]["ghidra"]`. If `None` (not configured), all analysis methods raise `AnalysisError` with "Ghidra is not configured — set tool_configs.ghidra".

### Single 5-Mode Script Dispatch (Avoids Slow Project Creation)

Ghidra project creation takes **5–10 seconds** per invocation. Instead of running separate scripts for each analysis mode (which would require a fresh `analyzeHeadless` call per mode), the backend uses a single script (`ghidra_analysis.py`) with a **mode dispatch via the `GHIDRA_MODE` environment variable**.

Available modes:

| `GHIDRA_MODE` | Backend Method | Description |
|---------------|---------------|-------------|
| `structure` | `analyze_pe_structure` | PE header, sections, characteristics, imphash |
| `imports-exports` | `get_imports_exports` | Import/export tables |
| `strings` | `extract_strings` | Dual-strategy string extraction |
| `disassembly` | `disassemble_function` | Code disassembly by section |
| `file-info` | `get_file_info` | File metadata, hashes, timestamps |

This avoids recreating the temp project for each mode — each method call is a separate subprocess but the tradeoff is accepted because project creation is the bottleneck.

### Temp Project Directory Lifecycle

The backend creates a temp dir via `tempfile.mkdtemp(prefix="reai_ghidra_")` before each analysis call, then cleans up in a `finally` block:

```python
temp_dir = tempfile.mkdtemp(prefix="reai_ghidra_")
try:
    # ... subprocess.run(...) ...
    return data
finally:
    if temp_dir and os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir)
```

If the subprocess **crashes or times out**, the temp dir is still cleaned up. The output JSON path is also inside this temp dir, so a missing output file suggests the script never started or crashed before writing.

### 360-Second Timeout (Ghidra Slower Than IDA)

- `_GHIDRA_TIMEOUT = 360` seconds (6 minutes).
- Ghidra's auto-analysis is slower than IDA Pro's because it includes a full decompilation pass and more aggressive type propagation.
- The `-analysisTimeoutPerFile 360` flag mirrors the Python-side timeout.
- If exceeded, `AnalysisError` with "Ghidra timeout (360s) for mode <mode> on <path>".

### stdout vs stderr Gotcha

**Ghidra headless prints error information to stdout, unlike IDA Pro which uses stderr.** The backend's error handling accounts for this:

```python
stderr = (proc.stderr or b"").decode()
stdout = (proc.stdout or b"").decode()
combined = (stdout + "\n" + stderr).strip()[:2000]
```

When debugging Ghidra failures, check the stdout content — that's where Jython tracebacks and script errors appear.

### Jython 2.7 Constraints

`ghidra_analysis.py` runs inside Ghidra's Jython 2.7 interpreter. This imposes significant constraints on the script code:

| Constraint | Impact |
|-----------|--------|
| **No f-strings** | Use `%s` formatting or `.format()` — no `f"...{var}"` |
| **No `pathlib`** | Use `os.path.join()`, `os.path.exists()`, and string paths |
| **No type hints** | No function annotations, no `typing` module imports |
| **Old-style exception handling** | `except Exception, e:` (Python 2 syntax) — though the script uses `except Exception as exc:` which works in Jython 2.7 |
| **`java.io` for file I/O** | To read the binary path the script uses `java.io.File(path)` |
| **Long/integer division** | Python 2 semantics — `5 / 2 = 2` (integer division), use explicit float conversion |
| **No `subprocess`** | The script runs inside Ghidra and cannot spawn further processes |

The script guards against being imported outside Ghidra via a try/except block around `ghidra` module imports, exiting early with a clear message if the imports fail.

### `-readOnly` Flag

The `-readOnly` flag is **critical** — without it, Ghidra may modify the original binary during import (e.g. updating the checksum in the PE header). The backend always passes this flag. This means:

- The analysis script cannot modify the binary on disk.
- Analysis results are determined by Ghidra's in-memory representation of the imported file.

### Dual-Strategy String Extraction

The Ghidra string extraction (`_mode_strings`) uses a two-pass approach:

**Pass 1: Ghidra `StringSearch` API** (preferred, faster):

```python
from ghidra.app.util import StringSearch
found = StringSearch.findStrings(program, monitor, min_length, -1, True)
```

This uses Ghidra's internal string discovery, which understands alignment and common string patterns. It's faster and produces cleaner results — but in headless mode (`analyzeHeadless`), the `StringSearch` API may return incomplete results or none at all depending on whether auto-analysis completed certain indexing passes.

**Pass 2: Brute-force fallback** (always runs, ensures coverage):

Scans every byte in each initialized memory block:

1. **ASCII** scan: consecutive bytes in 0x20–0x7E range, minimum length from `GHIDRA_MIN_LENGTH` env var (default 5)
2. **UTF-16LE** scan: consecutive (printable ASCII + null byte) pairs, minimum character count from `GHIDRA_MIN_LENGTH`

Results from both passes are merged, deduplicated by address (preferring `StringSearch` values), capped at **200 displayed strings**, and sorted by length descending.

This dual-strategy approach ensures Ghidra headless string extraction is more reliable than IDA's single-pass brute force — though the total coverage difference is usually marginal for typical malware samples.

### Error Handling Modes

The `GhidraBackend._run_ghidra_script()` handles errors in the same categories as IDA Pro, plus one extra:

| Failure Mode | Error Type | Notes |
|-------------|-----------|-------|
| **Not configured** | `AnalysisError` | "Ghidra is not configured — set tool_configs.ghidra" |
| **Timeout** | `AnalysisError` | 360s timeout |
| **Binary not found** | `AnalysisError` | `FileNotFoundError` |
| **Script failure** | `AnalysisError` | Non-zero return code — includes both stdout and stderr (Ghidra uses stdout for errors) |
| **Missing output** | `AnalysisError` | Includes stdout+stderr excerpt to help diagnose why the script failed |
| **File/parse error** | `AnalysisError` | JSON decode failure or file read error |

All errors are logged at `logging.ERROR` with full traceback before re-raising.

### Architecture & Disassembly Notes

Ghidra's disassembly mode reads sections differently than IDA. If the requested section (via `GHIDRA_SECTION_NAME`) is not found, the script falls back to the **first initialized executable block** — which may not be `.text` for packed or unconventional binaries. The fallback behavior logs through Ghidra's internal mechanisms; check the returned `section_name` field to confirm which section was actually analysed.

The instruction limit is 500 (enforced server-side), matching the capstone backend. Ghidra does not return raw byte strings for instructions the same way capstone does — the `bytes` field is constructed by reading `program.getMemory().getBytes()` which may fail for uninitialized or page-gapped regions (returns empty string in that case).
