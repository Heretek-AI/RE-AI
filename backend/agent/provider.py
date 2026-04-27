"""Provider abstraction layer for AI chat completions.

Defines a common streaming interface across OpenAI, Anthropic, and Ollama
(compatible with any OpenAI-compatible local endpoint).

Usage::

    provider = get_provider({"ai_provider": "openai", "ai_api_key": "...", "ai_model": "gpt-4o"})
    async for event in provider.chat_stream(messages, system_prompt, tool_schemas):
        if event["type"] == "delta":
            print(event["content"], end="")
        elif event["type"] == "tool_call":
            print(f"Tool: {event['name']}({event['arguments']})")

Each yielded dict has a ``type`` key: ``"delta"``, ``"tool_call"``,
``"done"``, or ``"error"``.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base provider
# ---------------------------------------------------------------------------


class BaseProvider(ABC):
    """Abstract base class for AI chat providers.

    Subclasses must implement ``chat_stream``, yielding dicts with at
    least a ``type`` key.
    """

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a chat completion.

        Parameters
        ----------
        messages:
            Conversation history — each entry has ``role`` and ``content``.
        system_prompt:
            System-level instruction prepended to the conversation.
        tools:
            OpenAI-compatible tool/function definitions.

        Yields
        ------
        dict
            Event dicts with ``type`` in (``"delta"``, ``"tool_call"``,
            ``"done"``, ``"error"``).
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class OpenAIProvider(BaseProvider):
    """OpenAI chat completions via ``openai.AsyncOpenAI``."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: Optional[str] = None,
    ) -> None:
        import openai

        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.AsyncOpenAI(**kwargs)
        self._model = model

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        full_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": full_messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            import openai

            stream = await self._client.chat.completions.create(**kwargs)
        except openai.APIStatusError as exc:
            yield {"type": "error", "code": exc.status_code, "message": str(exc)}
            return
        except openai.APIConnectionError as exc:
            yield {"type": "error", "code": 0, "message": f"Connection error: {exc}"}
            return
        except openai.RateLimitError as exc:
            yield {"type": "error", "code": 429, "message": f"Rate limited: {exc}"}
            return

        tool_calls_in_progress: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            if not chunk.choices:
                # May be an empty usage chunk at the end — skip
                continue

            delta = chunk.choices[0].delta

            # Delta content
            if delta.content:
                yield {"type": "delta", "content": delta.content}

            # Tool calls (delta accumulates across chunks)
            if delta.tool_calls:
                for tc_chunk in delta.tool_calls:
                    idx = tc_chunk.index
                    if idx not in tool_calls_in_progress:
                        tool_calls_in_progress[idx] = {
                            "id": tc_chunk.id or "",
                            "name": tc_chunk.function.name if tc_chunk.function else "",
                            "arguments": tc_chunk.function.arguments if tc_chunk.function else "",
                        }
                    else:
                        entry = tool_calls_in_progress[idx]
                        if tc_chunk.id:
                            entry["id"] = tc_chunk.id
                        if tc_chunk.function:
                            if tc_chunk.function.name:
                                entry["name"] = tc_chunk.function.name
                            if tc_chunk.function.arguments:
                                entry["arguments"] += tc_chunk.function.arguments

            # Finish reason signals end-of-stream
            finish_reason = chunk.choices[0].finish_reason
            if finish_reason:
                # Flush accumulated tool calls
                for entry in tool_calls_in_progress.values():
                    try:
                        parsed_args = json.loads(entry["arguments"]) if entry["arguments"] else {}
                    except json.JSONDecodeError:
                        parsed_args = {}
                    yield {
                        "type": "tool_call",
                        "id": entry["id"],
                        "name": entry["name"],
                        "arguments": parsed_args,
                    }

                if finish_reason == "tool_calls":
                    pass  # Already yielded above
                elif finish_reason == "stop":
                    yield {"type": "done"}
                elif finish_reason == "length":
                    yield {
                        "type": "error",
                        "code": 0,
                        "message": "Response truncated due to max_tokens limit.",
                    }
                else:
                    yield {"type": "done"}
                return

        yield {"type": "done"}


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class AnthropicProvider(BaseProvider):
    """Anthropic chat completions via ``anthropic.AsyncAnthropic``.

    Maps Anthropic's ``tool_use`` content blocks to the common
    ``"tool_call"`` event format.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        base_url: Optional[str] = None,
    ) -> None:
        import anthropic

        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.AsyncAnthropic(**kwargs)
        self._model = model

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        # Convert OpenAI-format tool schemas to Anthropic format
        anthropic_tools = [_openai_tool_to_anthropic(t) for t in tools] if tools else []

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "system": system_prompt,
            "max_tokens": 4096,
            "stream": True,
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        try:
            import anthropic

            stream = await self._client.messages.create(**kwargs)
        except anthropic.APIStatusError as exc:
            yield {"type": "error", "code": exc.status_code, "message": str(exc)}
            return
        except anthropic.APIConnectionError as exc:
            yield {"type": "error", "code": 0, "message": f"Connection error: {exc}"}
            return
        except anthropic.RateLimitError as exc:
            yield {"type": "error", "code": 429, "message": f"Rate limited: {exc}"}
            return

        async for event in stream:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                yield {"type": "delta", "content": event.delta.text}
            elif event.type == "content_block_start" and event.content_block.type == "tool_use":
                # Start accumulating a tool call
                self._tool_acc: dict[str, Any] = {
                    "id": event.content_block.id,
                    "name": event.content_block.name,
                    "arguments": "",
                }
            elif event.type == "content_block_delta" and event.delta.type == "input_json_delta":
                if hasattr(self, "_tool_acc") and self._tool_acc is not None:
                    self._tool_acc["arguments"] += event.delta.partial_json
            elif event.type == "content_block_stop":
                if hasattr(self, "_tool_acc") and self._tool_acc is not None:
                    try:
                        parsed_args = json.loads(self._tool_acc["arguments"])
                    except (json.JSONDecodeError, TypeError):
                        parsed_args = {}
                    yield {
                        "type": "tool_call",
                        "id": self._tool_acc["id"],
                        "name": self._tool_acc["name"],
                        "arguments": parsed_args,
                    }
                    self._tool_acc = None
            elif event.type == "message_delta" and event.delta.stop_reason == "end_turn":
                yield {"type": "done"}
                return
            elif event.type == "message_stop":
                yield {"type": "done"}
                return

        yield {"type": "done"}


def _openai_tool_to_anthropic(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAI-format tool definition to Anthropic format."""
    return {
        "name": tool["function"]["name"],
        "description": tool["function"].get("description", ""),
        "input_schema": tool["function"]["parameters"],
    }


# ---------------------------------------------------------------------------
# Ollama (OpenAI-compatible API)
# ---------------------------------------------------------------------------


class OllamaProvider(BaseProvider):
    """Ollama chat via the ``/api/chat`` HTTP endpoint.

    Uses ``httpx`` for streaming POST requests.  Compatible with any
    OpenAI-compatible local endpoint (e.g., vLLM, llama.cpp server).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        full_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": full_messages,
            "stream": True,
        }

        # Ollama supports tool calling in newer versions
        if tools and self._model not in ("llama3.1:8b", "llama3.2"):
            # Convert OpenAI schema to Ollama format
            ollama_tools = []
            for t in tools:
                ollama_tools.append({
                    "type": "function",
                    "function": {
                        "name": t["function"]["name"],
                        "description": t["function"].get("description", ""),
                        "parameters": t["function"]["parameters"],
                    },
                })
            payload["tools"] = ollama_tools

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                yield {
                    "type": "error",
                    "code": exc.response.status_code,
                    "message": f"Ollama error: {exc.response.text}",
                }
                return
            except httpx.ConnectError as exc:
                yield {
                    "type": "error",
                    "code": 0,
                    "message": f"Cannot connect to Ollama at {self._base_url}: {exc}",
                }
                return
            except httpx.TimeoutException as exc:
                yield {
                    "type": "error",
                    "code": 0,
                    "message": f"Ollama request timed out: {exc}",
                }
                return

            # Stream line-by-line (Ollama returns NDJSON)
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if "message" in chunk:
                    msg = chunk["message"]
                    if msg.get("content"):
                        yield {"type": "delta", "content": msg["content"]}
                    if msg.get("tool_calls"):
                        for tc in msg["tool_calls"]:
                            yield {
                                "type": "tool_call",
                                "id": tc.get("id", ""),
                                "name": tc["function"]["name"],
                                "arguments": tc["function"].get("arguments", {}),
                            }

                if chunk.get("done", False):
                    yield {"type": "done"}
                    return

        yield {"type": "done"}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "ollama": OllamaProvider,
}


def get_provider(config: dict[str, Any]) -> BaseProvider:
    """Factory: instantiate a provider from a config dict.

    Expects keys: ``ai_provider``, ``ai_api_key``, ``ai_model``,
    and optionally ``ai_base_url``.

    Raises ``ValueError`` for unknown provider names.
    """
    provider_name = (config.get("ai_provider") or "openai").lower().strip()
    cls = _PROVIDER_REGISTRY.get(provider_name)
    if cls is None:
        valid = ", ".join(_PROVIDER_REGISTRY)
        raise ValueError(
            f"Unknown AI provider: {provider_name!r}. "
            f"Valid options: {valid}"
        )

    if provider_name == "openai":
        return OpenAIProvider(
            api_key=config.get("ai_api_key") or "",
            model=config.get("ai_model") or "gpt-4o",
            base_url=config.get("ai_base_url"),
        )
    elif provider_name == "anthropic":
        return AnthropicProvider(
            api_key=config.get("ai_api_key") or "",
            model=config.get("ai_model") or "claude-sonnet-4-20250514",
            base_url=config.get("ai_base_url"),
        )
    elif provider_name == "ollama":
        return OllamaProvider(
            base_url=config.get("ai_base_url") or "http://localhost:11434",
            model=config.get("ai_model") or "llama3.1",
        )
    else:
        raise ValueError(f"Unhandled provider: {provider_name!r}")
