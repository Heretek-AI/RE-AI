"""Analysis backend package.

Provides the abstract interface (``AbstractAnalysisBackend``) and shared
result type models used by all analysis backends.
"""

from backend.analysis.base import (
    AbstractAnalysisBackend,
    AnalysisError,
    DisassemblyResult,
    FileInfoResult,
    ImportsExportsResult,
    PeStructureResult,
    StringsResult,
)

__all__: list[str] = [
    "AbstractAnalysisBackend",
    "AnalysisError",
    "DisassemblyResult",
    "FileInfoResult",
    "ImportsExportsResult",
    "PeStructureResult",
    "StringsResult",
]
