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
