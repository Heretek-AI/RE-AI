"""RE tools detection API.

Scans the local system for known reverse-engineering and binary-analysis
tools via ``shutil.which()``, ``PATH`` scanning, Windows Registry
(``winreg``), and common install paths.

Endpoints
---------
- GET  /api/tools/detect    — Scan for installed RE tools; returns per-tool status
- POST /api/tools/install   — Placeholder: returns an install URL / guidance for the requested tool
"""

import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

# Common install roots — Windows-centric but portable fallbacks work on
# Linux / macOS too.
_PROGRAM_FILES = Path(os.environ.get("ProgramFiles", "C:\\Program Files"))
_PROGRAM_FILES_X86 = Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"))
_LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", "")) or Path.home() / "AppData" / "Local"
_APPDATA = Path(os.environ.get("APPDATA", "")) or Path.home() / "AppData" / "Roaming"
_USER_HOME = Path.home()


@dataclass
class ToolDef:
    """Definition of a RE tool to detect."""

    id: str                               # Stable key returned in the API response
    display_name: str                      # Human-readable name
    exe_names: tuple[str, ...]             # Executable names to try via PATH / shutil
    registry_keys: list[str] = field(default_factory=list)  # ``winreg`` key paths to try
    common_paths: list[str] = field(default_factory=list)   # Common install directory patterns
    install_url: str = ""                  # Download / info URL


TOOLS: list[ToolDef] = [
    ToolDef(
        id="ida_pro",
        display_name="IDA Pro",
        exe_names=("idat64.exe", "idat.exe"),
        registry_keys=[
            r"SOFTWARE\Hex-Rays\IDA",
            r"SOFTWARE\Wow6432Node\Hex-Rays\IDA",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "IDA Pro"),
            str(_PROGRAM_FILES / "IDA" / "IDA Pro"),
        ],
        install_url="https://hex-rays.com/ida-pro/",
    ),
    ToolDef(
        id="x64dbg",
        display_name="x64dbg",
        exe_names=("x64dbg.exe", "x32dbg.exe", "x96dbg.exe"),
        registry_keys=[
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\x64dbg.exe",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "x64dbg"),
            str(_PROGRAM_FILES / "x64dbg" / "release"),
            str(_LOCAL_APPDATA / "x64dbg"),
        ],
        install_url="https://x64dbg.com/",
    ),
    ToolDef(
        id="ghidra",
        display_name="Ghidra",
        exe_names=("ghidraRun.bat", "ghidraRun", "analyzeHeadless.bat", "analyzeHeadless"),
        registry_keys=[
            r"SOFTWARE\Ghidra",
            r"SOFTWARE\Wow6432Node\Ghidra",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "ghidra"),
            str(_PROGRAM_FILES / "Ghidra"),
            str(_USER_HOME / "ghidra"),
        ],
        install_url="https://ghidra-sre.org/",
    ),
    ToolDef(
        id="cheat_engine",
        display_name="Cheat Engine",
        exe_names=("Cheat Engine.exe", "CheatEngine.exe", "cheatengine-i386.exe"),
        registry_keys=[
            r"SOFTWARE\Cheat Engine",
            r"SOFTWARE\Wow6432Node\Cheat Engine",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "Cheat Engine"),
            str(_PROGRAM_FILES_X86 / "Cheat Engine"),
        ],
        install_url="https://cheatengine.org/",
    ),
    ToolDef(
        id="dnspy",
        display_name="dnSpy",
        exe_names=("dnSpy.exe", "dnspy.exe"),
        registry_keys=[
            r"SOFTWARE\dnSpy",
            r"SOFTWARE\Wow6432Node\dnSpy",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "dnSpy"),
            str(_PROGRAM_FILES_X86 / "dnSpy"),
            str(_LOCAL_APPDATA / "dnSpy"),
        ],
        install_url="https://github.com/dnSpy/dnSpy",
    ),
    ToolDef(
        id="hxd",
        display_name="HxD",
        exe_names=("HxD.exe", "hxd.exe"),
        registry_keys=[
            r"SOFTWARE\Mael Horz\HxD",
            r"SOFTWARE\Wow6432Node\Mael Horz\HxD",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "HxD"),
            str(_PROGRAM_FILES_X86 / "HxD"),
        ],
        install_url="https://mh-nexus.de/en/hxd/",
    ),
    ToolDef(
        id="detect_it_easy",
        display_name="Detect It Easy (DIE)",
        exe_names=("die.exe", "diec.exe", "diel.exe"),
        registry_keys=[
            r"SOFTWARE\Detect It Easy",
            r"SOFTWARE\Wow6432Node\Detect It Easy",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "Detect It Easy"),
            str(_PROGRAM_FILES_X86 / "Detect It Easy"),
        ],
        install_url="https://github.com/horsicq/Detect-It-Easy",
    ),
    ToolDef(
        id="pe_bear",
        display_name="PE-bear",
        exe_names=("PE-bear.exe", "pe-bear.exe", "pebear.exe"),
        registry_keys=[
            r"SOFTWARE\PE-bear",
            r"SOFTWARE\Wow6432Node\PE-bear",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "PE-bear"),
            str(_PROGRAM_FILES_X86 / "PE-bear"),
        ],
        install_url="https://github.com/hasherezade/pe-bear",
    ),
    ToolDef(
        id="process_hacker",
        display_name="Process Hacker",
        exe_names=("ProcessHacker.exe", "processhacker.exe"),
        registry_keys=[
            r"SOFTWARE\Process Hacker",
            r"SOFTWARE\Wow6432Node\Process Hacker",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "Process Hacker"),
            str(_PROGRAM_FILES_X86 / "Process Hacker"),
        ],
        install_url="https://processhacker.sourceforge.io/",
    ),
    ToolDef(
        id="process_monitor",
        display_name="Process Monitor",
        exe_names=("procmon64.exe", "procmon.exe"),
        registry_keys=[
            r"SOFTWARE\Sysinternals\Process Monitor",
            r"SOFTWARE\Wow6432Node\Sysinternals\Process Monitor",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "Sysinternals"),
            str(_PROGRAM_FILES / "Sysinternals Suite"),
        ],
        install_url="https://learn.microsoft.com/en-us/sysinternals/downloads/procmon",
    ),
    ToolDef(
        id="imhex",
        display_name="ImHex",
        exe_names=("imhex.exe", "ImHex.exe"),
        registry_keys=[
            r"SOFTWARE\ImHex",
            r"SOFTWARE\Wow6432Node\ImHex",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "ImHex"),
            str(_LOCAL_APPDATA / "imhex"),
        ],
        install_url="https://imhex.werwolv.net/",
    ),
    ToolDef(
        id="rizin",
        display_name="Rizin / Cutter",
        exe_names=("rizin.exe", "cutter.exe"),
        registry_keys=[
            r"SOFTWARE\Rizin",
            r"SOFTWARE\Cutter",
            r"SOFTWARE\Wow6432Node\Rizin",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "Rizin"),
            str(_PROGRAM_FILES / "Cutter"),
            str(_LOCAL_APPDATA / "rizin"),
        ],
        install_url="https://rizin.re/",
    ),
    ToolDef(
        id="binary_ninja",
        display_name="Binary Ninja",
        exe_names=("binaryninja.exe", "BinaryNinja.exe", "bncli.exe"),
        registry_keys=[
            r"SOFTWARE\Vector35\Binary Ninja",
            r"SOFTWARE\Wow6432Node\Vector35\Binary Ninja",
        ],
        common_paths=[
            str(_PROGRAM_FILES / "Binary Ninja"),
            str(_LOCAL_APPDATA / "binaryninja"),
        ],
        install_url="https://binary.ninja/",
    ),
]

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

# Compiled regex to strip ANSI / shell colour escape sequences from subprocess output
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _try_shutil(exe_names: tuple[str, ...]) -> Optional[str]:
    """Try each *exe_names* via ``shutil.which()`` and return the first match."""
    for name in exe_names:
        try:
            path = shutil.which(name)
            if path:
                return path
        except PermissionError:
            logger.debug("Permission error checking PATH for %s", name)
        except OSError:
            logger.debug("OS error checking PATH for %s", name)
    return None


def _try_winreg(keys: list[str]) -> Optional[str]:
    """Query Windows Registry for an install path under *keys*.

    Tries ``InstallLocation`` and ``InstallDir`` values first, then falls
    back to the default value.  Returns ``None`` on any error (key missing,
    permission denied, etc.).
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None

    value_names = ("InstallLocation", "InstallDir", "")

    for key_path in keys:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                for value_name in value_names:
                    try:
                        install_dir = winreg.QueryValueEx(key, value_name)[0]
                        if install_dir and Path(install_dir).is_dir():
                            return install_dir
                    except FileNotFoundError:
                        continue
        except (FileNotFoundError, PermissionError, OSError):
            logger.debug("Registry key not accessible: %s", key_path)

    return None


def _try_common_paths(paths: list[str], exe_names: tuple[str, ...]) -> Optional[str]:
    """Scan *paths* for any *exe_names* and return the first match."""
    for base in paths:
        base_path = Path(base)
        if not base_path.is_dir():
            continue
        for exe in exe_names:
            candidate = base_path / exe
            try:
                if candidate.is_file():
                    return str(candidate)
            except PermissionError:
                logger.debug("Permission error checking %s", candidate)
            except OSError:
                logger.debug("OS error checking %s", candidate)
    return None


def _detect_one(tool: ToolDef) -> dict[str, Any]:
    """Run all detection strategies for a single *tool*.

    Returns a dict with keys ``{id, display_name, detected, path, method}``.
    Never raises — all errors are caught and logged.
    """
    result: dict[str, Any] = {
        "id": tool.id,
        "display_name": tool.display_name,
        "detected": False,
        "path": None,
        "method": None,
    }

    # 1. PATH / shutil
    path = _try_shutil(tool.exe_names)
    if path:
        result["detected"] = True
        result["path"] = path
        result["method"] = "path"
        return result

    # 2. Windows Registry
    path = _try_winreg(tool.registry_keys)
    if path:
        # Resolve actual exe in the install directory
        for exe in tool.exe_names:
            candidate = Path(path) / exe
            if candidate.is_file():
                result["detected"] = True
                result["path"] = str(candidate)
                result["method"] = "registry"
                return result
        # Directory exists but we couldn't find a known exe — mark detected
        result["detected"] = True
        result["path"] = path
        result["method"] = "registry"
        return result

    # 3. Common install paths
    path = _try_common_paths(tool.common_paths, tool.exe_names)
    if path:
        result["detected"] = True
        result["path"] = path
        result["method"] = "common_path"
        return result

    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/detect")
async def detect_tools():
    """Scan the system for installed RE tools.

    For each known tool, a 3‑strategy cascade is applied:

    1. ``shutil.which()`` / ``PATH`` search
    2. Windows Registry (``HKLM\\SOFTWARE\\{vendor}\\{product}``)
    3. Common install directory patterns

    Returns a dict mapping tool ``id`` → detection result
    (``{id, display_name, detected, path, method}``).

    The endpoint never raises on permission errors — inaccessible paths or
    registry keys are silently skipped.
    """
    results: dict[str, Any] = {}

    for tool in TOOLS:
        try:
            results[tool.id] = _detect_one(tool)
        except Exception:
            logger.exception("Unexpected error detecting tool '%s'", tool.id)
            results[tool.id] = {
                "id": tool.id,
                "display_name": tool.display_name,
                "detected": False,
                "path": None,
                "method": "error",
            }

    return results


# Pydantic models for the install endpoint


from pydantic import BaseModel


class InstallRequest(BaseModel):
    """Request to get install guidance for a tool."""

    tool_id: str


@router.post("/install")
async def install_tool_placeholder(payload: InstallRequest):
    """(Placeholder) Return installation guidance for the requested tool.

    This endpoint does **not** perform an actual install — it returns the
    download URL and a human-readable guidance string.
    """
    for tool in TOOLS:
        if tool.id == payload.tool_id:
            return {
                "tool_id": tool.id,
                "display_name": tool.display_name,
                "install_url": tool.install_url,
                "guidance": (
                    f"Download {tool.display_name} from {tool.install_url} "
                    "and install it manually. A future version may support "
                    "automated installation."
                ),
            }

    return {
        "tool_id": payload.tool_id,
        "display_name": payload.tool_id,
        "install_url": None,
        "guidance": f"Unknown tool '{payload.tool_id}'. No install guidance available.",
    }
