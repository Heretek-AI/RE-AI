"""Tests for the analysis backend — base ABC, result types, and native impl."""

from __future__ import annotations

from pathlib import Path
from typing import get_type_hints

import pytest

from backend.analysis import (
    AbstractAnalysisBackend,
    AnalysisError,
    DisassemblyResult,
    FileInfoResult,
    ImportsExportsResult,
    NativePythonBackend,
    PeStructureResult,
    StringsResult,
    get_analysis_backend,
    list_available_backends,
)
from backend.analysis.base import AbstractAnalysisBackend
from backend.analysis.native import NativePythonBackend


# ---------------------------------------------------------------------------
# T02 — ABC & result types
# ---------------------------------------------------------------------------


class TestAnalysisError:
    """AnalysisError is raise-able and has a proper str representation."""

    def test_raise_and_str(self) -> None:
        err = AnalysisError("test message")
        assert str(err) == "test message"
        assert isinstance(err, Exception)

    def test_with_cause(self) -> None:
        try:
            raise ValueError("inner")
        except ValueError as exc:
            err = AnalysisError("wrapped")
            err.__cause__ = exc
        assert isinstance(err.__cause__, ValueError)
        assert str(err) == "wrapped"


class TestABC:
    """AbstractAnalysisBackend cannot be instantiated directly."""

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            AbstractAnalysisBackend()  # type: ignore[abstract]

    def test_method_signatures(self) -> None:
        """Verify abstract method signatures match expected parameters."""
        # Use inspect to verify method signatures without instantiating
        import inspect

        sig = inspect.signature(AbstractAnalysisBackend.analyze_pe_structure)
        params = list(sig.parameters.keys())
        assert params == ["self", "path"]
        # path must be typed str
        hints = get_type_hints(AbstractAnalysisBackend.analyze_pe_structure)
        assert hints["path"] is str
        # Return type is dict[str, Any] — just verify it's a dict
        assert hints["return"].__origin__ is dict

        sig = inspect.signature(AbstractAnalysisBackend.get_imports_exports)
        params = list(sig.parameters.keys())
        assert params == ["self", "path"]

        sig = inspect.signature(AbstractAnalysisBackend.extract_strings)
        params = list(sig.parameters.keys())
        assert params == ["self", "path", "min_length"]
        # min_length must default to 5
        default = next(
            v.default
            for k, v in inspect.signature(
                AbstractAnalysisBackend.extract_strings
            ).parameters.items()
            if k == "min_length"
        )
        assert default == 5

        sig = inspect.signature(AbstractAnalysisBackend.disassemble_function)
        params = list(sig.parameters.keys())
        assert params == ["self", "path", "section_name", "offset", "size"]
        default_size = next(
            v.default
            for k, v in inspect.signature(
                AbstractAnalysisBackend.disassemble_function
            ).parameters.items()
            if k == "size"
        )
        assert default_size == 256

        sig = inspect.signature(AbstractAnalysisBackend.get_file_info)
        params = list(sig.parameters.keys())
        assert params == ["self", "path"]


class TestResultTypes:
    """Result type TypedDicts can be constructed (not enforced at runtime)."""

    def test_pe_structure_result_fields(self) -> None:
        """Verify PeStructureResult has the expected fields."""
        fields = set(PeStructureResult.__annotations__)
        expected = {
            "machine_type",
            "characteristics",
            "is_dll",
            "is_exe",
            "subsystems",
            "sections",
            "entry_point",
            "image_base",
            "size_of_image",
            "imphash",
        }
        assert fields == expected

    def test_imports_exports_result_fields(self) -> None:
        fields = set(ImportsExportsResult.__annotations__)
        expected = {"imports", "exports", "has_exceptions"}
        assert fields == expected

    def test_strings_result_fields(self) -> None:
        fields = set(StringsResult.__annotations__)
        expected = {"strings", "total_count", "displayed_count"}
        assert fields == expected

    def test_disassembly_result_fields(self) -> None:
        fields = set(DisassemblyResult.__annotations__)
        expected = {
            "architecture",
            "mode",
            "section_name",
            "offset",
            "bytes_count",
            "instructions",
            "truncated",
        }
        assert fields == expected

    def test_file_info_result_fields(self) -> None:
        fields = set(FileInfoResult.__annotations__)
        expected = {
            "path",
            "size_bytes",
            "md5",
            "sha256",
            "is_pe",
            "subsystem",
            "architecture",
            "is_dll",
            "is_exe",
            "entry_point",
            "timestamp",
        }
        assert fields == expected


# ---------------------------------------------------------------------------
# T03 — NativePythonBackend concrete implementation
# ---------------------------------------------------------------------------


@pytest.fixture()
def native() -> NativePythonBackend:
    from backend.analysis.native import NativePythonBackend

    return NativePythonBackend()


class TestNativePythonBackend:
    """NativePythonBackend with pefile + capstone."""

    pytestmark = pytest.mark.asyncio

    # ── Fixture paths ──────────────────────────────────────────────────

    FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
    TEST_DLL = str(FIXTURE_DIR / "minimal_test.dll")
    TEST_ARM = str(FIXTURE_DIR / "test_arm.dll")

    # ── analyze_pe_structure ───────────────────────────────────────────

    async def test_analyze_pe_structure_amd64(self, native) -> None:
        result = await native.analyze_pe_structure(self.TEST_DLL)
        assert result["machine_type"] == "AMD64"
        assert result["is_dll"] is True
        assert result["is_exe"] is False
        assert len(result["sections"]) > 0
        section_names = [s["name"] for s in result["sections"]]
        assert ".text" in section_names
        assert ".data" in section_names
        assert result["image_base"] == 0x180000000
        assert result["size_of_image"] > 0
        assert "imphash" in result

    async def test_analyze_pe_structure_arm(self, native) -> None:
        result = await native.analyze_pe_structure(self.TEST_ARM)
        assert result["machine_type"] == "ARM"
        assert result["is_dll"] is True

    async def test_analyze_pe_structure_non_pe(self, native) -> None:
        """Non-PE binary file should raise AnalysisError."""
        non_pe = str(self.FIXTURE_DIR / "minimal_test.dll")
        # Temporarily make a non-PE copy
        tmp = self.FIXTURE_DIR / "_non_pe_test.bin"
        tmp.write_bytes(b"\x00" * 128)
        try:
            with pytest.raises(AnalysisError):
                await native.analyze_pe_structure(str(tmp))
        finally:
            tmp.unlink(missing_ok=True)

    # ── get_imports_exports ────────────────────────────────────────────

    async def test_get_imports_exports_empty(self, native) -> None:
        """Fixture DLL has no imports/exports — should return empty lists."""
        result = await native.get_imports_exports(self.TEST_DLL)
        assert isinstance(result["imports"], list)
        assert isinstance(result["exports"], list)
        # Our minimal DLL has no import/export directory entries
        assert result["imports"] == []
        assert result["exports"] == []

    # ── extract_strings ────────────────────────────────────────────────

    async def test_extract_strings_finds_hello(self, native) -> None:
        result = await native.extract_strings(self.TEST_DLL, min_length=3)
        texts = [s["string"] for s in result["strings"]]
        assert "HelloFromREAI" in texts
        assert "REAI_ANALYSIS" in texts
        assert "REAI_v1.0" in texts
        assert result["total_count"] >= 4
        assert result["displayed_count"] <= result["total_count"]

    async def test_extract_strings_min_length_filter(self, native) -> None:
        """With min_length=10, shorter strings like 'REAI_v1.0' (9 chars) are excluded."""
        result = await native.extract_strings(self.TEST_DLL, min_length=10)
        texts = [s["string"] for s in result["strings"]]
        assert "HelloFromREAI" in texts  # 12 chars
        assert "REAI_v1.0" not in texts  # 9 chars

    # ── disassemble_function ───────────────────────────────────────────

    async def test_disassemble_ret_instruction(self, native) -> None:
        """Disassemble .text section at offset 0 (the ret instruction)."""
        result = await native.disassemble_function(
            self.TEST_DLL, section_name=".text", offset=0, size=16
        )
        assert result["architecture"] == "AMD64"
        assert result["section_name"] == ".text"
        assert result["offset"] == 0
        assert len(result["instructions"]) >= 1
        # First instruction should be `ret`
        first = result["instructions"][0]
        assert first["mnemonic"] == "ret"

    async def test_disassemble_section_not_found(self, native) -> None:
        """Requesting a non-existent section raises AnalysisError."""
        with pytest.raises(AnalysisError):
            await native.disassemble_function(
                self.TEST_DLL, section_name=".bogus", offset=0, size=16
            )

    # ── get_file_info ──────────────────────────────────────────────────

    async def test_get_file_info_pe(self, native) -> None:
        result = await native.get_file_info(self.TEST_DLL)
        assert result["path"] == self.TEST_DLL
        assert result["size_bytes"] > 0
        assert result["is_pe"] is True
        assert result["architecture"] == "AMD64"
        assert result["is_dll"] is True
        assert result["is_exe"] is False
        assert isinstance(result["md5"], str) and len(result["md5"]) == 32
        assert isinstance(result["sha256"], str) and len(result["sha256"]) == 64

    async def test_get_file_info_non_pe(self, native) -> None:
        """A non-PE file returns is_pe=False with correct size/hash."""
        non_pe = self.FIXTURE_DIR / "_non_pe_info.bin"
        content = b"AAAAABBBBBCCCCCDDDDD"  # 20 bytes
        non_pe.write_bytes(content)
        try:
            result = await native.get_file_info(str(non_pe))
            assert result["is_pe"] is False
            assert result["size_bytes"] == 20
            assert result["subsystem"] is None
            assert result["architecture"] is None
            import hashlib
            expected_md5 = hashlib.md5(content).hexdigest()
            expected_sha256 = hashlib.sha256(content).hexdigest()
            assert result["md5"] == expected_md5
            assert result["sha256"] == expected_sha256
        finally:
            non_pe.unlink(missing_ok=True)

    # ── Error: non-existent file ───────────────────────────────────────

    async def test_analyze_pe_bad_path(self, native) -> None:
        with pytest.raises(AnalysisError):
            await native.analyze_pe_structure("/nonexistent/path.dll")

    async def test_get_file_info_bad_path(self, native) -> None:
        with pytest.raises(AnalysisError):
            await native.get_file_info("/nonexistent/path.dll")

    async def test_get_imports_exports_bad_path(self, native) -> None:
        with pytest.raises(AnalysisError):
            await native.get_imports_exports("/nonexistent/path.dll")

    async def test_extract_strings_bad_path(self, native) -> None:
        with pytest.raises(AnalysisError):
            await native.extract_strings("/nonexistent/path.dll")

    async def test_disassemble_bad_path(self, native) -> None:
        with pytest.raises(AnalysisError):
            await native.disassemble_function(
                "/nonexistent/path.dll", section_name=".text", offset=0
            )

    # ── ARM PE detection ───────────────────────────────────────────────

    async def test_arm_pe_structure(self, native) -> None:
        """ARM PE DLL reports ARM machine type."""
        result = await native.analyze_pe_structure(self.TEST_ARM)
        assert result["machine_type"] == "ARM"

    async def test_arm_file_info(self, native) -> None:
        result = await native.get_file_info(self.TEST_ARM)
        assert result["is_pe"] is True
        assert result["architecture"] == "ARM"

    async def test_arm_disassemble(self, native) -> None:
        """ARM Thumb code (BX LR = 0x4770) should disassemble."""
        result = await native.disassemble_function(
            self.TEST_ARM, section_name=".text", offset=0, size=16
        )
        assert result["architecture"] == "ARM"
        assert len(result["instructions"]) >= 1


# ---------------------------------------------------------------------------
# T04 — Registry, factory, and list_available_backends
# ---------------------------------------------------------------------------


class TestAnalysisRegistry:
    """Backend registry and factory function."""

    @staticmethod
    def test_factory_empty_config_returns_native() -> None:
        """Factory returns NativePythonBackend for empty config."""
        backend = get_analysis_backend({})
        assert isinstance(backend, NativePythonBackend)

    @staticmethod
    def test_factory_native_config() -> None:
        """Factory returns NativePythonBackend for 'native'."""
        backend = get_analysis_backend({"analysis_backend": "native"})
        assert isinstance(backend, NativePythonBackend)

    @staticmethod
    def test_factory_unknown_name_falls_back() -> None:
        """Factory returns NativePythonBackend for unknown name (fallback)."""
        backend = get_analysis_backend({"analysis_backend": "ida_pro"})
        assert isinstance(backend, NativePythonBackend)

    @staticmethod
    def test_list_available_backends_contains_native() -> None:
        """list_available_backends returns at least one entry with 'native'."""
        backends = list_available_backends()
        assert len(backends) >= 1
        names = [b["name"] for b in backends]
        assert "native" in names
        for b in backends:
            assert "name" in b
            assert "description" in b


# ---------------------------------------------------------------------------
# T05 — Analysis ToolDefs in agent tools
# ---------------------------------------------------------------------------


class TestAnalysisToolDefs:
    """Integration tests for the 5 analysis ToolDefs in backend/agent/tools.py.

    These tests call execute_tool_call() with a mock PlanningEngine (the
    analysis tools don't use the engine — it's passed as required by the
    ToolDef API). The real backend (NativePythonBackend) performs actual
    analysis on fixture PE files.
    """

    FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
    TEST_DLL = str(FIXTURE_DIR / "minimal_test.dll")
    TEST_ARM = str(FIXTURE_DIR / "test_arm.dll")

    @pytest.fixture()
    def mock_engine(self):
        """Return a minimal mock PlanningEngine (unused by analysis tools)."""
        from unittest.mock import AsyncMock, MagicMock

        return AsyncMock()

    @pytest.fixture(autouse=True)
    def _import_tools(self):
        """Lazy import the tools module so the analysis backend is importable."""
        from backend.agent import tools as _tools

        self.tools = _tools

    # ── extract_pe_info ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_extract_pe_info_tool(self, mock_engine) -> None:
        """extract_pe_info returns PE structure with machine type and sections."""
        result = await self.tools.execute_tool_call(
            "extract_pe_info",
            {"path": self.TEST_DLL},
            mock_engine,
        )
        assert "## PE Structure" in result
        assert "AMD64" in result
        assert ".text" in result
        assert ".data" in result
        assert "0x180000000" in result  # image base

    @pytest.mark.asyncio
    async def test_extract_pe_info_arm(self, mock_engine) -> None:
        """ARM PE reports ARM machine type."""
        result = await self.tools.execute_tool_call(
            "extract_pe_info",
            {"path": self.TEST_ARM},
            mock_engine,
        )
        assert "## PE Structure" in result
        assert "ARM" in result

    # ── list_imports_exports ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_list_imports_exports_tool(self, mock_engine) -> None:
        """list_imports_exports returns Imports / Exports sections."""
        result = await self.tools.execute_tool_call(
            "list_imports_exports",
            {"path": self.TEST_DLL},
            mock_engine,
        )
        assert "## Imports & Exports" in result
        assert "No imports found" in result
        assert "No exports found" in result

    # ── extract_strings ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_extract_strings_tool(self, mock_engine) -> None:
        """extract_strings finds 'HelloFromREAI' string."""
        result = await self.tools.execute_tool_call(
            "extract_strings",
            {"path": self.TEST_DLL},
            mock_engine,
        )
        assert "## Strings" in result
        assert "HelloFromREAI" in result
        assert "REAI_ANALYSIS" in result

    @pytest.mark.asyncio
    async def test_extract_strings_min_length(self, mock_engine) -> None:
        """Strings with min_length=10 excludes shorter strings."""
        result = await self.tools.execute_tool_call(
            "extract_strings",
            {"path": self.TEST_DLL, "min_length": 10},
            mock_engine,
        )
        assert "HelloFromREAI" in result
        assert "REAI_v1.0" not in result  # 9 chars

    @pytest.mark.asyncio
    async def test_extract_strings_max_results(self, mock_engine) -> None:
        """max_results caps the number of displayed strings."""
        result = await self.tools.execute_tool_call(
            "extract_strings",
            {"path": self.TEST_DLL, "max_results": 1},
            mock_engine,
        )
        assert "## Strings" in result
        # Should only show 1 string + the "more strings not shown" note
        assert "more strings not shown" in result

    # ── disassemble_function ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_disassemble_function_tool(self, mock_engine) -> None:
        """Disassemble .text at offset 0 shows at least one instruction."""
        result = await self.tools.execute_tool_call(
            "disassemble_function",
            {"path": self.TEST_DLL, "section_name": ".text", "offset": 0, "size": 16},
            mock_engine,
        )
        assert "## Disassembly" in result
        assert "AMD64" in result
        assert "ret" in result  # first instruction is ret

    # ── analyze_directory ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_analyze_directory_tool(self, mock_engine, tmp_path) -> None:
        """Analyze a temp dir with fixture DLLs."""
        import shutil

        # Copy fixture DLLs to temp dir
        shutil.copy2(self.TEST_DLL, str(tmp_path / "minimal_test.dll"))
        # Add a non-PE file to test skipping
        (tmp_path / "notes.txt").write_text("This is not a PE file.\n")
        # Add a non-exe/dll file that should be skipped
        (tmp_path / "data.bin").write_bytes(b"\x00" * 64)

        result = await self.tools.execute_tool_call(
            "analyze_directory",
            {"directory": str(tmp_path)},
            mock_engine,
        )
        assert "## Directory Analysis" in result
        assert "minimal_test.dll" in result
        assert "AMD64" in result
        assert "DLL" in result
        assert "1 PE file(s)" in result
        assert "non-PE file(s) skipped" in result

    @pytest.mark.asyncio
    async def test_analyze_directory_empty(self, mock_engine, tmp_path) -> None:
        """Empty directory returns 'No PE files found'."""
        result = await self.tools.execute_tool_call(
            "analyze_directory",
            {"directory": str(tmp_path)},
            mock_engine,
        )
        assert "No PE files found" in result

    @pytest.mark.asyncio
    async def test_analyze_directory_missing(self, mock_engine) -> None:
        """Non-existent directory returns ERROR."""
        result = await self.tools.execute_tool_call(
            "analyze_directory",
            {"directory": "/nonexistent/path"},
            mock_engine,
        )
        assert result.startswith("ERROR:")

    # ── Error handling: invalid paths ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_tool_invalid_path_extract_pe(self, mock_engine) -> None:
        """extract_pe_info returns ERROR for non-existent path."""
        result = await self.tools.execute_tool_call(
            "extract_pe_info",
            {"path": "/nonexistent/file.dll"},
            mock_engine,
        )
        assert result.startswith("ERROR:")

    @pytest.mark.asyncio
    async def test_tool_invalid_path_imports_exports(self, mock_engine) -> None:
        """list_imports_exports returns ERROR for non-existent path."""
        result = await self.tools.execute_tool_call(
            "list_imports_exports",
            {"path": "/nonexistent/file.dll"},
            mock_engine,
        )
        assert result.startswith("ERROR:")

    @pytest.mark.asyncio
    async def test_tool_invalid_path_strings(self, mock_engine) -> None:
        """extract_strings returns ERROR for non-existent path."""
        result = await self.tools.execute_tool_call(
            "extract_strings",
            {"path": "/nonexistent/file.dll"},
            mock_engine,
        )
        assert result.startswith("ERROR:")

    @pytest.mark.asyncio
    async def test_tool_invalid_path_disassemble(self, mock_engine) -> None:
        """disassemble_function returns ERROR for non-existent path."""
        result = await self.tools.execute_tool_call(
            "disassemble_function",
            {"path": "/nonexistent/file.dll", "section_name": ".text", "offset": 0},
            mock_engine,
        )
        assert result.startswith("ERROR:")

    @pytest.mark.asyncio
    async def test_tool_invalid_path_analyze_dir(self, mock_engine) -> None:
        """analyze_directory returns ERROR for non-existent path."""
        result = await self.tools.execute_tool_call(
            "analyze_directory",
            {"directory": "/nonexistent/dir"},
            mock_engine,
        )
        assert result.startswith("ERROR:")

    # ── Error handling: not a PE file ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_tool_not_a_pe_extract_pe(self, mock_engine, tmp_path) -> None:
        """extract_pe_info returns ERROR for non-PE file."""
        non_pe = tmp_path / "not_a_pe.bin"
        non_pe.write_bytes(b"\x00" * 128)
        result = await self.tools.execute_tool_call(
            "extract_pe_info",
            {"path": str(non_pe)},
            mock_engine,
        )
        # The underlying backend raises AnalysisError — tool catches it
        assert result.startswith("ERROR:")

    @pytest.mark.asyncio
    async def test_tool_not_a_pe_imports_exports(self, mock_engine, tmp_path) -> None:
        """list_imports_exports returns ERROR for non-PE file."""
        non_pe = tmp_path / "not_a_pe.bin"
        non_pe.write_bytes(b"\x00" * 128)
        result = await self.tools.execute_tool_call(
            "list_imports_exports",
            {"path": str(non_pe)},
            mock_engine,
        )
        assert result.startswith("ERROR:")

    @pytest.mark.asyncio
    async def test_tool_not_a_pe_strings(self, mock_engine, tmp_path) -> None:
        """extract_strings returns ERROR for non-PE file."""
        non_pe = tmp_path / "not_a_pe.bin"
        non_pe.write_bytes(b"\x00" * 128)
        result = await self.tools.execute_tool_call(
            "extract_strings",
            {"path": str(non_pe)},
            mock_engine,
        )
        assert result.startswith("ERROR:")

    @pytest.mark.asyncio
    async def test_tool_not_a_pe_disassemble(self, mock_engine, tmp_path) -> None:
        """disassemble_function returns ERROR for non-PE file."""
        non_pe = tmp_path / "not_a_pe.bin"
        non_pe.write_bytes(b"\x00" * 128)
        result = await self.tools.execute_tool_call(
            "disassemble_function",
            {"path": str(non_pe), "section_name": ".text", "offset": 0},
            mock_engine,
        )
        assert result.startswith("ERROR:")

    # ── Schema registration ────────────────────────────────────────────

    def test_tool_schema_registration(self) -> None:
        """All 5 analysis tool names appear in get_tool_schemas()."""
        schemas = self.tools.get_tool_schemas()
        names = {s["function"]["name"] for s in schemas}
        for expected in (
            "extract_pe_info",
            "list_imports_exports",
            "extract_strings",
            "disassemble_function",
            "analyze_directory",
        ):
            assert expected in names, f"Tool {expected!r} missing from get_tool_schemas()"

    # ── Missing arguments → ERROR ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_tool_missing_path_extract_pe(self, mock_engine) -> None:
        """extract_pe_info with no path returns ERROR."""
        result = await self.tools.execute_tool_call(
            "extract_pe_info", {}, mock_engine,
        )
        assert result.startswith("ERROR:")

    @pytest.mark.asyncio
    async def test_tool_missing_section_name(self, mock_engine) -> None:
        """disassemble_function with missing section_name returns ERROR."""
        result = await self.tools.execute_tool_call(
            "disassemble_function",
            {"path": self.TEST_DLL},
            mock_engine,
        )
        assert result.startswith("ERROR:")

    @pytest.mark.asyncio
    async def test_tool_missing_directory(self, mock_engine) -> None:
        """analyze_directory with no directory returns ERROR."""
        result = await self.tools.execute_tool_call(
            "analyze_directory", {}, mock_engine,
        )
        assert result.startswith("ERROR:")
