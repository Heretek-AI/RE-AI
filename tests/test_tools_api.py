"""Tests for the tools API endpoints, including path validation.

Tests use mocking to avoid requiring actual IDA Pro or Ghidra
installations during unit testing.
"""

import os
import subprocess
import tempfile
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.api.tools import (
    ValidatePathRequest,
    ValidatePathResponse,
    _validate_ida,
    _validate_ghidra,
    _KNOWN_VALIDATABLE_TOOLS,
    _VALIDATORS,
)


# =========================================================================
# Helper: create a temp executable that pretends to be a tool
# =========================================================================


def _make_script(content: str, suffix: str = ".bat") -> str:
    """Write a temporary script and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix, text=True)
    os.write(fd, content.encode("utf-8"))
    os.close(fd)
    os.chmod(path, 0o755)
    return path


# =========================================================================
# _validate_ida tests
# =========================================================================


class TestValidateIda:
    def test_ida_file_not_found(self):
        """Non-existent path returns valid=False with 'File not found'."""
        result = _validate_ida(r"C:\no_such_ida\idat64.exe")
        assert result.valid is False
        assert result.error == "File not found"

    def test_ida_validation_success(self):
        """A valid IDA binary (exit 0) returns valid=True."""
        script = _make_script("@echo off\necho IDA Pro v8.4\nexit /b 0\n")
        try:
            result = _validate_ida(script)
            assert result.valid is True
        finally:
            os.unlink(script)

    def test_ida_validation_failure(self):
        """An IDA binary that exits non-zero returns valid=False."""
        script = _make_script("@echo off\nexit /b 1\n")
        try:
            result = _validate_ida(script)
            assert result.valid is False
            assert "exit code 1" in (result.error or "")
        finally:
            os.unlink(script)

    def test_ida_timeout_handled(self):
        """An IDA binary that hangs gets caught by the timeout."""
        script = _make_script("@echo off\nping -n 60 127.0.0.1 > nul\nexit /b 0\n")
        try:
            result = _validate_ida(script)
            assert result.valid is False
            assert "timed out" in (result.error or "")
        finally:
            os.unlink(script)


# =========================================================================
# _validate_ghidra tests
# =========================================================================


class TestValidateGhidra:
    def test_ghidra_file_not_found(self):
        """Non-existent path returns valid=False with 'File not found'."""
        result = _validate_ghidra(r"C:\no_such_ghidra\analyzeHeadless.bat")
        assert result.valid is False
        assert result.error == "File not found"

    def test_ghidra_validation_success(self):
        """A analyzeHeadless binary with Ghidra output returns valid=True."""
        script = _make_script(
            "@echo off\necho Ghidra 11.1 analyzeHeadless\nexit /b 0\n"
        )
        try:
            result = _validate_ghidra(script)
            assert result.valid is True
        finally:
            os.unlink(script)

    def test_ghidra_validation_usage_output(self):
        """analyzeHeadless returning 'Usage' output and exit 1 is still valid."""
        script = _make_script(
            "@echo off\necho Usage: analyzeHeadless [project] [script]\nexit /b 1\n"
        )
        try:
            result = _validate_ghidra(script)
            assert result.valid is True
        finally:
            os.unlink(script)

    def test_ghidra_validation_unrecognized_binary(self):
        """A binary that doesn't mention Ghidra/analyzeHeadless returns valid=False."""
        script = _make_script("@echo off\necho Hello World\nexit /b 0\n")
        try:
            result = _validate_ghidra(script)
            assert result.valid is False
            assert "not respond as analyzeHeadless" in (result.error or "")
        finally:
            os.unlink(script)

    def test_ghidra_timeout_handled(self):
        """A Ghidra binary that hangs gets caught by the timeout."""
        script = _make_script(
            "@echo off\nping -n 30 127.0.0.1 > nul\nexit /b 0\n"
        )
        try:
            result = _validate_ghidra(script)
            assert result.valid is False
            assert "timed out" in (result.error or "")
        finally:
            os.unlink(script)


# =========================================================================
# Endpoint contract tests
# =========================================================================


class TestValidatePathEndpoint:
    """Test the validate-path endpoint via its inner logic.

    These tests verify the dispatch and error handling logic that would
    otherwise require httpx ASGI transport (which existing test_e2e_routers
    tests use). We test the core logic directly to avoid test framework
    complexity.
    """

    def test_known_tools_are_validatable(self):
        """Only ida_pro and ghidra are in the known set."""
        assert _KNOWN_VALIDATABLE_TOOLS == {"ida_pro", "ghidra"}

    def test_validator_registry_has_entries(self):
        """Each known tool has a validator function registered."""
        for tid in _KNOWN_VALIDATABLE_TOOLS:
            assert tid in _VALIDATORS, f"{tid} missing from _VALIDATORS"
            assert callable(_VALIDATORS[tid]), f"{tid} validator not callable"

    def test_unknown_tool_id_raises(self):
        """An unknown tool_id is rejected."""
        from backend.api.tools import validate_tool_path

        req = ValidatePathRequest(tool_id="nonexistent_tool", path=r"C:\test.exe")

        async def _run():
            try:
                await validate_tool_path(req)
                return None
            except HTTPException as exc:
                return exc

        import asyncio

        exc = asyncio.run(_run())
        assert exc is not None
        assert exc.status_code == 400
        assert "Unknown tool_id" in exc.detail


# =========================================================================
# Version extraction tests
# =========================================================================


class TestVersionExtraction:
    def test_ida_version_extracted(self):
        """IDA validation extracts version from output containing 'version'."""
        script = _make_script(
            "@echo off\necho IDA Pro version 8.4.240925 Windows x86_64\nexit /b 0\n"
        )
        try:
            result = _validate_ida(script)
            assert result.valid is True
            assert result.version is not None
            assert "version 8.4" in result.version
        finally:
            os.unlink(script)

    def test_ghidra_version_extracted(self):
        """Ghidra validation extracts version from version-like output lines."""
        script = _make_script(
            "@echo off\necho Ghidra version 11.1 released\nexit /b 0\n"
        )
        try:
            result = _validate_ghidra(script)
            assert result.valid is True
            assert result.version is not None
            assert "version 11.1" in result.version
        finally:
            os.unlink(script)
