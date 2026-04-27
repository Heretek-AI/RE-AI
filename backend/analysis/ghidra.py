"""Ghidra analysis backend using headless subprocess calls.

Wraps ``analyzeHeadless`` invocations, launching the Ghidra analysis
script (``ghidra_analysis.py``) in headless mode and returning its
JSON output.

Parameters are passed via environment variables (see the
``ghidra_scripts`` package docstring for details).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path
from typing import Any

import anyio

from backend.analysis.base import AbstractAnalysisBackend, AnalysisError

logger = logging.getLogger("backend.analysis.ghidra")

# Default timeout for Ghidra headless scripts (seconds).
# Ghidra's auto-analysis is slower than IDA's, so the timeout is longer.
_GHIDRA_TIMEOUT: int = 360


# ═══════════════════════════════════════════════════════════════════════════
# GhidraBackend
# ═══════════════════════════════════════════════════════════════════════════


class GhidraBackend(AbstractAnalysisBackend):
    """Analysis backend that delegates to headless Ghidra (analyzeHeadless).

    Each abstract method runs ``ghidra_analysis.py`` with the corresponding
    ``GHIDRA_MODE`` in a headless Ghidra subprocess.

    The ``analyzeHeadless`` binary path is read from
    ``config["tool_configs"]["ghidra"]``.
    If the path is ``None`` (not configured), all five analysis methods
    raise :class:`AnalysisError` with a descriptive message.
    """

    # ── Constructor ──────────────────────────────────────────────────────

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__()
        config = config or {}
        tool_configs = config.get("tool_configs", {}) or {}
        self._ghidra_path: str | None = tool_configs.get("ghidra")
        self._scripts_dir: Path = (
            Path(__file__).resolve().parent / "ghidra_scripts"
        )

    # ── Internal: headless subprocess runner ─────────────────────────────

    async def _run_ghidra_script(
        self,
        mode: str,
        binary_path: str,
        env_extra: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run ``ghidra_analysis.py`` with a given *mode* in headless Ghidra.

        Parameters
        ----------
        mode:
            One of ``"structure"``, ``"imports-exports"``, ``"strings"``,
            ``"disassembly"``, or ``"file-info"``.
        binary_path:
            Absolute path to the PE/DLL to analyse.
        env_extra:
            Optional extra environment variables to pass to the script
            (e.g. ``GHIDRA_MIN_LENGTH`` for string extraction).

        Returns
        -------
        dict[str, Any]
            Parsed JSON output written by the script.

        Raises
        ------
        AnalysisError
            If Ghidra is not configured, the subprocess times out, the
            script's output file is missing, or any other error occurs.
        """
        if not self._ghidra_path:
            raise AnalysisError(
                "Ghidra is not configured — set tool_configs.ghidra"
            )

        # Create a temporary directory for the Ghidra project
        temp_dir: str | None = None
        output_path: str | None = None
        try:
            temp_dir = tempfile.mkdtemp(prefix="reai_ghidra_")
            output_path = os.path.join(
                temp_dir, f"{Path(binary_path).name}.ghidra_{mode}.json"
            )

            # Build environment
            full_env = os.environ.copy()
            full_env["GHIDRA_MODE"] = mode
            full_env["GHIDRA_OUTPUT"] = output_path
            if env_extra:
                full_env.update(env_extra)

            def _run_sync() -> subprocess.CompletedProcess:
                return subprocess.run(
                    [
                        self._ghidra_path,
                        temp_dir,
                        "TempProject",
                        "-import",
                        binary_path,
                        "-postScript",
                        "ghidra_analysis.py",
                        "-scriptPath",
                        str(self._scripts_dir),
                        "-deleteProject",
                        "-readOnly",
                        "-analysisTimeoutPerFile",
                        "360",
                    ],
                    env=full_env,
                    timeout=_GHIDRA_TIMEOUT,
                    capture_output=True,
                )

            try:
                proc = await anyio.to_thread.run_sync(_run_sync)
            except subprocess.TimeoutExpired:
                raise AnalysisError(
                    f"Ghidra timeout ({_GHIDRA_TIMEOUT}s) for mode {mode} "
                    f"on {binary_path}"
                )
            except FileNotFoundError:
                raise AnalysisError(
                    f"Ghidra binary not found: {self._ghidra_path}"
                )
            except OSError as exc:
                raise AnalysisError(
                    f"Ghidra subprocess error for mode {mode}: {exc}"
                )

            # Check return code
            if proc.returncode != 0:
                stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
                stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
                # Ghidra often prints useful error info to stdout as well
                combined = (stdout + "\n" + stderr).strip()[:2000]
                raise AnalysisError(
                    f"Ghidra script mode {mode} exited with code "
                    f"{proc.returncode}:\n{combined}"
                )

            # Read output file
            if not os.path.exists(output_path):
                # Ghidra may have printed the result to stderr/stdout
                # even if the output file is missing — surface that
                stdout = (proc.stdout or b"").decode("utf-8", errors="replace")
                stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
                combined = (stdout + "\n" + stderr).strip()[:2000]
                raise AnalysisError(
                    f"Ghidra script mode {mode} did not produce output at "
                    f"{output_path}:\n{combined}"
                )

            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    data: dict[str, Any] = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                raise AnalysisError(
                    f"Failed to read/parse Ghidra output {output_path}: {exc}"
                )

            return data

        finally:
            # Clean up temp dir and all its contents
            if temp_dir and os.path.isdir(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except OSError:
                    pass

    # ═══════════════════════════════════════════════════════════════════════
    # Abstract method implementations
    # ═══════════════════════════════════════════════════════════════════════

    # ── analyze_pe_structure ──────────────────────────────────────────────

    async def analyze_pe_structure(self, path: str) -> dict[str, Any]:
        logger.debug("Ghidra analyze_pe_structure: %s", path)
        try:
            result = await self._run_ghidra_script("structure", path)
            logger.debug("Ghidra analyze_pe_structure OK: %s", path)
            return result
        except AnalysisError:
            raise
        except Exception as exc:
            logger.error(
                "Ghidra analyze_pe_structure error: %s\n%s",
                path, traceback.format_exc(),
            )
            raise AnalysisError(str(exc)) from exc

    # ── get_imports_exports ───────────────────────────────────────────────

    async def get_imports_exports(self, path: str) -> dict[str, Any]:
        logger.debug("Ghidra get_imports_exports: %s", path)
        try:
            result = await self._run_ghidra_script("imports-exports", path)
            logger.debug("Ghidra get_imports_exports OK: %s", path)
            return result
        except AnalysisError:
            raise
        except Exception as exc:
            logger.error(
                "Ghidra get_imports_exports error: %s\n%s",
                path, traceback.format_exc(),
            )
            raise AnalysisError(str(exc)) from exc

    # ── extract_strings ───────────────────────────────────────────────────

    async def extract_strings(
        self, path: str, min_length: int = 5
    ) -> dict[str, Any]:
        logger.debug(
            "Ghidra extract_strings: %s (min_length=%d)", path, min_length
        )
        try:
            env_extra = {"GHIDRA_MIN_LENGTH": str(min_length)}
            result = await self._run_ghidra_script(
                "strings", path, env_extra=env_extra
            )
            logger.debug("Ghidra extract_strings OK: %s", path)
            return result
        except AnalysisError:
            raise
        except Exception as exc:
            logger.error(
                "Ghidra extract_strings error: %s\n%s",
                path, traceback.format_exc(),
            )
            raise AnalysisError(str(exc)) from exc

    # ── disassemble_function ──────────────────────────────────────────────

    async def disassemble_function(
        self,
        path: str,
        section_name: str,
        offset: int,
        size: int = 256,
    ) -> dict[str, Any]:
        logger.debug(
            "Ghidra disassemble_function: %s section=%s offset=%d size=%d",
            path, section_name, offset, size,
        )
        try:
            env_extra = {
                "GHIDRA_SECTION_NAME": section_name,
                "GHIDRA_OFFSET": str(offset),
                "GHIDRA_SIZE": str(size),
            }
            result = await self._run_ghidra_script(
                "disassembly", path, env_extra=env_extra
            )
            logger.debug(
                "Ghidra disassemble_function OK: %s (%d instructions)",
                path, len(result.get("instructions", [])),
            )
            return result
        except AnalysisError:
            raise
        except Exception as exc:
            logger.error(
                "Ghidra disassemble_function error: %s\n%s",
                path, traceback.format_exc(),
            )
            raise AnalysisError(str(exc)) from exc

    # ── get_file_info ─────────────────────────────────────────────────────

    async def get_file_info(self, path: str) -> dict[str, Any]:
        logger.debug("Ghidra get_file_info: %s", path)
        try:
            result = await self._run_ghidra_script("file-info", path)
            logger.debug("Ghidra get_file_info OK: %s", path)
            return result
        except AnalysisError:
            raise
        except Exception as exc:
            logger.error(
                "Ghidra get_file_info error: %s\n%s",
                path, traceback.format_exc(),
            )
            raise AnalysisError(str(exc)) from exc
