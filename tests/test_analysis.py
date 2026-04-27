"""Tests for the analysis backend — base ABC, result types, and native impl."""

from __future__ import annotations

from typing import get_type_hints

import pytest

from backend.analysis import (
    AbstractAnalysisBackend,
    AnalysisError,
    DisassemblyResult,
    FileInfoResult,
    ImportsExportsResult,
    PeStructureResult,
    StringsResult,
)
from backend.analysis.base import AbstractAnalysisBackend


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
