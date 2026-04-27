"""Tests for the agent loop engine and chat WebSocket.

Uses mock providers to avoid real API calls during unit testing.
"""

import asyncio
import json
from collections.abc import AsyncIterator, AsyncGenerator
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from fastapi import WebSocket
from fastapi import WebSocketDisconnect

import pytest
from fastapi import WebSocket

from backend.agent.loop import (
    AgentLoopSession,
    DEFAULT_SYSTEM_PROMPT,
    _build_system_prompt,
)
from backend.agent.provider import BaseProvider
from backend.agent.tools import MAX_TOOL_CALLS_PER_TURN
from backend.api.chat_ws import chat_websocket, _forward_events
from backend.api.ws import ConnectionManager


# =========================================================================
# Mock provider for testing
# =========================================================================


class MockProvider(BaseProvider):
    """Yields a predetermined sequence of events from a list."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self._call_count = 0

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        self._call_count += 1
        for event in self._events:
            yield event


class StreamingMockProvider(BaseProvider):
    """Yields delta chunks first, then tool_call, then done."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_messages: Optional[list[dict[str, Any]]] = None

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        self.call_count += 1
        self.last_messages = messages
        yield {"type": "delta", "content": "Hello! "}
        yield {"type": "delta", "content": "How can I help?"}
        yield {"type": "done"}


# =========================================================================
# System prompt tests
# =========================================================================


def test_build_system_prompt_contains_tools():
    """_build_system_prompt() lists available tools in the prompt."""
    prompt = _build_system_prompt()
    assert "shell" in prompt
    assert "create_task" in prompt
    assert "update_task_status" in prompt
    assert "get_task_status" in prompt
    assert "get_slice_tasks" in prompt


def test_default_system_prompt_template():
    """DEFAULT_SYSTEM_PROMPT has a {tool_descriptions} placeholder."""
    assert "{tool_descriptions}" in DEFAULT_SYSTEM_PROMPT


# =========================================================================
# AgentLoopSession creation
# =========================================================================


@pytest.mark.asyncio
async def test_session_creation():
    """AgentLoopSession can be created with a mock provider and mock engine."""
    provider = MockProvider([])
    engine = AsyncMock()
    session = AgentLoopSession(provider=provider, engine=engine)
    assert session.messages == []


@pytest.mark.asyncio
async def test_session_custom_system_prompt():
    """Session uses a custom system prompt when provided."""
    provider = MockProvider([])
    engine = AsyncMock()
    session = AgentLoopSession(
        provider=provider,
        engine=engine,
        system_prompt="Custom system prompt",
    )
    assert session._system_prompt == "Custom system prompt"


# =========================================================================
# AgentLoopSession.process_message — simple response (no tool calls)
# =========================================================================


@pytest.mark.asyncio
async def test_process_message_no_tools():
    """process_message yields delta events and agent:done with no tool calls."""
    provider = StreamingMockProvider()
    engine = AsyncMock()
    session = AgentLoopSession(provider=provider, engine=engine)

    events = []
    async for event in session.process_message("Hello"):
        events.append(event)

    # Should have: 2 deltas + done
    assert len(events) == 3
    assert events[0]["type"] == "agent:delta"
    assert events[0]["content"] == "Hello! "
    assert events[1]["type"] == "agent:delta"
    assert events[1]["content"] == "How can I help?"
    assert events[2]["type"] == "agent:done"

    # Conversation history should include user message and assistant response
    assert len(session.messages) == 2
    assert session.messages[0]["role"] == "user"
    assert session.messages[0]["content"] == "Hello"
    assert session.messages[1]["role"] == "assistant"
    assert session.messages[1]["content"] == "Hello! How can I help?"


# =========================================================================
# AgentLoopSession.process_message — tool call cycle
# =========================================================================


@pytest.mark.asyncio
async def test_process_message_with_tool_call():
    """process_message handles a tool call cycle: tool_call → tool_result."""

    class ToolCallProvider(BaseProvider):
        """Yields delta, then tool_call, then done on first call.
        On second call (LLM sees tool result), yields delta + done."""

        def __init__(self) -> None:
            self.call_count = 0

        async def chat_stream(
            self,
            messages: list[dict[str, Any]],
            system_prompt: str,
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[dict[str, Any]]:
            self.call_count += 1
            if self.call_count == 1:
                yield {"type": "delta", "content": "Let me check that."}
                yield {
                    "type": "tool_call",
                    "id": "call_123",
                    "name": "get_task_status",
                    "arguments": {"task_id": 1},
                }
                yield {"type": "done"}
            else:
                yield {"type": "delta", "content": "Task 1 is pending."}
                yield {"type": "done"}

    provider = ToolCallProvider()
    engine = AsyncMock()
    engine.get_task = AsyncMock(
        return_value=MagicMock(
            id=1, title="Test task", status="pending", slice_id=1,
            updated_at=MagicMock(isoformat=lambda: "2026-04-27T00:00:00"),
        )
    )

    session = AgentLoopSession(provider=provider, engine=engine)

    events = []
    async for event in session.process_message("Check task 1"):
        events.append(event)

    # Event sequence: delta → tool_call → tool_result → delta → done
    assert len(events) == 5

    assert events[0]["type"] == "agent:delta"
    assert events[0]["content"] == "Let me check that."

    assert events[1]["type"] == "agent:tool_call"
    assert events[1]["name"] == "get_task_status"
    assert events[1]["arguments"]["task_id"] == 1

    assert events[2]["type"] == "agent:tool_result"
    assert events[2]["name"] == "get_task_status"
    assert "pending" in events[2]["result"]

    assert events[3]["type"] == "agent:delta"
    assert events[3]["content"] == "Task 1 is pending."

    assert events[4]["type"] == "agent:done"

    # Tool result should be in conversation history
    assert provider.call_count == 2


# =========================================================================
# AgentLoopSession.process_message — max tool calls enforcement
# =========================================================================


@pytest.mark.asyncio
async def test_process_message_max_tool_calls():
    """process_message enforces MAX_TOOL_CALLS_PER_TURN limit."""

    class InfiniteToolProvider(BaseProvider):
        """Always yields a tool call — used to test the max limit."""

        async def chat_stream(
            self,
            messages: list[dict[str, Any]],
            system_prompt: str,
            tools: list[dict[str, Any]],
        ) -> AsyncIterator[dict[str, Any]]:
            yield {"type": "delta", "content": "Using a tool..."}
            yield {
                "type": "tool_call",
                "id": "call_loop",
                "name": "get_slice_tasks",
                "arguments": {"slice_id": 1},
            }
            yield {"type": "done"}

    provider = InfiniteToolProvider()
    engine = AsyncMock()
    engine.get_tasks_by_slice = AsyncMock(
        return_value=[
            MagicMock(id=1, title="A", status="pending"),
        ]
    )

    session = AgentLoopSession(provider=provider, engine=engine)

    events = []
    async for event in session.process_message("Do many things"):
        events.append(event)

    # The loop should eventually hit the max and emit an error + done
    error_events = [e for e in events if e["type"] == "agent:error"]
    done_events = [e for e in events if e["type"] == "agent:done"]
    tool_call_events = [e for e in events if e["type"] == "agent:tool_call"]
    tool_result_events = [e for e in events if e["type"] == "agent:tool_result"]

    # Should have multiple tool call cycles
    assert len(tool_call_events) >= MAX_TOOL_CALLS_PER_TURN
    assert len(tool_result_events) >= MAX_TOOL_CALLS_PER_TURN

    # Should have an error about max tool calls
    assert len(error_events) >= 1
    assert "maximum" in error_events[-1]["message"].lower() or "max" in error_events[-1]["message"].lower()

    # Should end with done
    assert done_events[-1]["type"] == "agent:done"


# =========================================================================
# AgentLoopSession.process_message — error handling
# =========================================================================


@pytest.mark.asyncio
async def test_process_message_provider_error():
    """process_message handles provider errors gracefully."""
    provider = MockProvider([
        {"type": "error", "code": 401, "message": "Invalid API key"},
    ])
    engine = AsyncMock()
    session = AgentLoopSession(provider=provider, engine=engine)

    events = []
    async for event in session.process_message("Hello"):
        events.append(event)

    assert len(events) == 2
    assert events[0]["type"] == "agent:error"
    assert events[0]["code"] == 401
    assert events[1]["type"] == "agent:done"


@pytest.mark.asyncio
async def test_process_message_catches_exceptions():
    """process_message catches unexpected exceptions from provider."""

    class BrokenProvider(BaseProvider):
        async def chat_stream(self, messages, system_prompt, tools):
            raise RuntimeError("Something went terribly wrong")

    provider = BrokenProvider()
    engine = AsyncMock()
    session = AgentLoopSession(provider=provider, engine=engine)

    events = []
    async for event in session.process_message("Hello"):
        events.append(event)

    assert len(events) == 2
    assert events[0]["type"] == "agent:error"
    # Error message is wrapped by the outer handler — check it mentions error
    assert events[0]["message"] is not None
    assert events[1]["type"] == "agent:done"


@pytest.mark.asyncio
async def test_process_message_tool_error():
    """process_message handles tool execution errors without crashing."""
    provider = MockProvider([
        {"type": "delta", "content": "Running tool..."},
        {
            "type": "tool_call",
            "id": "call_err",
            "name": "create_task",
            "arguments": {"slice_id": 999, "title": "Bad task"},
        },
        {"type": "done"},
        {"type": "delta", "content": "Done."},
        {"type": "done"},
    ])
    engine = AsyncMock()
    engine.create_task = AsyncMock(return_value=None)  # Simulate slice not found

    session = AgentLoopSession(provider=provider, engine=engine)

    events = []
    async for event in session.process_message("Create a task in slice 999"):
        events.append(event)

    # Should include tool_result with error
    tool_results = [e for e in events if e["type"] == "agent:tool_result"]
    assert len(tool_results) >= 1
    assert "ERROR:" in tool_results[0]["result"]


def _make_mock_app():
    """Create a mock FastAPI app with engine on app.state."""
    app = MagicMock()
    app.state.engine = MagicMock()
    return app


# =========================================================================
# Chat WebSocket tests
# =========================================================================


@pytest.mark.asyncio
async def test_forward_events():
    """_forward_events sends events to a WebSocket as JSON messages."""
    provider = StreamingMockProvider()
    engine = AsyncMock()
    session = AgentLoopSession(provider=provider, engine=engine)

    # Create a mock WebSocket
    ws_mock = MagicMock(spec=WebSocket)

    await _forward_events(session, "Hello", ws_mock)

    # Should have sent 3 messages (2 deltas + done)
    assert ws_mock.send_text.call_count == 3
    assert ws_mock.send_json.call_count == 0

    # Check first message
    first_call = ws_mock.send_text.call_args_list[0]
    first_payload = json.loads(first_call[0][0])
    assert first_payload["type"] == "agent:delta"
    assert first_payload["content"] == "Hello! "


@pytest.mark.asyncio
async def test_forward_events_cancelled():
    """_forward_events handles CancelledError gracefully."""
    provider = MockProvider([
        {"type": "delta", "content": "Starting..."},
    ])
    engine = AsyncMock()
    session = AgentLoopSession(provider=provider, engine=engine)

    ws_mock = MagicMock(spec=WebSocket)

    # Create a task so we can cancel it
    async def run():
        await _forward_events(session, "Hello", ws_mock)

    task = asyncio.create_task(run())
    await asyncio.sleep(0.05)
    task.cancel()
    result = await task
    assert result is None  # Should not raise


@pytest.mark.asyncio
async def test_chat_websocket_no_config():
    """chat_websocket sends error when no config exists."""

    class _NoConfigWebSocket:
        """Simulates a WebSocket that gets one message then disconnects."""

        def __init__(self):
            self.sent: list[dict[str, Any]] = []
            self._call_count = 0
            self.scope = {"app": None}

        async def accept(self):
            pass

        async def receive_text(self) -> str:
            self._call_count += 1
            if self._call_count == 1:
                return json.dumps({"type": "chat:message", "content": "Hello"})
            raise WebSocketDisconnect()

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

        async def send_text(self, payload: str) -> None:
            self.sent.append(json.loads(payload))

        def close(self) -> None:
            pass

    ws = _NoConfigWebSocket()

    with patch("backend.api.chat_ws.ConfigStore") as mock_store_cls:
        mock_store = MagicMock()
        mock_store.load.return_value = {}
        mock_store_cls.return_value = mock_store

        await chat_websocket(ws)

    # Should have sent error about no config
    error_msgs = [s for s in ws.sent
                  if s.get("type") == "agent:error" and "configured" in s.get("message", "").lower()]
    assert len(error_msgs) >= 1
    assert any(s.get("type") == "agent:done" for s in ws.sent)


@pytest.mark.asyncio
async def test_chat_websocket_invalid_json():
    """chat_websocket sends error for invalid JSON messages."""

    mock_app = _make_mock_app()

    class _InvalidJsonWebSocket:
        def __init__(self):
            self.sent: list[dict[str, Any]] = []
            self._call_count = 0
            self.scope = {"app": mock_app}

        async def accept(self):
            pass

        async def receive_text(self) -> str:
            self._call_count += 1
            if self._call_count == 1:
                return "this is not json"
            raise WebSocketDisconnect()

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

        async def send_text(self, payload: str) -> None:
            self.sent.append(json.loads(payload))

        def close(self) -> None:
            pass

    ws = _InvalidJsonWebSocket()

    with patch("backend.api.chat_ws.ConfigStore") as mock_store_cls:
        mock_store = MagicMock()
        mock_store.load.return_value = {
            "ai_provider": "openai",
            "ai_api_key": "sk-test",
            "ai_model": "gpt-4o",
        }
        mock_store_cls.return_value = mock_store

        with patch("backend.api.chat_ws.get_provider") as mock_get_provider:
            mock_get_provider.return_value = MagicMock()

            await chat_websocket(ws)

    # Should have gotten an error about invalid JSON
    error_msgs = [s for s in ws.sent
                  if s.get("type") == "agent:error" and "Invalid JSON" in s.get("message", "")]
    assert len(error_msgs) == 1


@pytest.mark.asyncio
async def test_chat_websocket_unknown_message_type():
    """chat_websocket sends error for unknown message types."""

    mock_app = _make_mock_app()

    class _UnknownTypeWebSocket:
        def __init__(self):
            self.sent: list[dict[str, Any]] = []
            self._call_count = 0
            self.scope = {"app": mock_app}

        async def accept(self):
            pass

        async def receive_text(self) -> str:
            self._call_count += 1
            if self._call_count == 1:
                return json.dumps({"type": "unknown:type", "content": "Hello"})
            raise WebSocketDisconnect()

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

        async def send_text(self, payload: str) -> None:
            self.sent.append(json.loads(payload))

        def close(self) -> None:
            pass

    ws = _UnknownTypeWebSocket()

    with patch("backend.api.chat_ws.ConfigStore") as mock_store_cls:
        mock_store = MagicMock()
        mock_store.load.return_value = {
            "ai_provider": "openai",
            "ai_api_key": "sk-test",
            "ai_model": "gpt-4o",
        }
        mock_store_cls.return_value = mock_store

        with patch("backend.api.chat_ws.get_provider") as mock_get_provider:
            mock_get_provider.return_value = MagicMock()

            await chat_websocket(ws)

    error_msgs = [s for s in ws.sent
                  if s.get("type") == "agent:error" and "Unknown message type" in s.get("message", "")]
    assert len(error_msgs) >= 1


# =========================================================================
# Conversation history access
# =========================================================================


@pytest.mark.asyncio
async def test_messages_property_returns_copy():
    """messages property returns a copy, not the internal list."""
    provider = StreamingMockProvider()
    engine = AsyncMock()
    session = AgentLoopSession(provider=provider, engine=engine)

    msgs = session.messages
    msgs.append({"role": "test", "content": "should not modify internal"})

    # Internal list should be unchanged
    assert len(session._messages) == 0


# =========================================================================
# Edge cases
# =========================================================================


@pytest.mark.asyncio
async def test_process_message_empty_content():
    """process_message handles a provider that yields only done."""
    provider = MockProvider([{"type": "done"}])
    engine = AsyncMock()
    session = AgentLoopSession(provider=provider, engine=engine)

    events = []
    async for event in session.process_message("Hello"):
        events.append(event)

    assert len(events) == 1
    assert events[0]["type"] == "agent:done"

    # No assistant message appended (no content)
    assert len(session.messages) == 1
    assert session.messages[0]["role"] == "user"


@pytest.mark.asyncio
async def test_process_message_only_error():
    """process_message yields done after a provider error."""
    provider = MockProvider([
        {"type": "error", "code": 429, "message": "Rate limited"},
    ])
    engine = AsyncMock()
    session = AgentLoopSession(provider=provider, engine=engine)

    events = []
    async for event in session.process_message("Hello"):
        events.append(event)

    assert len(events) == 2
    assert events[0]["type"] == "agent:error"
    assert events[1]["type"] == "agent:done"


@pytest.mark.asyncio
async def test_process_message_tool_result_stored_in_history():
    """Tool results are appended to conversation history for LLM context."""

    class _TwoPhaseProvider(BaseProvider):
        """First call yields tool call, second call yields final response."""

        def __init__(self):
            self.call_count = 0

        async def chat_stream(self, messages, system_prompt, tools):
            self.call_count += 1
            if self.call_count == 1:
                yield {"type": "delta", "content": "Let me check..."}
                yield {
                    "type": "tool_call",
                    "id": "call_42",
                    "name": "get_slice_tasks",
                    "arguments": {"slice_id": 1},
                }
                yield {"type": "done"}
            else:
                yield {"type": "delta", "content": "All done."}
                yield {"type": "done"}

    provider = _TwoPhaseProvider()
    engine = AsyncMock()
    engine.get_tasks_by_slice = AsyncMock(
        return_value=[MagicMock(id=1, title="Test", status="pending")]
    )

    session = AgentLoopSession(provider=provider, engine=engine)

    async for _ in session.process_message("List tasks"):
        pass

    # Messages should include: user, assistant, tool (result), assistant
    roles = [m["role"] for m in session.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
