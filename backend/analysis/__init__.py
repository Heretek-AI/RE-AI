"""Analysis backend package.

Provides the abstract interface (``AbstractAnalysisBackend``), the native
Python implementation (``NativePythonBackend``), a registry of available
backends, and a factory function for selecting one at runtime.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from backend.analysis.base import (
    AbstractAnalysisBackend,
    AnalysisError,
    DisassemblyResult,
    FileInfoResult,
    ImportsExportsResult,
    PeStructureResult,
    StringsResult,
)
from backend.analysis.native import NativePythonBackend

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backend registry — mirrors the _PROVIDER_REGISTRY pattern from provider.py
# ---------------------------------------------------------------------------

_ANALYSIS_BACKENDS: dict[str, type[AbstractAnalysisBackend]] = {
    "native": NativePythonBackend,
}


def get_analysis_backend(config: dict[str, Any]) -> AbstractAnalysisBackend:
    """Factory: instantiate an analysis backend from a config dict.

    Reads ``config.get("analysis_backend", "native")`` to select the
    backend.  Unknown backend names fall back to ``NativePythonBackend``
    with a warning logged.

    Parameters
    ----------
    config:
        Configuration dict with an optional ``"analysis_backend"`` key.

    Returns
    -------
    AbstractAnalysisBackend
        An instance of the requested (or fallback) backend.
    """
    name = (config.get("analysis_backend") or "native").lower().strip()
    cls = _ANALYSIS_BACKENDS.get(name)
    if cls is None:
        logger.warning("Unknown analysis backend %r, falling back to native", name)
        cls = NativePythonBackend
    return cls()


def list_available_backends() -> list[dict[str, str]]:
    """Return metadata about every registered analysis backend.

    Returns
    -------
    list[dict[str, str]]
        Each entry has ``"name"`` and ``"description"`` keys.
    """
    descriptions: dict[str, str] = {
        "native": "Built-in Python analysis using pefile + capstone",
    }
    result: list[dict[str, str]] = []
    for name in _ANALYSIS_BACKENDS:
        result.append({
            "name": name,
            "description": descriptions.get(name, ""),
        })
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: list[str] = [
    "AbstractAnalysisBackend",
    "AnalysisError",
    "DisassemblyResult",
    "FileInfoResult",
    "ImportsExportsResult",
    "PeStructureResult",
    "StringsResult",
    "NativePythonBackend",
    "get_analysis_backend",
    "list_available_backends",
]
