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
