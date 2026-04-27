"""Agent tool definitions — shell execution, kanban CRUD, and status queries.

Each tool is defined as a ``ToolDef`` dataclass with an ``async_execute``
callable.  ``get_tool_schemas()`` produces OpenAI-compatible function
definitions.  ``execute_tool_call(name, args, engine)`` dispatches to the
correct implementation by name.

Tools
-----
- ``shell`` – Run a shell command via ``asyncio.create_subprocess_shell``
- ``create_task`` – Create a new task under a given slice
- ``update_task_status`` – Transition a task to a new status
- ``get_task_status`` – Read a task's current status
- ``get_slice_tasks`` – List all tasks in a slice
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from backend.analysis import AnalysisError, get_analysis_backend
from backend.engine.models import TaskCreate, TaskResponse
from backend.engine.planning import PlanningEngine
from backend.rag.base import BaseVectorStore

logger = logging.getLogger(__name__)

# Default working directory for shell commands — project root.
DEFAULT_CWD: str = os.getcwd()

# Maximum tool call rounds per user message.
MAX_TOOL_CALLS_PER_TURN: int = 10

# ---------------------------------------------------------------------------
# ToolDef
# ---------------------------------------------------------------------------


@dataclass
class ToolDef:
    """Definition of an agent-callable tool.

    Attributes
    ----------
    name:
        Unique tool name (used by the LLM to invoke this tool).
    description:
        Human-readable description — passed as the function description
        in the tool schema.
    input_schema:
        JSON Schema dict describing the expected arguments.
    async_execute:
        Async callable ``(args: dict, engine: PlanningEngine) -> str``
        that performs the operation and returns a human-readable result
        string.
    """

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    async_execute: Optional[callable] = None  # type: ignore[type-arg]

    def to_openai_schema(self) -> dict[str, Any]:
        """Return an OpenAI-compatible tool definition dict."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def _exec_shell(args: dict[str, Any], engine: PlanningEngine) -> str:
    """Execute a shell command with timeout and output truncation."""
    command: str = args.get("command", "")
    cwd: str = args.get("cwd", DEFAULT_CWD)
    timeout: int = args.get("timeout", 30)

    if not command.strip():
        return "ERROR: No command provided."

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"ERROR: Command timed out after {timeout}s."

        output = ""
        if stdout:
            output += stdout.decode("utf-8", errors="replace")
        if stderr:
            if output:
                output += "\n--- STDERR ---\n"
            output += stderr.decode("utf-8", errors="replace")

        # Truncate to 4000 characters
        if len(output) > 4000:
            output = output[:4000] + f"\n... (truncated, {len(output)} total chars)"

        return (
            f"EXIT_CODE: {proc.returncode}\n"
            f"CWD: {cwd}\n"
            f"{output}"
        )
    except FileNotFoundError:
        return f"ERROR: Shell not found (cwd={cwd})"
    except PermissionError:
        return "ERROR: Permission denied when running shell command."
    except Exception as exc:
        logger.exception("Shell tool error")
        return f"ERROR: {exc}"


async def _exec_create_task(args: dict[str, Any], engine: PlanningEngine) -> str:
    """Create a new task under a slice."""
    slice_id: int = args.get("slice_id", 0)
    title: str = args.get("title", "Untitled task")
    description: str = args.get("description", "")

    task = await engine.create_task(slice_id, TaskCreate(title=title, description=description))
    if task is None:
        return f"ERROR: Slice {slice_id} not found."
    return (
        f"Created task {task.id} '{task.title}' under slice {slice_id} "
        f"(status: {task.status})."
    )


async def _exec_update_task_status(args: dict[str, Any], engine: PlanningEngine) -> str:
    """Transition a task to a new status."""
    task_id: int = args.get("task_id", 0)
    status: str = args.get("status", "")

    try:
        task = await engine.update_task_status(task_id, status)
    except ValueError as exc:
        return f"ERROR: {exc}"
    if task is None:
        return f"ERROR: Task {task_id} not found."
    return f"Task {task_id} '{task.title}' status changed to '{task.status}'."


async def _exec_get_task_status(args: dict[str, Any], engine: PlanningEngine) -> str:
    """Read a task's current status."""
    task_id: int = args.get("task_id", 0)
    task = await engine.get_task(task_id)
    if task is None:
        return f"ERROR: Task {task_id} not found."
    return (
        f"Task {task.id}: '{task.title}' | "
        f"Status: {task.status} | "
        f"Slice: {task.slice_id} | "
        f"Updated: {task.updated_at.isoformat()}"
    )


async def _exec_get_slice_tasks(args: dict[str, Any], engine: PlanningEngine) -> str:
    """List all tasks in a slice."""
    slice_id: int = args.get("slice_id", 0)
    tasks = await engine.get_tasks_by_slice(slice_id)
    if not tasks:
        return f"Slice {slice_id} has no tasks."
    lines = [f"Slice {slice_id} tasks ({len(tasks)} total):"]
    for t in tasks:
        lines.append(f"  - [{t.status}] #{t.id} {t.title}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# RAG store — set by backend/main.py lifespan startup
# ---------------------------------------------------------------------------

_rag_store: Optional[BaseVectorStore] = None


def set_rag_store(store: Optional[BaseVectorStore]) -> None:
    """Set the global RAG vector store reference.

    Called from ``backend/main.py`` lifespan startup after the vector
    store is initialized.  Pass ``None`` to disable RAG capabilities.
    """
    global _rag_store
    _rag_store = store


async def _exec_rag_search(args: dict[str, Any], engine: PlanningEngine) -> str:
    """Search past analysis findings, tool results, and conversation context.

    Queries the vector database across the specified collections and
    returns formatted results.
    """
    if _rag_store is None:
        return (
            "ERROR: RAG vector store is not available "
            "(not configured or Chroma not installed)."
        )

    query: str = args.get("query", "")
    top_k: int = args.get("top_k", 5)
    collections: list[str] = args.get(
        "collections", ["tool_results", "conversation"]
    )

    if not query.strip():
        return "ERROR: No search query provided."

    all_results: list[dict[str, Any]] = []
    seen_texts: set[str] = set()

    for collection in collections:
        try:
            results = await _rag_store.search(collection, query, top_k)
        except Exception:
            logger.exception("RAG search error on collection %r", collection)
            continue

        for item in results:
            text = item.get("text", "")
            # Deduplicate across collections
            if text not in seen_texts:
                seen_texts.add(text)
                all_results.append(item)

    # Sort by score descending
    all_results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    all_results = all_results[:top_k]

    if not all_results:
        return f"No relevant findings found for '{query}'."

    lines = [f"## RAG Search Results: '{query}'", ""]
    for i, item in enumerate(all_results, 1):
        score = item.get("score", 0.0)
        text = item.get("text", "")
        metadata = item.get("metadata", {})
        source = metadata.get("role", metadata.get("tool_name", "unknown"))

        lines.append(f"### Result {i} (score: {score:.3f}, source: {source})")
        # Truncate text to avoid excessive response size
        display_text = text[:800] + ("..." if len(text) > 800 else "")
        lines.append(display_text)
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Analysis tool implementations
# ---------------------------------------------------------------------------


async def _exec_extract_pe_info(args: dict[str, Any], engine: PlanningEngine) -> str:
    """Extract PE header structure information from a PE/DLL file."""
    path: str = args.get("path", "")
    if not path:
        return "ERROR: No path provided."

    try:
        backend = get_analysis_backend({})
        result = await backend.analyze_pe_structure(path)
    except AnalysisError as exc:
        return f"ERROR: {exc}"
    except FileNotFoundError as exc:
        return f"ERROR: File not found: {exc}"
    except Exception as exc:
        logger.exception("extract_pe_info error")
        return f"ERROR: {exc}"

    lines = [
        f"## PE Structure: {path}",
        "",
        f"- **Machine type:** {result.get('machine_type', '?')}",
        f"- **Characteristics:** {result.get('characteristics', '?')}",
        f"- **Is DLL:** {result.get('is_dll', '?')}",
        f"- **Is EXE:** {result.get('is_exe', '?')}",
        f"- **Entry point:** {result.get('entry_point', '?')} (0x{result.get('entry_point', 0):x})",
        f"- **Image base:** 0x{result.get('image_base', 0):x}",
        f"- **Size of image:** {result.get('size_of_image', 0)} bytes",
        f"- **Imphash:** {result.get('imphash', 'N/A')}",
        "",
        "### Subsystems",
    ]
    subs = result.get("subsystems", [])
    for s in subs:
        lines.append(f"- {s}")
    lines.append("")
    lines.append("### Sections")
    lines.append("")
    lines.append("| Name | Virtual Address | Virtual Size | Raw Size | Characteristics |")
    lines.append("|------|-----------------|-------------|----------|----------------|")
    for sec in result.get("sections", []):
        lines.append(
            f"| {sec.get('name', '?')} | "
            f"0x{sec.get('virtual_address', 0):x} | "
            f"0x{sec.get('virtual_size', 0):x} | "
            f"{sec.get('size_of_raw_data', 0)} | "
            f"{sec.get('characteristics', '?')} |"
        )
    return "\n".join(lines)


async def _exec_list_imports_exports(args: dict[str, Any], engine: PlanningEngine) -> str:
    """List import and export tables of a PE/DLL file."""
    path: str = args.get("path", "")
    if not path:
        return "ERROR: No path provided."

    try:
        backend = get_analysis_backend({})
        result = await backend.get_imports_exports(path)
    except AnalysisError as exc:
        return f"ERROR: {exc}"
    except FileNotFoundError as exc:
        return f"ERROR: File not found: {exc}"
    except Exception as exc:
        logger.exception("list_imports_exports error")
        return f"ERROR: {exc}"

    lines = [f"## Imports & Exports: {path}", ""]

    imports = result.get("imports", [])
    if imports:
        lines.append(f"### Imports ({len(imports)} DLLs)")
        lines.append("")
        for dll_entry in imports:
            dll_name = dll_entry.get("dll", "?")
            funcs = dll_entry.get("imports", [])
            lines.append(f"**{dll_name}** ({len(funcs)} functions)")
            for f in funcs:
                fname = f.get("name", f"(ordinal {f.get('ordinal', '?')})")
                by_ord = " [by ordinal]" if f.get("import_by_ordinal") else ""
                lines.append(f"  - {fname}{by_ord}")
            lines.append("")
    else:
        lines.append("*No imports found.*")
        lines.append("")

    exports = result.get("exports", [])
    if exports:
        lines.append(f"### Exports ({len(exports)} symbols)")
        lines.append("")
        lines.append("| Name | Ordinal | Address |")
        lines.append("|------|---------|---------|")
        for exp in exports:
            ename = exp.get("name", f"(ordinal {exp.get('ordinal', '?')})")
            addr = exp.get("address", 0)
            lines.append(f"| {ename} | {exp.get('ordinal', '?')} | 0x{addr:x} |")
    else:
        lines.append("*No exports found.*")

    return "\n".join(lines)


async def _exec_extract_strings(args: dict[str, Any], engine: PlanningEngine) -> str:
    """Extract printable ASCII/Unicode strings from a PE/DLL file."""
    path: str = args.get("path", "")
    min_length: int = args.get("min_length", 5)
    max_results: int = args.get("max_results", 200)

    if not path:
        return "ERROR: No path provided."

    try:
        backend = get_analysis_backend({})
        result = await backend.extract_strings(path, min_length)
    except AnalysisError as exc:
        return f"ERROR: {exc}"
    except FileNotFoundError as exc:
        return f"ERROR: File not found: {exc}"
    except Exception as exc:
        logger.exception("extract_strings error")
        return f"ERROR: {exc}"

    strings_list = result.get("strings", [])
    total_count = result.get("total_count", 0)

    # Apply max_results cap here (the backend caps at 200 already, but honour the tool arg)
    display_list = strings_list[:max_results]

    lines = [
        f"## Strings: {path}",
        "",
        f"Total strings found: {total_count}",
        f"Displaying: {len(display_list)}",
        "",
        "| Offset | Type | String |",
        "|--------|------|--------|",
    ]
    for entry in display_list:
        offset = entry.get("offset", 0)
        text = entry.get("string", "")
        # Truncate very long strings for display
        if len(text) > 120:
            text = text[:120] + "..."
        s_type = "ASCII" if all(32 <= ord(c) < 127 for c in text) else "Unicode"
        lines.append(f"| 0x{offset:x} | {s_type} | {text} |")

    if total_count > len(display_list):
        lines.append("")
        lines.append(f"*{total_count - len(display_list)} more strings not shown (use max_results to increase limit).*")

    return "\n".join(lines)


async def _exec_disassemble_function(args: dict[str, Any], engine: PlanningEngine) -> str:
    """Disassemble a function from a PE/DLL file section."""
    path: str = args.get("path", "")
    section_name: str = args.get("section_name", "")
    offset: int = args.get("offset", 0)
    size: int = args.get("size", 256)

    if not path:
        return "ERROR: No path provided."
    if not section_name:
        return "ERROR: No section_name provided."

    try:
        backend = get_analysis_backend({})
        result = await backend.disassemble_function(path, section_name, offset, size)
    except AnalysisError as exc:
        return f"ERROR: {exc}"
    except FileNotFoundError as exc:
        return f"ERROR: File not found: {exc}"
    except Exception as exc:
        logger.exception("disassemble_function error")
        return f"ERROR: {exc}"

    lines = [
        f"## Disassembly: {path}",
        "",
        f"- **Architecture:** {result.get('architecture', '?')}",
        f"- **Mode:** {result.get('mode', '?')}",
        f"- **Section:** {result.get('section_name', '?')}",
        f"- **Offset:** 0x{result.get('offset', 0):x}",
        f"- **Bytes analyzed:** {result.get('bytes_count', 0)}",
        "",
        "### Instructions",
        "",
        "| Address | Bytes | Instruction |",
        "|---------|-------|-------------|",
    ]
    for insn in result.get("instructions", []):
        addr = insn.get("address", 0)
        raw_bytes = insn.get("bytes", "")
        mnemonic = insn.get("mnemonic", "")
        operands = insn.get("operands", "")
        if operands:
            instr_text = f"{mnemonic} {operands}"
        else:
            instr_text = mnemonic
        lines.append(f"| 0x{addr:x} | `{raw_bytes}` | {instr_text} |")

    if result.get("truncated"):
        lines.append("")
        lines.append("*Disassembly truncated (more than 500 instructions).*")

    return "\n".join(lines)


async def _exec_analyze_directory(args: dict[str, Any], engine: PlanningEngine) -> str:
    """Analyze all PE/DLL files in a directory."""
    directory: str = args.get("directory", "")
    if not directory:
        return "ERROR: No directory provided."
    if not os.path.isdir(directory):
        return f"ERROR: Directory not found: {directory}"

    backend = get_analysis_backend({})

    # Collect PE files
    pe_files: list[str] = []
    non_pe_files: list[str] = []
    try:
        for entry in os.listdir(directory):
            if entry.lower().endswith((".exe", ".dll")):
                pe_files.append(os.path.join(directory, entry))
            else:
                non_pe_files.append(os.path.join(directory, entry))
    except PermissionError:
        return f"ERROR: Permission denied reading directory: {directory}"
    except Exception as exc:
        return f"ERROR: {exc}"

    if not pe_files:
        skipped_note = f" ({len(non_pe_files)} non-PE files skipped)" if non_pe_files else ""
        return f"No PE files found in {directory}{skipped_note}."

    lines = [
        f"## Directory Analysis: {directory}",
        "",
        f"Found {len(pe_files)} PE file(s) in {directory}.",
    ]
    if non_pe_files:
        lines.append(f"({len(non_pe_files)} non-PE file(s) skipped.)")
        lines.append("")

    lines.append("")
    lines.append("| File | Size | Architecture | Type | Entry Point | Imphash |")
    lines.append("|------|------|--------------|------|-------------|---------|")

    for file_path in pe_files:
        try:
            info = await backend.get_file_info(file_path)
            structure = await backend.analyze_pe_structure(file_path)
            fname = os.path.basename(file_path)
            size = info.get("size_bytes", 0)
            arch = info.get("architecture", "?")
            ftype = "DLL" if info.get("is_dll") else "EXE" if info.get("is_exe") else "?"
            ep = structure.get("entry_point", 0)
            imphash = structure.get("imphash", "N/A") or "N/A"
            size_str = f"{size:,}" if size else "?"
            lines.append(f"| {fname} | {size_str} B | {arch} | {ftype} | 0x{ep:x} | {imphash} |")
        except AnalysisError:
            lines.append(f"| {os.path.basename(file_path)} | — | — | — | — | (parse error) |")
        except Exception as exc:
            logger.exception("analyze_directory error for %s", file_path)
            lines.append(f"| {os.path.basename(file_path)} | — | — | — | — | (error: {exc}) |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS: list[ToolDef] = [
    ToolDef(
        name="shell",
        description=(
            "Execute a shell command on the local filesystem. "
            "Returns exit code, stdout, and stderr. "
            "Output is truncated to 4000 characters. "
            "Use cwd to control the working directory."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (default: project root).",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30, max: 120).",
                    "default": 30,
                },
            },
            "required": ["command"],
        },
        async_execute=_exec_shell,
    ),
    ToolDef(
        name="create_task",
        description="Create a new task under the specified slice.",
        input_schema={
            "type": "object",
            "properties": {
                "slice_id": {
                    "type": "integer",
                    "description": "ID of the parent slice.",
                },
                "title": {
                    "type": "string",
                    "description": "Task title.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional task description.",
                },
            },
            "required": ["slice_id", "title"],
        },
        async_execute=_exec_create_task,
    ),
    ToolDef(
        name="update_task_status",
        description=(
            "Change the status of a task. "
            "Valid statuses: pending, in_progress, complete, errored."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "ID of the task to update.",
                },
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "complete", "errored"],
                    "description": "New status value.",
                },
            },
            "required": ["task_id", "status"],
        },
        async_execute=_exec_update_task_status,
    ),
    ToolDef(
        name="get_task_status",
        description="Get the current status and details of a task.",
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "ID of the task to inspect.",
                },
            },
            "required": ["task_id"],
        },
        async_execute=_exec_get_task_status,
    ),
    ToolDef(
        name="get_slice_tasks",
        description="List all tasks in a given slice with their statuses.",
        input_schema={
            "type": "object",
            "properties": {
                "slice_id": {
                    "type": "integer",
                    "description": "ID of the slice.",
                },
            },
            "required": ["slice_id"],
        },
        async_execute=_exec_get_slice_tasks,
    ),
    ToolDef(
        name="extract_pe_info",
        description=(
            "Extract PE header structure from a PE/DLL file. "
            "Returns machine type, characteristics, sections, entry point, "
            "image base, size, and imphash."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the PE or DLL file.",
                },
            },
            "required": ["path"],
        },
        async_execute=_exec_extract_pe_info,
    ),
    ToolDef(
        name="list_imports_exports",
        description=(
            "List imported and exported functions from a PE/DLL file. "
            "Returns import tables grouped by DLL and export symbols."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the PE or DLL file.",
                },
            },
            "required": ["path"],
        },
        async_execute=_exec_list_imports_exports,
    ),
    ToolDef(
        name="extract_strings",
        description=(
            "Extract printable ASCII and Unicode strings from a PE/DLL file. "
            "Returns a table of offsets, types, and string values."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the PE or DLL file.",
                },
                "min_length": {
                    "type": "integer",
                    "description": "Minimum string length (default: 5).",
                    "default": 5,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of strings to return (default: 200).",
                    "default": 200,
                },
            },
            "required": ["path"],
        },
        async_execute=_exec_extract_strings,
    ),
    ToolDef(
        name="disassemble_function",
        description=(
            "Disassemble code from a specific section of a PE/DLL file. "
            "Returns an instruction listing with addresses and raw bytes."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the PE or DLL file.",
                },
                "section_name": {
                    "type": "string",
                    "description": "Name of the section to disassemble (e.g. .text).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Byte offset within the section to start.",
                },
                "size": {
                    "type": "integer",
                    "description": "Number of bytes to disassemble (default: 256).",
                    "default": 256,
                },
            },
            "required": ["path", "section_name", "offset"],
        },
        async_execute=_exec_disassemble_function,
    ),
    ToolDef(
        name="analyze_directory",
        description=(
            "Analyze all PE/DLL files in a directory. "
            "Scans for *.exe and *.dll files and returns basic info for each: "
            "size, architecture, type (DLL/EXE), entry point, and imphash. "
            "Non-PE files are skipped with a note."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Path to the directory to scan.",
                },
            },
            "required": ["directory"],
        },
        async_execute=_exec_analyze_directory,
    ),
    ToolDef(
        name="rag_search",
        description=(
            "Search past analysis findings, tool results, and conversation "
            "context stored in the vector database. Use this when you need "
            "to recall what was previously discovered about a topic."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default: 5).",
                    "default": 5,
                },
                "collections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional: collections to search (default: "
                        "both tool_results and conversation)."
                    ),
                },
            },
            "required": ["query"],
        },
        async_execute=_exec_rag_search,
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_tool_schemas() -> list[dict[str, Any]]:
    """Return OpenAI-compatible tool definitions for all registered tools.

    Combines static tool definitions (shell, kanban CRUD) with dynamic
    registry tool definitions (``mcp_invoke``, skills, etc.).
    Each dict follows the ``tools`` parameter format for
    ``chat.completions.create``.
    """
    schemas = [t.to_openai_schema() for t in TOOLS]
    # Append registry-provided ToolDef schemas (mcp_invoke, skills, etc.)
    try:
        from backend.registry.registry import ToolRegistry  # lazy: avoid circular import

        registry = ToolRegistry.get_instance()
        for tool_def in registry.get_tool_defs():
            schemas.append(tool_def.to_openai_schema())
    except Exception:
        logger.debug("ToolRegistry not available, skipping registry schemas")
    return schemas


async def execute_tool_call(
    name: str,
    args: dict[str, Any],
    engine: PlanningEngine,
) -> str:
    """Execute a tool by name and return the result string.

    Parameters
    ----------
    name:
        Tool name (must match a ``ToolDef.name`` in the registry).
    args:
        Arguments dict matching the tool's ``input_schema``.
    engine:
        The shared ``PlanningEngine`` instance (passed to each tool's
        ``async_execute`` callable).

    Returns
    -------
    str
        Human-readable result or error message.  Errors are returned as
        strings starting with ``"ERROR:"`` — never raised.
    """
    for tool in TOOLS:
        if tool.name == name:
            if tool.async_execute is None:
                return f"ERROR: Tool '{name}' has no async_execute implementation."
            try:
                return await tool.async_execute(args, engine)
            except Exception as exc:
                logger.exception("Tool '%s' raised an exception", name)
                return f"ERROR: {name} failed: {exc}"

    # Fall through to registry for dynamically registered tools (mcp_invoke, etc.)
    try:
        from backend.registry.registry import ToolRegistry  # lazy: avoid circular import

        registry = ToolRegistry.get_instance()
        return await registry.exec_registered_tool(name, args, engine)
    except Exception as exc:
        logger.exception("Registry dispatch failed for '%s'", name)
        return f"ERROR: Unknown tool '{name}'."
