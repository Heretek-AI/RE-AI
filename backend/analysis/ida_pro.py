"""IDA Pro analysis backend using headless subprocess calls.

Wraps headless ``idat64`` / ``idal64`` invocations, launching
IDAPython scripts as subprocesses and returning their JSON output.

Parameters are passed to the scripts via environment variables
(see the ida_scripts package docstring for details).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import traceback
from pathlib import Path
from typing import Any

import anyio

from backend.analysis.base import AbstractAnalysisBackend, AnalysisError

logger = logging.getLogger("backend.analysis.ida_pro")

# Default timeout for IDA Pro headless scripts (seconds).
_IDA_TIMEOUT: int = 300


# ═══════════════════════════════════════════════════════════════════════════
# IdaProBackend
# ═══════════════════════════════════════════════════════════════════════════


class IdaProBackend(AbstractAnalysisBackend):
    """Analysis backend that delegates to headless IDA Pro (idat64 / idal64).

    Each abstract method runs the corresponding IDAPython script from
    ``backend/analysis/ida_scripts/`` in a headless IDA subprocess.

    The IDA binary path is read from ``config["tool_configs"]["ida_pro"]``.
    If the path is ``None`` (not configured), all five analysis methods
    raise :class:`AnalysisError` with a descriptive message.
    """

    # ── Constructor ──────────────────────────────────────────────────────

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__()
        config = config or {}
        tool_configs = config.get("tool_configs", {}) or {}
        self._ida_path: str | None = tool_configs.get("ida_pro")
        self._scripts_dir: Path = (
            Path(__file__).resolve().parent / "ida_scripts"
        )

    # ── Internal: headless subprocess runner ─────────────────────────────

    async def _run_headless(
        self,
        script_name: str,
        binary_path: str,
        env_extra: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run an IDAPython script in headless IDA Pro.

        Parameters
        ----------
        script_name:
            Filename of the script in ``ida_scripts/`` (e.g.
            ``"analyze_pe_structure.py"``).
        binary_path:
            Absolute path to the PE/DLL to analyse.
        env_extra:
            Optional extra environment variables to pass to the script.

        Returns
        -------
        dict[str, Any]
            Parsed JSON output written by the script.

        Raises
        ------
        AnalysisError
            If IDA is not configured, the subprocess times out, the
            script's output file is missing, or any other error occurs.
        """
        if not self._ida_path:
            raise AnalysisError(
                "IDA Pro is not configured — set tool_configs.ida_pro"
            )

        script = self._scripts_dir / script_name
        output_path = binary_path + ".ida_temp.json"

        # Build environment
        full_env = os.environ.copy()
        full_env["IDA_ANALYSIS_BIN_PATH"] = binary_path
        full_env["IDA_OUTPUT_PATH"] = output_path
        if env_extra:
            full_env.update(env_extra)

        def _run_sync() -> subprocess.CompletedProcess:
            return subprocess.run(
                [self._ida_path, "-A", f"-S{script}", binary_path],
                env=full_env,
                timeout=_IDA_TIMEOUT,
                capture_output=True,
            )

        try:
            proc = await anyio.to_thread.run_sync(_run_sync)
        except subprocess.TimeoutExpired:
            raise AnalysisError(
                f"IDA Pro timeout ({_IDA_TIMEOUT}s) for {script_name} "
                f"on {binary_path}"
            )
        except FileNotFoundError:
            raise AnalysisError(
                f"IDA Pro binary not found: {self._ida_path}"
            )
        except OSError as exc:
            raise AnalysisError(
                f"IDA Pro subprocess error for {script_name}: {exc}"
            )

        # Check return code
        if proc.returncode != 0:
            stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
            raise AnalysisError(
                f"IDA Pro script {script_name} exited with code "
                f"{proc.returncode}:\n{stderr[:2000]}"
            )

        # Read output file
        if not os.path.exists(output_path):
            raise AnalysisError(
                f"IDA Pro script {script_name} did not produce output at "
                f"{output_path}"
            )

        try:
            with open(output_path, "r", encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            raise AnalysisError(
                f"Failed to read/parse IDA output {output_path}: {exc}"
            )
        finally:
            # Best-effort cleanup of temp file
            try:
                os.remove(output_path)
            except OSError:
                pass

        return data

    # ═══════════════════════════════════════════════════════════════════════
    # Abstract method implementations
    # ═══════════════════════════════════════════════════════════════════════

    # ── analyze_pe_structure ──────────────────────────────────────────────

    async def analyze_pe_structure(self, path: str) -> dict[str, Any]:
        logger.debug("IdaPro analyze_pe_structure: %s", path)
        try:
            result = await self._run_headless("analyze_pe_structure.py", path)
            logger.debug("IdaPro analyze_pe_structure OK: %s", path)
            return result
        except AnalysisError:
            raise
        except Exception as exc:
            logger.error(
                "IdaPro analyze_pe_structure error: %s\n%s",
                path, traceback.format_exc(),
            )
            raise AnalysisError(str(exc)) from exc

    # ── get_imports_exports ───────────────────────────────────────────────

    async def get_imports_exports(self, path: str) -> dict[str, Any]:
        logger.debug("IdaPro get_imports_exports: %s", path)
        try:
            result = await self._run_headless(
                "get_imports_exports.py", path
            )
            logger.debug("IdaPro get_imports_exports OK: %s", path)
            return result
        except AnalysisError:
            raise
        except Exception as exc:
            logger.error(
                "IdaPro get_imports_exports error: %s\n%s",
                path, traceback.format_exc(),
            )
            raise AnalysisError(str(exc)) from exc

    # ── extract_strings ───────────────────────────────────────────────────

    async def extract_strings(
        self, path: str, min_length: int = 5
    ) -> dict[str, Any]:
        logger.debug("IdaPro extract_strings: %s (min_length=%d)", path, min_length)
        try:
            env_extra = {"IDA_MIN_LENGTH": str(min_length)}
            result = await self._run_headless(
                "extract_strings.py", path, env_extra=env_extra
            )
            logger.debug("IdaPro extract_strings OK: %s", path)
            return result
        except AnalysisError:
            raise
        except Exception as exc:
            logger.error(
                "IdaPro extract_strings error: %s\n%s",
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
            "IdaPro disassemble_function: %s section=%s offset=%d size=%d",
            path, section_name, offset, size,
        )
        try:
            env_extra = {
                "IDA_SECTION_NAME": section_name,
                "IDA_OFFSET": str(offset),
                "IDA_SIZE": str(size),
            }
            result = await self._run_headless(
                "disassemble_function.py", path, env_extra=env_extra
            )
            logger.debug(
                "IdaPro disassemble_function OK: %s (%d instructions)",
                path, len(result.get("instructions", [])),
            )
            return result
        except AnalysisError:
            raise
        except Exception as exc:
            logger.error(
                "IdaPro disassemble_function error: %s\n%s",
                path, traceback.format_exc(),
            )
            raise AnalysisError(str(exc)) from exc

    # ── get_file_info ─────────────────────────────────────────────────────

    async def get_file_info(self, path: str) -> dict[str, Any]:
        logger.debug("IdaPro get_file_info: %s", path)
        try:
            result = await self._run_headless("get_file_info.py", path)
            logger.debug("IdaPro get_file_info OK: %s", path)
            return result
        except AnalysisError:
            raise
        except Exception as exc:
            logger.error(
                "IdaPro get_file_info error: %s\n%s",
                path, traceback.format_exc(),
            )
            raise AnalysisError(str(exc)) from exc
