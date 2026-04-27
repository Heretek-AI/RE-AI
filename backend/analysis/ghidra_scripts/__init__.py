"""Ghidra Python analysis scripts for the Ghidra backend.

Each mode is dispatched from a single comprehensive script
(``ghidra_analysis.py``) via the ``GHIDRA_MODE`` environment
variable, avoiding per-mode Ghidra project creation overhead.

Mode dispatch:
    GHIDRA_MODE=structure        — PE header structure analysis
    GHIDRA_MODE=imports-exports  — Import / export table extraction
    GHIDRA_MODE=strings          — String extraction (ASCII + UTF-16LE)
    GHIDRA_MODE=disassembly      — Code disassembly
    GHIDRA_MODE=file-info        — File-level metadata extraction

Result files are written to the path specified by ``GHIDRA_OUTPUT``.
"""
