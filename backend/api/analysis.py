"""Analysis REST API endpoints — wrap the analysis backends as POST JSON endpoints.

Each endpoint accepts a file path (and optional parameters), calls the backend
method, and returns the raw result dict as JSON.

Error handling
--------------
- ``AnalysisError`` (from the backend layer) → HTTP 400 with ``{"detail": str}``
- ``FileNotFoundError`` → HTTP 400 with ``{"detail": str}``
- Unexpected ``Exception`` → HTTP 500 with ``{"detail": str}``
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.analysis import AnalysisError, get_analysis_backend

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class PathRequest(BaseModel):
    path: str = Field(..., description="Absolute path to the PE/DLL file on disk.")


class ExtractStringsRequest(PathRequest):
    min_length: int = Field(5, description="Minimum string length (default: 5).")
    max_results: int = Field(200, description="Maximum number of strings to return (default: 200).")


class DisassembleRequest(PathRequest):
    section_name: str = Field(..., description="Name of the section (e.g. `.text`).")
    offset: int = Field(0, description="Byte offset within the section to start.")
    size: int = Field(256, description="Number of bytes to disassemble (default: 256).")


class BatchRequest(BaseModel):
    directory: str = Field(..., description="Absolute path to a directory to scan for PE/DLL files.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ANALYSIS_BACKEND_CACHE: dict[str, Any] = {}  # noqa: RUF012


def _get_backend():
    """Lazy-factory returning an analysis backend instance."""
    return get_analysis_backend({})


async def _run_analysis(call: str, **kwargs: Any) -> dict[str, Any]:
    """Execute an analysis backend method with standard error wrapping.

    Parameters
    ----------
    call:
        Name of the backend method to call (e.g. ``"analyze_pe_structure"``).
    **kwargs:
        Arguments forwarded to the method.

    Returns
    -------
    dict[str, Any]
        The raw result dict from the backend.

    Raises
    ------
    HTTPException
        With status 400 for ``AnalysisError`` / ``FileNotFoundError``,
        or 500 for unexpected errors.
    """
    backend = _get_backend()
    method = getattr(backend, call, None)
    if method is None:
        raise HTTPException(status_code=500, detail=f"Backend method {call!r} not found.")

    try:
        return await method(**kwargs)
    except AnalysisError as exc:
        logger.warning("Analysis error in %s: %s", call, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        logger.warning("File not found in %s: %s", call, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error in analysis/%s", call)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/extract-pe-info")
async def extract_pe_info(body: PathRequest) -> dict[str, Any]:
    """Extract PE header structure information from a PE/DLL file.

    Returns machine type, characteristics, sections, entry point, image
    base, image size, and imphash.
    """
    logger.debug("POST /api/analysis/extract-pe-info: %s", body.path)
    return await _run_analysis("analyze_pe_structure", path=body.path)


@router.post("/list-imports-exports")
async def list_imports_exports(body: PathRequest) -> dict[str, Any]:
    """List import and export tables of a PE/DLL file.

    Returns imports grouped by DLL and export symbols with ordinals and
    addresses.
    """
    logger.debug("POST /api/analysis/list-imports-exports: %s", body.path)
    return await _run_analysis("get_imports_exports", path=body.path)


@router.post("/extract-strings")
async def extract_strings(body: ExtractStringsRequest) -> dict[str, Any]:
    """Extract printable ASCII/Unicode strings from a PE/DLL file.

    Accepts optional ``min_length`` and ``max_results`` parameters.
    Returns strings with offsets, the total count, and a truncated flag.
    """
    logger.debug(
        "POST /api/analysis/extract-strings: %s (min_length=%d, max_results=%d)",
        body.path,
        body.min_length,
        body.max_results,
    )
    result = await _run_analysis("extract_strings", path=body.path, min_length=body.min_length)

    # Apply client-side max_results cap (backend caps at 200 already)
    strings_list = result.get("strings", [])
    total_count = result.get("total_count", 0)
    capped = strings_list[: body.max_results]
    result["strings"] = capped
    result["displayed_count"] = len(capped)
    result["truncated"] = total_count > body.max_results or result.get("truncated", False)

    return result


@router.post("/disassemble")
async def disassemble(body: DisassembleRequest) -> dict[str, Any]:
    """Disassemble a code region from a PE/DLL file section.

    Accepts ``section_name``, ``offset``, and ``size`` parameters.
    Returns an instruction listing with addresses, mnemonics, operands,
    and raw bytes.
    """
    logger.debug(
        "POST /api/analysis/disassemble: %s section=%s offset=%d size=%d",
        body.path,
        body.section_name,
        body.offset,
        body.size,
    )
    return await _run_analysis(
        "disassemble_function",
        path=body.path,
        section_name=body.section_name,
        offset=body.offset,
        size=body.size,
    )


@router.post("/analyze-batch")
async def analyze_batch(body: BatchRequest) -> dict[str, Any]:
    """Analyze all PE/DLL files in a directory.

    Scans for ``*.exe`` and ``*.dll`` files and returns basic info
    (size, architecture, type, entry point, imphash) for each one.
    Non-PE files and parse errors are recorded with a note rather
    than failing the whole batch.
    """
    import os

    directory: str = body.directory
    logger.debug("POST /api/analysis/analyze-batch: %s", directory)

    if not os.path.isdir(directory):
        raise HTTPException(status_code=400, detail=f"Directory not found: {directory}")

    backend = _get_backend()

    # Collect PE files
    pe_files: list[str] = []
    non_pe_count = 0
    try:
        for entry in os.listdir(directory):
            full = os.path.join(directory, entry)
            if not os.path.isfile(full):
                continue
            if entry.lower().endswith((".exe", ".dll")):
                pe_files.append(full)
            else:
                non_pe_count += 1
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=f"Permission denied: {exc}") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not pe_files:
        detail = f"No PE files found in {directory}"
        if non_pe_count:
            detail += f" ({non_pe_count} non-PE files skipped)"
        raise HTTPException(status_code=400, detail=detail)

    files_info: list[dict[str, Any]] = []
    for file_path in pe_files:
        try:
            info = await backend.get_file_info(file_path)
            structure = await backend.analyze_pe_structure(file_path)
            files_info.append({
                "path": file_path,
                "filename": os.path.basename(file_path),
                "size_bytes": info.get("size_bytes", 0),
                "architecture": info.get("architecture", "?"),
                "is_dll": info.get("is_dll", False),
                "is_exe": info.get("is_exe", False),
                "entry_point": structure.get("entry_point", 0),
                "entry_point_hex": f"0x{structure.get('entry_point', 0):x}",
                "imphash": structure.get("imphash", "N/A"),
                "sections_count": len(structure.get("sections", [])),
            })
        except AnalysisError:
            files_info.append({
                "path": file_path,
                "filename": os.path.basename(file_path),
                "error": "PE parse error",
            })
        except Exception as exc:
            logger.exception("analyze-batch error for %s", file_path)
            files_info.append({
                "path": file_path,
                "filename": os.path.basename(file_path),
                "error": str(exc),
            })

    summary = (
        f"Analyzed {len(pe_files)} PE file(s) in {directory}"
        f" ({len([f for f in files_info if 'error' not in f])} succeeded,"
        f" {len([f for f in files_info if 'error' in f])} failed)"
    )
    if non_pe_count:
        summary += f", {non_pe_count} non-PE file(s) skipped"

    return {
        "files": files_info,
        "summary": summary,
        "total_found": len(pe_files),
        "non_pe_skipped": non_pe_count,
    }
