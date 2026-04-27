"""Integration tests for analysis REST API endpoints.

Tests use httpx.AsyncClient with ASGITransport to verify JSON schemas,
real PE analysis against fixture DLLs, and error handling.

Test structure:
- Mock-backend tests verify JSON shapes without PE file dependencies
- Real-backend tests exercise actual PE analysis on fixture files
- Error handling tests: missing fields → 422, missing files → 400, etc.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI

from backend.analysis import AnalysisError
from backend.api.analysis import router

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
TEST_DLL = str(FIXTURE_DIR / "minimal_test.dll")
TEST_ARM = str(FIXTURE_DIR / "test_arm.dll")


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _make_app() -> FastAPI:
    """Create a minimal FastAPI app with just the analysis router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
async def client():
    """Provide an httpx AsyncClient hitting the analysis router via ASGI."""
    app = _make_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ═══════════════════════════════════════════════════════════════════════
# Mock-backend tests  (schema validation without PE file dependencies)
# ═══════════════════════════════════════════════════════════════════════


class TestMockBackend:
    """Verify JSON response shapes with a mocked analysis backend."""

    @pytest.fixture()
    def mock_backend(self):
        """Build a mock with canned responses for all backend methods."""
        backend = AsyncMock(spec=[])
        backend.analyze_pe_structure = AsyncMock(
            return_value={
                "machine_type": "AMD64",
                "characteristics": "EXECUTABLE_IMAGE, LARGE_ADDRESS_AWARE",
                "is_dll": True,
                "is_exe": False,
                "subsystems": ["WINDOWS_GUI"],
                "sections": [
                    {
                        "name": ".text",
                        "virtual_address": 4096,
                        "virtual_size": 512,
                        "size_of_raw_data": 1024,
                        "characteristics": "CODE, EXECUTE",
                    },
                ],
                "entry_point": 16384,
                "image_base": 0x180000000,
                "size_of_image": 65536,
                "imphash": "a" * 32,
            }
        )
        backend.get_imports_exports = AsyncMock(
            return_value={
                "imports": [
                    {
                        "dll": "KERNEL32.DLL",
                        "imports": [
                            {"name": "GetProcAddress", "ordinal": 0, "import_by_ordinal": False},
                            {"name": "LoadLibraryA", "ordinal": 1, "import_by_ordinal": False},
                        ],
                    },
                ],
                "exports": [
                    {"name": "DllMain", "ordinal": 1, "address": 16384},
                ],
                "has_exceptions": False,
            }
        )
        backend.extract_strings = AsyncMock(
            return_value={
                "strings": [
                    {"offset": 100, "string": "HelloFromREAI"},
                    {"offset": 200, "string": "REAI_ANALYSIS"},
                ],
                "total_count": 2,
                "displayed_count": 2,
            }
        )
        backend.disassemble_function = AsyncMock(
            return_value={
                "architecture": "AMD64",
                "mode": "64-bit",
                "section_name": ".text",
                "offset": 0,
                "bytes_count": 4,
                "instructions": [
                    {
                        "address": 4096,
                        "bytes": "c3",
                        "mnemonic": "ret",
                        "operands": "",
                    },
                ],
                "truncated": False,
            }
        )
        backend.get_file_info = AsyncMock(
            return_value={
                "path": "/mock/file.dll",
                "size_bytes": 10240,
                "md5": "aaaaa",
                "sha256": "bbbbbbb",
                "is_pe": True,
                "subsystem": "WINDOWS_GUI",
                "architecture": "AMD64",
                "is_dll": True,
                "is_exe": False,
                "entry_point": 16384,
                "timestamp": "2026-01-01T00:00:00",
            }
        )
        return backend

    # ── extract-pe-info ───────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_extract_pe_info_shape(self, client, mock_backend) -> None:
        """POST /api/analysis/extract-pe-info returns JSON with expected keys."""
        with patch("backend.api.analysis.get_analysis_backend", return_value=mock_backend):
            resp = await client.post(
                "/api/analysis/extract-pe-info",
                json={"path": "/mock/file.dll"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["machine_type"] == "AMD64"
        assert len(data["sections"]) == 1
        assert data["sections"][0]["name"] == ".text"
        assert data["entry_point"] == 16384
        assert data["imphash"] == "a" * 32

    # ── list-imports-exports ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_list_imports_exports_shape(self, client, mock_backend) -> None:
        """POST /api/analysis/list-imports-exports returns imports/exports arrays."""
        with patch("backend.api.analysis.get_analysis_backend", return_value=mock_backend):
            resp = await client.post(
                "/api/analysis/list-imports-exports",
                json={"path": "/mock/file.dll"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["imports"], list)
        assert isinstance(data["exports"], list)
        assert len(data["imports"]) == 1
        assert data["imports"][0]["dll"] == "KERNEL32.DLL"

    # ── extract-strings ───────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_extract_strings_shape(self, client, mock_backend) -> None:
        """POST /api/analysis/extract-strings returns strings array and total_count."""
        with patch("backend.api.analysis.get_analysis_backend", return_value=mock_backend):
            resp = await client.post(
                "/api/analysis/extract-strings",
                json={"path": "/mock/file.dll"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["strings"], list)
        assert data["total_count"] == 2
        assert data["displayed_count"] == 2
        assert data["strings"][0]["string"] == "HelloFromREAI"

    @pytest.mark.asyncio
    async def test_extract_strings_max_results(self, client, mock_backend) -> None:
        """max_results query param caps the strings array (client-side truncation)."""
        with patch("backend.api.analysis.get_analysis_backend", return_value=mock_backend):
            resp = await client.post(
                "/api/analysis/extract-strings",
                json={"path": "/mock/file.dll", "max_results": 1},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["strings"]) == 1
        assert data["displayed_count"] == 1
        assert data["truncated"] is True

    # ── disassemble ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_disassemble_shape(self, client, mock_backend) -> None:
        """POST /api/analysis/disassemble returns instructions array and architecture."""
        with patch("backend.api.analysis.get_analysis_backend", return_value=mock_backend):
            resp = await client.post(
                "/api/analysis/disassemble",
                json={"path": "/mock/file.dll", "section_name": ".text", "offset": 0},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["instructions"], list)
        assert data["architecture"] == "AMD64"
        assert data["section_name"] == ".text"
        assert data["instructions"][0]["mnemonic"] == "ret"

    # ── analyze-batch ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_analyze_batch_shape(self, client, mock_backend, tmp_path) -> None:
        """POST /api/analysis/analyze-batch returns file list and summary."""
        # Create a temp dir with a .dll file
        fake_dll = tmp_path / "myapp.dll"
        fake_dll.write_bytes(b"\x00" * 64)
        with patch("backend.api.analysis.get_analysis_backend", return_value=mock_backend):
            resp = await client.post(
                "/api/analysis/analyze-batch",
                json={"directory": str(tmp_path)},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["files"], list)
        assert isinstance(data["summary"], str)
        assert data["total_found"] >= 1
        assert "Analyzed" in data["summary"]


# ═══════════════════════════════════════════════════════════════════════
# Real-backend tests  (actual PE analysis on fixture DLLs)
# ═══════════════════════════════════════════════════════════════════════


class TestRealBackend:
    """Exercise actual PE analysis through HTTP against fixture DLLs."""

    @pytest.mark.asyncio
    async def test_extract_pe_info_real(self, client) -> None:
        """POST /api/analysis/extract-pe-info on fixture DLL returns real structure."""
        resp = await client.post(
            "/api/analysis/extract-pe-info",
            json={"path": TEST_DLL},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["machine_type"] == "AMD64"
        assert data["is_dll"] is True
        assert data["is_exe"] is False
        assert len(data["sections"]) > 0
        section_names = [s["name"] for s in data["sections"]]
        assert ".text" in section_names
        assert ".data" in section_names
        assert "imphash" in data

    @pytest.mark.asyncio
    async def test_extract_pe_info_arm(self, client) -> None:
        """ARM PE fixture returns ARM machine type."""
        resp = await client.post(
            "/api/analysis/extract-pe-info",
            json={"path": TEST_ARM},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["machine_type"] == "ARM"

    @pytest.mark.asyncio
    async def test_list_imports_exports_real(self, client) -> None:
        """Fixture DLL has no imports/exports — returns empty arrays."""
        resp = await client.post(
            "/api/analysis/list-imports-exports",
            json={"path": TEST_DLL},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["imports"], list)
        assert isinstance(data["exports"], list)
        # Our minimal DLL has no import/export directory entries
        assert data["imports"] == []
        assert data["exports"] == []

    @pytest.mark.asyncio
    async def test_extract_strings_real(self, client) -> None:
        """Fixture DLL contains known embedded strings."""
        resp = await client.post(
            "/api/analysis/extract-strings",
            json={"path": TEST_DLL},
        )
        assert resp.status_code == 200
        data = resp.json()
        texts = [s["string"] for s in data["strings"]]
        assert "HelloFromREAI" in texts
        assert "REAI_ANALYSIS" in texts
        assert data["total_count"] >= 4

    @pytest.mark.asyncio
    async def test_extract_strings_min_length(self, client) -> None:
        """min_length parameter filters shorter strings."""
        resp = await client.post(
            "/api/analysis/extract-strings",
            json={"path": TEST_DLL, "min_length": 10},
        )
        assert resp.status_code == 200
        texts = [s["string"] for s in resp.json()["strings"]]
        assert "HelloFromREAI" in texts  # 12 chars
        assert "REAI_v1.0" not in texts  # 9 chars

    @pytest.mark.asyncio
    async def test_disassemble_real(self, client) -> None:
        """Disassemble .text section at offset 0 (ret instruction)."""
        resp = await client.post(
            "/api/analysis/disassemble",
            json={"path": TEST_DLL, "section_name": ".text", "offset": 0, "size": 16},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["architecture"] == "AMD64"
        assert data["section_name"] == ".text"
        assert len(data["instructions"]) >= 1
        # First instruction should be `ret`
        assert data["instructions"][0]["mnemonic"] == "ret"

    @pytest.mark.asyncio
    async def test_analyze_batch_real(self, client, tmp_path) -> None:
        """Batch analysis of fixture DLL directory returns files list."""
        import shutil
        shutil.copy2(TEST_DLL, str(tmp_path / "minimal_test.dll"))
        shutil.copy2(TEST_ARM, str(tmp_path / "test_arm.dll"))
        # Add a non-PE file to verify skipping
        (tmp_path / "notes.txt").write_text("not a PE file")

        resp = await client.post(
            "/api/analysis/analyze-batch",
            json={"directory": str(tmp_path)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["files"]) == 2
        assert data["total_found"] == 2
        assert data["non_pe_skipped"] == 1
        assert "Analyzed" in data["summary"]


# ═══════════════════════════════════════════════════════════════════════
# Error handling tests
# ═══════════════════════════════════════════════════════════════════════


class TestErrorHandling:
    """Validation errors, missing files, and non-PE input."""

    # ── Missing path → 422 ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_extract_pe_info_missing_path_422(self, client) -> None:
        """Missing path field returns 422 validation error."""
        resp = await client.post("/api/analysis/extract-pe-info", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_imports_exports_missing_path_422(self, client) -> None:
        """Missing path field returns 422 validation error."""
        resp = await client.post("/api/analysis/list-imports-exports", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_extract_strings_missing_path_422(self, client) -> None:
        """Missing path field returns 422 validation error."""
        resp = await client.post("/api/analysis/extract-strings", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_disassemble_missing_path_422(self, client) -> None:
        """Missing path field returns 422 validation error."""
        resp = await client.post(
            "/api/analysis/disassemble",
            json={"section_name": ".text", "offset": 0},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_disassemble_missing_section_422(self, client) -> None:
        """Missing section_name field returns 422 validation error."""
        resp = await client.post(
            "/api/analysis/disassemble",
            json={"path": TEST_DLL, "offset": 0},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_analyze_batch_missing_dir_422(self, client) -> None:
        """Missing directory field returns 422 validation error."""
        resp = await client.post("/api/analysis/analyze-batch", json={})
        assert resp.status_code == 422

    # ── Non-existent path → 400 ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_extract_pe_info_bad_path_400(self, client) -> None:
        """Non-existent path returns 400 with error detail."""
        resp = await client.post(
            "/api/analysis/extract-pe-info",
            json={"path": "/nonexistent/file.dll"},
        )
        assert resp.status_code == 400
        assert "detail" in resp.json()

    @pytest.mark.asyncio
    async def test_list_imports_exports_bad_path_400(self, client) -> None:
        """Non-existent path returns 400 with error detail."""
        resp = await client.post(
            "/api/analysis/list-imports-exports",
            json={"path": "/nonexistent/file.dll"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_extract_strings_bad_path_400(self, client) -> None:
        """Non-existent path returns 400 with error detail."""
        resp = await client.post(
            "/api/analysis/extract-strings",
            json={"path": "/nonexistent/file.dll"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_disassemble_bad_path_400(self, client) -> None:
        """Non-existent path returns 400 with error detail."""
        resp = await client.post(
            "/api/analysis/disassemble",
            json={"path": "/nonexistent/file.dll", "section_name": ".text", "offset": 0},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_analyze_batch_bad_dir_400(self, client) -> None:
        """Non-existent directory returns 400 with error detail."""
        resp = await client.post(
            "/api/analysis/analyze-batch",
            json={"directory": "/nonexistent/dir"},
        )
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"].lower()

    # ── Non-PE file → 400 ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_extract_pe_info_non_pe_400(self, client, tmp_path) -> None:
        """Non-PE binary file returns 400."""
        non_pe = tmp_path / "not_a_pe.bin"
        non_pe.write_bytes(b"\x00" * 128)
        resp = await client.post(
            "/api/analysis/extract-pe-info",
            json={"path": str(non_pe)},
        )
        assert resp.status_code == 400
        assert "detail" in resp.json()

    @pytest.mark.asyncio
    async def test_list_imports_exports_non_pe_400(self, client, tmp_path) -> None:
        """Non-PE binary file returns 400."""
        non_pe = tmp_path / "not_a_pe.bin"
        non_pe.write_bytes(b"\x00" * 128)
        resp = await client.post(
            "/api/analysis/list-imports-exports",
            json={"path": str(non_pe)},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_extract_strings_non_pe_400(self, client, tmp_path) -> None:
        """Non-PE binary file returns 400 for strings."""
        non_pe = tmp_path / "not_a_pe.bin"
        non_pe.write_bytes(b"\x00" * 128)
        resp = await client.post(
            "/api/analysis/extract-strings",
            json={"path": str(non_pe)},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_disassemble_non_pe_400(self, client, tmp_path) -> None:
        """Non-PE binary file returns 400 for disassemble."""
        non_pe = tmp_path / "not_a_pe.bin"
        non_pe.write_bytes(b"\x00" * 128)
        resp = await client.post(
            "/api/analysis/disassemble",
            json={"path": str(non_pe), "section_name": ".text", "offset": 0},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_analyze_batch_empty_dir_400(self, client, tmp_path) -> None:
        """Empty directory returns 400 with 'No PE files found'."""
        resp = await client.post(
            "/api/analysis/analyze-batch",
            json={"directory": str(tmp_path)},
        )
        assert resp.status_code == 400
        assert "No PE files found" in resp.json()["detail"]
