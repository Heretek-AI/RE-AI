"""Abstract base class for PE/DLL analysis backends.

Defines the common interface that all analysis backends (native,
IDA Pro, Ghidra, etc.) must implement, along with shared result
type models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class AnalysisError(Exception):
    """Raised when a backend operation fails (PE parse error, I/O, etc.)."""


# ---------------------------------------------------------------------------
# Result type models  (all total=False for forward-compatibility)
# ---------------------------------------------------------------------------


class PeStructureResult(TypedDict, total=False):
    """Result of ``analyze_pe_structure``."""

    machine_type: str
    characteristics: str
    is_dll: bool
    is_exe: bool
    subsystems: list[str]
    sections: list[dict[str, Any]]
    entry_point: int
    image_base: int
    size_of_image: int
    imphash: str | None


class ImportsExportsResult(TypedDict, total=False):
    """Result of ``get_imports_exports``."""

    imports: list[dict[str, Any]]
    exports: list[dict[str, Any]]
    has_exceptions: bool


class StringsResult(TypedDict, total=False):
    """Result of ``extract_strings``."""

    strings: list[dict[str, Any]]
    total_count: int
    displayed_count: int


class DisassemblyResult(TypedDict, total=False):
    """Result of ``disassemble_function``."""

    architecture: str
    mode: str
    section_name: str
    offset: int
    bytes_count: int
    instructions: list[dict[str, Any]]
    truncated: bool


class FileInfoResult(TypedDict, total=False):
    """Result of ``get_file_info``."""

    path: str
    size_bytes: int
    md5: str
    sha256: str
    is_pe: bool
    subsystem: str | None
    architecture: str | None
    is_dll: bool | None
    is_exe: bool | None
    entry_point: int | None
    timestamp: str


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class AbstractAnalysisBackend(ABC):
    """Abstract base class for PE/DLL analysis backends.

    Each backend implements the same five methods below, so the agent
    can switch between native Python, IDA Pro, or Ghidra without
    changing its calling code.
    """

    @abstractmethod
    async def analyze_pe_structure(self, path: str) -> dict[str, Any]:
        """Analyse the PE header structure of a portable executable.

        Returns a dict matching :class:`PeStructureResult`.
        """

    @abstractmethod
    async def get_imports_exports(self, path: str) -> dict[str, Any]:
        """Extract import and export tables from a PE file.

        Returns a dict matching :class:`ImportsExportsResult`.
        """

    @abstractmethod
    async def extract_strings(
        self, path: str, min_length: int = 5
    ) -> dict[str, Any]:
        """Extract printable ASCII / Unicode strings from a PE file.

        Parameters
        ----------
        path:
            Path to the PE file.
        min_length:
            Minimum string length (default 5).  Strings shorter than
            this are filtered out.

        Returns a dict matching :class:`StringsResult`.
        """

    @abstractmethod
    async def disassemble_function(
        self,
        path: str,
        section_name: str,
        offset: int,
        size: int = 256,
    ) -> dict[str, Any]:
        """Disassemble a region of code from a section.

        Parameters
        ----------
        path:
            Path to the PE file.
        section_name:
            Name of the section containing the code (e.g. ``.text``).
        offset:
            Byte offset within the section to start disassembly.
        size:
            Number of bytes to disassemble (default 256).

        Returns a dict matching :class:`DisassemblyResult`.
        """

    @abstractmethod
    async def get_file_info(self, path: str) -> dict[str, Any]:
        """Return high-level file metadata (size, hashes, PE flag, …).

        Returns a dict matching :class:`FileInfoResult`.
        """
