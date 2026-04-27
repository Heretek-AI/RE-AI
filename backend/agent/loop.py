"""Agent loop engine — orchestrates LLM streaming calls with tool execution.

``AgentLoopSession`` holds per-connection conversation history and
manages the streaming interaction loop.  ``process_message()`` yields
structured events for the WebSocket handler to forward to the client.

Event types yielded by ``process_message``:

- ``agent:delta`` — streaming text content (``content`` key)
- ``agent:tool_call`` — LLM requested a tool invocation (``id``, ``name``, ``arguments``)
- ``agent:tool_result`` — result of a tool call (``id``, ``name``, ``result``)
- ``agent:error`` — an error occurred (``code``, ``message``)
- ``agent:done`` — processing complete (no payload)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, Optional

from backend.agent.provider import BaseProvider
from backend.agent.tools import (
    MAX_TOOL_CALLS_PER_TURN,
    execute_tool_call,
    get_tool_schemas,
)
from backend.engine.planning import PlanningEngine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = """You are RE-AI, an AI assistant specialized in reverse engineering, binary analysis, and software research.

You have access to the following tools:

{tool_descriptions}

Use tools when appropriate to accomplish tasks. When you run a shell command, wait for the result before deciding next steps.

When creating or updating kanban tasks, use the create_task/update_task_status tools. Tasks track work items in the project planning board.

Keep responses concise and actionable. If a tool returns an error, report it clearly and suggest alternatives."""


def _build_system_prompt() -> str:
    """Construct the system prompt from available tool definitions.

    Combines static tool schemas with dynamic registry tool definitions
    and appends CLI tool descriptions so the agent knows which external
    CLI utilities are available.
    """
    tool_lines: list[str] = []
    for tool_schema in get_tool_schemas():
        fn = tool_schema["function"]
        name = fn["name"]
        desc = fn.get("description", "")
        params = fn.get("parameters", {})
        props = params.get("properties", {})
        required = params.get("required", [])

        tool_lines.append(f"  - {name}: {desc}")
        for pname, pdef in props.items():
            req = " (required)" if pname in required else ""
            tool_lines.append(f"      - {pname}: {pdef.get('description', '')}{req}")

    # Append CLI descriptions from the registry
    try:
        from backend.registry.registry import ToolRegistry  # lazy: avoid circular import

        registry = ToolRegistry.get_instance()
        cli_text = registry.get_cli_descriptions()
        if cli_text:
            tool_lines.append("")
            tool_lines.append(cli_text)
    except Exception:
        logger.debug("ToolRegistry not available, skipping CLI descriptions")

    return DEFAULT_SYSTEM_PROMPT.format(tool_descriptions="\n".join(tool_lines))


# ---------------------------------------------------------------------------
# AgentLoopSession
# ---------------------------------------------------------------------------


class AgentLoopSession:
    """Per-connection agent session.

    Maintains conversation history and orchestrates the streaming
    interaction loop: LLM response → tool execution → LLM response →
    … up to *max_tool_calls* rounds, then final answer.

    Parameters
    ----------
    provider:
        AI provider instance (OpenAI, Anthropic, or Ollama).
    engine:
        The shared planning engine for kanban CRUD access.
    system_prompt:
        Optional override for the default system prompt.
    """

    def __init__(
        self,
        provider: BaseProvider,
        engine: PlanningEngine,
        system_prompt: Optional[str] = None,
    ) -> None:
        self._provider = provider
        self._engine = engine
        self._system_prompt = system_prompt if system_prompt is not None else _build_system_prompt()
        self._messages: list[dict[str, Any]] = []
        self._tool_schemas = get_tool_schemas()

    # -- Public API ------------------------------------------------------------

    @property
    def messages(self) -> list[dict[str, Any]]:
        """Read-only access to the conversation history."""
        return list(self._messages)

    async def process_message(self, user_message: str) -> AsyncIterator[dict[str, Any]]:
        """Process a user message and yield streaming events.

        Parameters
        ----------
        user_message:
            The user's text input.

        Yields
        ------
        dict
            Streaming event dicts:
            ``{"type": "agent:delta", "content": "..."}``,
            ``{"type": "agent:tool_call", "id": "...", "name": "...", "arguments": {...}}``,
            ``{"type": "agent:tool_result", "id": "...", "name": "...", "result": "..."}``,
            ``{"type": "agent:error", "code": 0, "message": "..."}``,
            ``{"type": "agent:done"}``.
        """
        self._messages.append({"role": "user", "content": user_message})

        tool_call_count = 0
        stream_exhausted = False
        caught_error = False

        while tool_call_count < MAX_TOOL_CALLS_PER_TURN:
            try:
                full_response = ""
                pending_tool_calls: list[dict[str, Any]] = []
                stream_exhausted = False
                caught_error = False

                async for event in self._provider.chat_stream(
                    messages=self._messages,
                    system_prompt=self._system_prompt,
                    tools=self._tool_schemas,
                ):
                    event_type = event["type"]

                    if event_type == "delta":
                        content = event.get("content", "")
                        full_response += content
                        yield {"type": "agent:delta", "content": content}

                    elif event_type == "tool_call":
                        pending_tool_calls.append(event)
                        yield {
                            "type": "agent:tool_call",
                            "id": event.get("id", ""),
                            "name": event.get("name", ""),
                            "arguments": event.get("arguments", {}),
                        }

                    elif event_type == "done":
                        stream_exhausted = True

                    elif event_type == "error":
                        caught_error = True
                        yield {
                            "type": "agent:error",
                            "code": event.get("code", 0),
                            "message": event.get("message", "Unknown error"),
                        }

                # Append assistant response text to conversation history
                if full_response:
                    self._messages.append({
                        "role": "assistant",
                        "content": full_response,
                    })

                # If provider errored, do not continue tool loop
                if caught_error:
                    yield {"type": "agent:done"}
                    return

                # Execute any pending tool calls
                if pending_tool_calls:
                    for tc in pending_tool_calls:
                        tool_name = tc.get("name", "")
                        tool_args = tc.get("arguments", {})
                        tc_id = tc.get("id", "")

                        try:
                            result = await execute_tool_call(
                                tool_name, tool_args, self._engine
                            )
                        except Exception as exc:
                            result = f"ERROR: {exc}"
                            logger.exception("Tool execution exception in agent loop")

                        # Append tool result to conversation history so the
                        # LLM sees it on the next cycle
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": result,
                        })

                        yield {
                            "type": "agent:tool_result",
                            "id": tc_id,
                            "name": tool_name,
                            "result": result,
                        }

                    tool_call_count += len(pending_tool_calls)
                    continue  # Another cycle — LLM sees tool results

                # Stream exhausted with no tool calls and no errors — final answer
                if stream_exhausted:
                    yield {"type": "agent:done"}
                    return

                # Fallback: should not normally reach here
                yield {"type": "agent:done"}
                return

            except Exception as exc:
                logger.exception("Agent loop error")
                yield {
                    "type": "agent:error",
                    "code": 0,
                    "message": f"Agent loop error: {exc}",
                }
                yield {"type": "agent:done"}
                return

        # Max tool calls reached without a final answer
        warning = (
            f"I've reached the maximum of {MAX_TOOL_CALLS_PER_TURN} "
            "tool calls for this message. "
            "Please let me know if you'd like me to continue."
        )
        self._messages.append({"role": "assistant", "content": warning})
        yield {
            "type": "agent:error",
            "code": 0,
            "message": (
                f"Reached maximum of {MAX_TOOL_CALLS_PER_TURN} "
                "tool calls per message."
            ),
        }
        yield {"type": "agent:done"}
