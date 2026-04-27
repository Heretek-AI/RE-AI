---
name: capstone
description: Disassembly via capstone — architecture mapping, mode selection, instruction format, truncation behavior
tool_id: disassemble_function
command_hint: disassemble_function path=file_path section_name=.text
---

## Capstone Disassembly Guide

The backend uses Capstone Engine for all disassembly operations. The `disassemble_function` tool delegates to the analysis backend which wraps capstone internally. This guide covers architecture mapping, mode selection, output interpretation, and common pitfalls.

### Architecture Mapping

The backend maps PE machine types to capstone architectures and modes automatically:

| Machine ID | Architecture | Capstone Arch | Capstone Mode |
|------------|-------------|---------------|---------------|
| `0x8664` (AMD64) | x86-64 | `CS_ARCH_X86` | `CS_MODE_64` |
| `0x14c` (I386) | x86-32 | `CS_ARCH_X86` | `CS_MODE_32` |
| `0x1c0` (ARM) | ARM v7 | `CS_ARCH_ARM` | `CS_MODE_ARM` |
| `0xaa64` (ARM64) | AArch64 | `CS_ARCH_AARCH64` | `CS_MODE_LITTLE_ENDIAN` |
| `0x1c4` (ARM Thumb) | ARM Thumb | `CS_ARCH_ARM` | `CS_MODE_THUMB` |
| `0x5032` (IA64) | Itanium | `CS_ARCH_IA64` | `CS_MODE_BIG_ENDIAN` |

If the machine type is unknown or unsupported, the backend raises `AnalysisError` with a message like "Unsupported architecture: 0x<hex>".

### Instruction Format

Each disassembled instruction is returned with these fields:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `address` | int | Virtual address of the instruction | `0x140001000` |
| `bytes` | str | Raw bytes as hex string | `488b05c3` |
| `mnemonic` | str | Instruction mnemonic | `mov` |
| `operands` | str | Operand text | `rax, qword ptr [rip+0x1a2c]` |

The backend renders these as a markdown table in the output:

```
| Address | Bytes | Instruction |
|---------|-------|-------------|
| 0x140001000 | `488b05c3` | mov rax, qword ptr [rip+0x1a2c] |
```

### Detail Mode Limitation

- The backend uses **detail mode disabled** (`detail=False`) by default.
- This means capstone returns only **mnemonic and operand strings** — not structured operand types (registers, immediates, memory operands).
- You **cannot** programmatically distinguish `mov eax, 1` from `mov eax, ebx` at the operand level — both are just strings.
- For most analysis needs (reading disassembly output), this is sufficient. If precise operand type analysis is required, note this as a future enhancement.

### No Decompilation

- Capstone is a **disassembler only** — it does not produce C-like pseudocode.
- The backend does **not** bundle a decompiler (no IDA Hex-Rays, no Ghidra decompiler via headless).
- Decompilation is available only when using IDA Pro or Ghidra backends (see `skills/ida_pro.md` and `skills/ghidra.md`).

### 500-Instruction Truncation

- The backend caps disassembly at **500 instructions** per call (`max_results=500`).
- If the requested range produces more than 500 instructions, the output includes a truncation note: `*Disassembly truncated (more than 500 instructions).*`
- To analyze beyond the truncation boundary, make multiple calls with different `offset` and `size` parameters.
- Each call analyzes `size` bytes (default: 256). 500 instructions typically consume 1-4KB of bytes depending on instruction length.

### Bad Instructions from Non-Code Sections

- Disassembling data sections (`.rdata`, `.data`, `.pdata`) produces **junk/bad instructions** — capstone will happily disassemble any bytes as code.
- These appear as valid instructions with nonsensical mnemonics and operands.
- Always disassemble `.text` (or other executable sections) unless you specifically intend to explore data as code (e.g., checking for embedded shellcode).

### Section Alignment Padding

- PE sections are padded to file alignment boundaries (typically 512 bytes).
- The padding bytes (usually zeros or `0xCC` INT3) at the end of `.text` will produce invalid or nonsensical instructions.
- The backend sets `offset=0` by default, starting at the beginning of the section. To skip padding, use a specific offset from a previous analysis.
- Entry point analysis: pass `offset=<entry_point_rva>` to start disassembly at the program's entry point rather than the section start.

### x86/x64 Instruction Length

- x86/x64 instructions are **variable length** (1-15 bytes).
- Capstone handles this correctly — it does not assume fixed-length instructions.
- The `bytes` field shows the actual raw bytes consumed by each decoded instruction.
- Common instruction lengths: `ret` (1 byte), `mov` (2-7 bytes), `call` (5 bytes near, 6 bytes far), `jmp` (2-5 bytes).
