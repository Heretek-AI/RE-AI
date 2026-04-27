---
name: static_analysis_workflow
description: Structured PE analysis workflow — file info → PE structure → imports/exports → strings → disassembly, with indicator triage and batch strategy
tool_id: analyze_directory
command_hint: analyze_directory directory=target_dir (kicks off multi-step workflow)
---

## Static Analysis Workflow

This skill defines a structured 5-step workflow for analysing PE files. When you run `analyze_directory` to scan a batch of files, it returns basic info (size, architecture, type, entry point, imphash) – use that to identify interesting targets, then drill into each with the granular tools for deep analysis.

### Step 1: File Info

For each PE, check these fields from `extract_pe_info`:

- **Architecture**: x86 (I386) vs AMD64 (x86-64) vs ARM vs ARM64 vs IA64. Modern Windows malware is predominantly AMD64. ARM/ARM64 appears in IoT and Windows-on-ARM samples.
- **File type**: EXE vs DLL vs SYS (driver). SYS files use `IMAGE_FILE_EXECUTABLE_IMAGE` without DLL or GUI subsystem flags — they are not detected by `is_dll()` or `is_exe()`.
- **Size**: Very large files (>100MB) may have appended data or heavy packing. Very small files (<2KB) are likely stubs or decoy executables with the real payload elsewhere.
- **Entry point**: Note the section the entry point falls in. An entry point in `.rdata`, `.data`, or `.rsrc` instead of `.text` is highly suspicious — it suggests the real code is in a non-standard section.
- **Imphash**: Cross-reference with known imphash databases (e.g. VirusTotal). Same imphash across files suggests the same toolchain or family variant.

**Suspicious indicators**:

| Signal | What to check |
|--------|--------------|
| Relocs stripped | `IMAGE_FILE_RELOCS_STRIPPED` (0x0001) — prevents ASLR, common in old malware but also in VC6-built EXEs |
| Huge file, tiny .text | Packed — code and data expand at runtime |
| SizeOfCode > file size | Arithmetic truncation? Possibly crafted header |
| DLL with entry point in .text | Legitimate — DLLs export their entry point from `.text` |
| SYS with no entry point | Normal — drivers use DriverEntry which Ghidra/IDA can resolve |

### Step 2: PE Structure

After gathering file info, examine the PE section layout via `extract_pe_info`. Key things to look for:

- **Executable sections** (`.text`, `.textbss`, .code sections): Should contain compiled code. Multiple executable sections are unusual but not necessarily malicious — some compilers split code regions.
- **Unusual section names**: Names that don't match standard conventions (`.text`, `.rdata`, `.data`, `.rsrc`, `.reloc`, `.pdata`, `.tls`, `.bss`, `.edata`, `.idata`). Packed binaries often use random-looking section names like `.UPX0`, `.UPX1`, `.mpress1`, `.adata`, or single-letter names.
- **Large sections with mismatched raw/virtual sizes**: A section with `virtual_size >> raw_size` means it expands in memory. This is typical of packed binaries — the unpacker writes decompressed code into the virtual space.
- **W^X violations**: Sections with both EXECUTE and WRITE permissions set. `IMAGE_SCN_MEM_EXECUTE` (0x20000000) + `IMAGE_SCN_MEM_WRITE` (0x80000000) = self-modifying code or packer stub. Most legitimate PE files never have W^X sections.
- **Sections in unusual order**: Standard order is `.text`, `.rdata`, `.data`, `.rsrc`, `.reloc`. Deviations are worth noting.
- **Resource section size**: A very large `.rsrc` section relative to file size can indicate resource-only DLLs (legitimate) or embedded payloads hidden in resources (suspicious).

**Suspicious indicators**:

| Signal | What it suggests |
|--------|-----------------|
| Non-standard section name | Packer (UPX, MPRESS, ASPack) or custom obfuscation |
| W^X section | Self-modifying code, packer unpack stub |
| Virtual size >> raw size | Packed — runtime expansion in memory |
| `.text` with WRITE permission | Patching self or anti-debug checks |
| Empty `.text` (zero bytes) | All code is in other sections or generated at runtime |
| Many small sections | Manual packing or custom section layout |

### Step 3: Imports / Exports

Use `list_imports_exports` to examine what APIs the PE calls. This step reveals the file's capabilities and can identify its behaviour category (loader, injector, keylogger, dropper, etc.).

**Import analysis strategy**:

1. **List all DLLs** — each DLL import adds capabilities. Common Windows DLLs and what they provide:
   - `kernel32.dll` / `ntdll.dll` — Core OS operations (process, memory, file I/O). Every PE imports these.
   - `advapi32.dll` — Registry, services, security (suspicious if you don't expect registry modification)
   - `wininet.dll` / `urlmon.dll` — HTTP/HTTPS network operations (downloader, C2 beacon)
   - `ws2_32.dll` — Winsock sockets (raw network communication, packet crafting)
   - `crypt32.dll`, `bcrypt.dll` — Cryptography (legitimate for HTTPS, suspicious in a process injection tool)
   - `user32.dll`, `gdi32.dll` — GUI operations (normal for applications, suspicious for hidden services)
   - `ntdll.dll` (native API) — Direct syscall imports suggest API hook evasion

2. **Check for suspicious API patterns**:

| Category | Suspicious APIs | What they enable |
|----------|----------------|------------------|
| Process manipulation | `OpenProcess`, `CreateRemoteThread`, `WriteProcessMemory`, `VirtualAllocEx`, `NtCreateThreadEx` | Process injection, code injection |
| Memory manipulation | `VirtualAlloc`, `VirtualProtect`, `HeapCreate`, `NtAllocateVirtualMemory` | Memory allocation for shellcode or unpacked payload |
| Code execution | `WinExec`, `ShellExecute`, `CreateProcess`, `NtCreateProcess` | Executing payloads, spawning new processes |
| Network | `WSAStartup`, `connect`, `send`, `recv`, `InternetOpen`, `HttpOpenRequest` | Network communication, C2 |
| Persistence | `RegSetValueEx`, `CreateService`, `ChangeServiceConfig` | Registry or service persistence |
| Anti-analysis | `IsDebuggerPresent`, `CheckRemoteDebuggerPresent`, `NtQueryInformationProcess`, `OutputDebugString` | Anti-debugging, environment detection |

3. **Exports** — for DLLs, check exports for suspicious function names. Legitimate DLLs have descriptive names. Hidden functionality may use:
   - Ordinal-only exports (no name) — common in malware DLLs
   - Nondescriptive names (`a1`, `function_1`, `start`) — potential hidden entry points
   - Exports that don't match the DLL name's apparent purpose

**Suspicious indicators**:

| Pattern | Severity | What it means |
|---------|----------|--------------|
| `kernel32 + ws2_32 + wininet` only | High | Downloader or C2 beacon — minimal imports, network-focused |
| Process injection API set | Critical | `OpenProcess + VirtualAllocEx + WriteProcessMemory + CreateRemoteThread` = classic process injection |
| No imports at all | Critical | Packed, or statically linked — must disassemble to understand |
| `ntdll` with no `kernel32` | High | Direct syscall user — bypassing user-mode API hooks |
| Registry APIs in a command-line tool | Medium | Persistence or configuration writing |
| Ordinal-only exports | High | Deliberately hiding function names |

### Step 4: Strings

Use `extract_strings` to find embedded text in the binary. Strings provide the most analyst-facing insight into what the binary does — they often reveal URLs, IPs, file paths, registry keys, embedded configuration, error messages, and command-and-control (C2) protocols.

**Scanning strategy**:

1. **Minimum length**: Start with the default (5 characters). Lowering to 4 catches more but increases noise. Increase to 10+ if you need to filter common noise.
2. **ASCII vs UTF-16LE**: Modern Windows malware uses UTF-16LE for API-related strings. Always check both.
3. **Focus areas**:
   - URLs and IPs (e.g. `https://`, `http://`, `1.2.3.4:8080`)
   - File paths (e.g. `C:\Windows\`, `%TEMP%`, `\\.\\pipe\\`)
   - Registry keys (e.g. `HKEY_LOCAL_MACHINE`, `SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run`)
   - Suspicious keywords: `encrypt`, `decode`, `inject`, `shellcode`, `payload`, `beacon`, `persist`, `dump`, `keylog`, `password`, `config`, `mutex`, `sandbox`, `bypass`
   - Function/variable names in embedded debug strings
   - Command-line argument patterns (e.g. `-h`, `--url`, `--key`)
   - Mutex names (unique to malware families — `Global\\MutexName`)

**Suspicious indicators**:

| Finding | Severity | Notes |
|---------|----------|-------|
| Hardcoded IP:port pair | High | Potential C2 server — verify with threat intelligence |
| `\\\\.\\pipe\\` strings | High | Named pipe — used for inter-process communication in injection |
| `%TEMP%` + `.exe` in same file | High | Drops executable to temp directory |
| Registry `Run` key paths | High | Persistence via startup |
| `Sandboxie`, `wireshark`, `procmon` | Medium | Anti-analysis — checking for analysis tools |
| Mutex name `Global\\` | Medium | Singleton enforcement — common in malware |
| Embedded config JSON/XML | High | Configuration block — may contain C2 addresses, encryption keys |
| Long base64-like strings | Medium | Could be encoded payload, config, or key material |

**False positive guide**:

- Many strings are compiler-inserted debug information (e.g. file paths to `.c` source files, compiler version strings). These are normal.
- OpenSSL libraries embed many readable strings — `OpenSSL` in strings often means TLS is used, not necessarily malicious.
- Standard API error messages (`The parameter is incorrect`) are benign and pervasive.
- MSVCRT/Universal CRT strings are compiler-inserted — ignore `__stdio_common_vfprintf` etc.

### Step 5: Disassembly

Use `disassemble_function` to examine code. This is the most time-intensive step — reserve it for files that have suspicious indicators from steps 1–4.

**Disassembly strategy**:

1. **Start at the entry point**: Pass `offset=<entry_point_rva>` to disassemble from the file's entry point. This shows the first code that executes. It's often a short stub that jumps to the real code — especially in packed files.
2. **Disassemble `.text` from offset 0**: Get the full `.text` section disassembly. Look for:
   - **Interesting functions**: Calls to known Windows APIs, loops, string references.
   - **Entry point analysis**: Check if the entry stub decrypts or decompresses additional code.
   - **Suspicious patterns**: 
     - `pushad; call; popad` — typical of packed unpack stubs.
     - `call $+5` / `call next; pop reg` — position-independent code (common in shellcode and unpackers).
     - Opaque predicates — comparison with always-true/false results (anti-analysis).
3. **Anti-analysis pattern detection**:
   - `call IsDebuggerPresent; test al, al; jne <anti-debug>` — debugger check.
   - XOR operations on registers immediately before a function call — likely decryption of API name strings.
   - Self-modifying code pattern: `VirtualProtect` followed by writes to the executable section.
4. **Epilogue patterns**:
   - Standard function epilogue: `add rsp, X; ret` or `leave; ret`.
   - Suspicious epilogue: `retn` with non-zero stack adjustment or tail calls via `jmp` instead of `call`.
5. **Import table resolution**: Look for `GetProcAddress` + `LoadLibrary` calls — the code is dynamically resolving imports, bypassing the static import table. This is a hallmark of packed or obfuscated code.

**Suspicious indicators**:

| Pattern | What it means |
|---------|--------------|
| `call` to `push; ret` sequence | Obfuscated control flow |
| Heavy XOR operations on data | Decryption/encoding loop |
| `call $+5` patterns | Position-independent code (shellcode) |
| `VirtualProtect` + write to `.text` | Self-modifying code |
| `GetProcAddress` loop | Dynamic API resolution — bypassing imports |
| Jump table via indirect `jmp [reg*8+table]` | Switch statement — legitimate, but check what it dispatches |
| Long NOP sled before shellcode | Standard shellcode padding |
| `push <exception_handler>; push dword fs:[0]` | SEH-based anti-debug (structured exception handling) |

### Batch Analysis Strategy

When you encounter a directory of PE files, use this strategy:

1. **Scan with `analyze_directory`** to get a quick overview — architecture, type, size, entry point, imphash for every file.
2. **Prioritize by suspiciousness**: Files with packed indicators (huge virtual vs raw size, W^X sections, non-standard section names, suspicious imphash) go first.
3. **Run `extract_pe_info`** on the most suspicious files for full PE header analysis (section permissions, characteristics flags).
4. **Run `list_imports_exports`** on files with suspicious structures — check for injection API sets, network libraries.
5. **Run `extract_strings`** on files flagged by imports or structure — look for embedded URLs, config, pipe names.
6. **Run `disassemble_function`** on the most critical files (confirmed suspicious after steps 3–5).

**Workflow decision tree**:

```
analyze_directory (all files)
  │
  ├── Normal PE → low priority, move on
  │
  └── Suspicious flags (packed, W^X, odd section names, DLL+injection APIs)
       │
       ├── extract_pe_info → reconfirm structure suspicion
       │    │
       │    └── Suspicious confirmed?
       │         │
       │         ├── Yes → list_imports_exports → ID capabilities
       │         │         │
       │         │         └── extract_strings → find URLs, config, C2
       │         │              │
       │         │              └── disassemble_function → deep code analysis
       │         │
       │         └── No → likely false positive, note and move on
       │
       └── Batch note: don't drill into every file — pick the top 1-3
           interesting targets per batch to stay efficient
```

### Indicator Triage

Not every suspicious finding is malicious. Use this triage framework:

| Severity | Criteria | Action |
|----------|----------|--------|
| **Benign** | Compiler-inserted strings, standard section layout, expected imports for file type, normal PE characteristics | Skip; note as "clean baseline" |
| **Informational** | Odd section name but no W^X, imphash matches known packers, large .rsrc but readable content | Note in findings; may be legitimate packer (UPX, MPRESS) |
| **Medium** | W^X section, network imports in utility tool, registry persistence calls, single-section PE with no imports | Flag for deeper analysis (strings + disassembly) |
| **High** | Process injection API set + network imports, encrypted strings, dynamic API resolution, embedded IPs/URLs, ordinal-only DLL exports | Full deep analysis required |
| **Critical** | Confirmed C2 URL with hardcoded IP, embedded config with encryption keys, shellcode detected in disassembly, process hollowing detection | Escalate; full report required |

**Benign false positive sources**:
- **Delphi / Borland** binaries: Non-standard section names, different import patterns. Check for `Borland` or `Delphi` debug strings.
- **.NET binaries**: PE header has a specific CLI header stub. Section names may include `.text`, `.rsrc` plus `.reloc`. Use `list_imports_exports` — if `mscoree.dll` is imported, it's .NET and needs different analysis.
- **NSIS / InnoSetup installers**: Packed with their own formats — the PE section structure is atypical. Use file info to detect the installer signature.
- **AutoIT / AHK compiled scripts**: The PE is a stub with embedded script data. Strings will show AutoIT library references. Requires AutoIT decompilation for full analysis.
- **Go binaries**: Large file size, no standard import table, statically linked, many runtime strings. Check `go` or `golang` references in strings.
- **Rust binaries**: Similar to Go — statically linked with distinct runtime strings.
