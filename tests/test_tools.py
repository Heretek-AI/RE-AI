"""Tests for agent tool definitions and provider abstraction.

Tests use mock patterns to avoid requiring actual AI API keys or
shell execution during unit testing.
"""

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.tools import (
    ToolDef,
    get_tool_schemas,
    execute_tool_call,
    TOOLS,
    DEFAULT_CWD,
    MAX_TOOL_CALLS_PER_TURN,
)
from backend.agent.provider import (
    BaseProvider,
    OpenAIProvider,
    AnthropicProvider,
    OllamaProvider,
    get_provider,
)


# =========================================================================
# ToolDef tests
# =========================================================================


def test_tooldef_to_openai_schema():
    """ToolDef.to_openai_schema() produces the expected OpenAI schema shape."""
    tool = ToolDef(
        name="test_tool",
        description="A test tool",
        input_schema={
            "type": "object",
            "properties": {
                "arg1": {"type": "string", "description": "First arg"},
            },
            "required": ["arg1"],
        },
    )
    schema = tool.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "test_tool"
    assert schema["function"]["description"] == "A test tool"
    assert schema["function"]["parameters"]["required"] == ["arg1"]


def test_get_tool_schemas_returns_all_tools():
    """get_tool_schemas() returns entries for all registered tools."""
    schemas = get_tool_schemas()
    assert len(schemas) >= 5  # shell, create_task, update_task_status, get_task_status, get_slice_tasks
    names = [s["function"]["name"] for s in schemas]
    assert "shell" in names
    assert "create_task" in names
    assert "update_task_status" in names
    assert "get_task_status" in names
    assert "get_slice_tasks" in names


async def _dummy_engine():
    """Return a mock PlanningEngine for tool tests."""
    mock = AsyncMock()
    mock.create_task = AsyncMock(
        return_value=MagicMock(
            id=42, title="Test task", status="pending", slice_id=1,
            updated_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00"),
        )
    )
    mock.update_task_status = AsyncMock(
        return_value=MagicMock(
            id=1, title="Test", status="in_progress",
            updated_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00"),
        )
    )
    mock.get_task = AsyncMock(
        return_value=MagicMock(
            id=1, title="Test task", status="pending", slice_id=1,
            updated_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00"),
        )
    )
    mock.get_tasks_by_slice = AsyncMock(
        return_value=[
            MagicMock(id=1, title="Task A", status="pending"),
            MagicMock(id=2, title="Task B", status="in_progress"),
        ]
    )
    return mock


@pytest.mark.asyncio
async def test_execute_tool_call_unknown():
    """execute_tool_call returns ERROR for unknown tool names."""
    engine = await _dummy_engine()
    result = await execute_tool_call("nonexistent_tool", {}, engine)
    assert result.startswith("ERROR:")
    assert "Unknown registered tool" in result


@pytest.mark.asyncio
async def test_execute_tool_call_create_task():
    """execute_tool_call dispatches to create_task correctly."""
    engine = await _dummy_engine()
    result = await execute_tool_call("create_task", {"slice_id": 1, "title": "New task"}, engine)
    assert "Created task" in result
    assert "42" in result
    engine.create_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_tool_call_get_task_status():
    """execute_tool_call dispatches to get_task_status correctly."""
    engine = await _dummy_engine()
    result = await execute_tool_call("get_task_status", {"task_id": 1}, engine)
    assert "Task 1" in result
    assert "pending" in result
    engine.get_task.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_execute_tool_call_get_slice_tasks():
    """execute_tool_call dispatches to get_slice_tasks correctly."""
    engine = await _dummy_engine()
    result = await execute_tool_call("get_slice_tasks", {"slice_id": 1}, engine)
    assert "Slice 1 tasks" in result
    assert "Task A" in result
    assert "Task B" in result


@pytest.mark.asyncio
async def test_execute_tool_call_update_task_status():
    """execute_tool_call dispatches to update_task_status correctly."""
    engine = await _dummy_engine()
    result = await execute_tool_call("update_task_status", {"task_id": 1, "status": "in_progress"}, engine)
    assert "changed to" in result
    assert "in_progress" in result
    engine.update_task_status.assert_awaited_once_with(1, "in_progress")


@pytest.mark.asyncio
async def test_execute_tool_call_update_task_invalid_status():
    """update_task_status with invalid status returns ERROR from engine."""
    engine = await _dummy_engine()
    engine.update_task_status = AsyncMock(side_effect=ValueError("Invalid status: unknown"))
    result = await execute_tool_call("update_task_status", {"task_id": 1, "status": "unknown"}, engine)
    assert result.startswith("ERROR:")


@pytest.mark.asyncio
async def test_execute_tool_call_create_task_missing_slice():
    """create_task returns ERROR when slice doesn't exist."""
    engine = await _dummy_engine()
    engine.create_task = AsyncMock(return_value=None)
    result = await execute_tool_call("create_task", {"slice_id": 999, "title": "Orphan"}, engine)
    assert result.startswith("ERROR:")
    assert "not found" in result


@pytest.mark.asyncio
async def test_execute_tool_call_get_task_not_found():
    """get_task_status returns ERROR when task doesn't exist."""
    engine = await _dummy_engine()
    engine.get_task = AsyncMock(return_value=None)
    result = await execute_tool_call("get_task_status", {"task_id": 999}, engine)
    assert result.startswith("ERROR:")
    assert "not found" in result


# =========================================================================
# Provider tests (mock-based, no real API calls)
# =========================================================================


def test_get_provider_unknown():
    """get_provider raises ValueError for unknown provider names."""
    with pytest.raises(ValueError, match="Unknown AI provider"):
        get_provider({"ai_provider": "nonexistent"})


def test_get_provider_openai():
    """get_provider returns OpenAIProvider for 'openai'."""
    provider = get_provider({
        "ai_provider": "openai",
        "ai_api_key": "sk-test",
        "ai_model": "gpt-4o",
    })
    assert isinstance(provider, OpenAIProvider)


def test_get_provider_anthropic():
    """get_provider returns AnthropicProvider for 'anthropic'."""
    provider = get_provider({
        "ai_provider": "anthropic",
        "ai_api_key": "sk-ant-test",
        "ai_model": "claude-sonnet-4-20250514",
    })
    assert isinstance(provider, AnthropicProvider)


def test_get_provider_ollama():
    """get_provider returns OllamaProvider for 'ollama'."""
    provider = get_provider({
        "ai_provider": "ollama",
        "ai_model": "llama3.1",
        "ai_base_url": "http://localhost:11434",
    })
    assert isinstance(provider, OllamaProvider)


@pytest.mark.asyncio
async def test_openai_provider_error_handling():
    """OpenAIProvider yields error events on API errors."""
    provider = OpenAIProvider(api_key="sk-bad", model="gpt-4o")

    with patch("openai.AsyncOpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_chat = mock_client.chat.completions.create

        from openai import APIStatusError

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.body = b'{"error": "unauthorized"}'
        mock_response.headers = {}
        mock_chat.side_effect = APIStatusError(
            message="Unauthorized",
            response=mock_response,
            body={"error": "unauthorized"},
        )

        events = []
        async for event in provider.chat_stream(
            messages=[{"role": "user", "content": "hello"}],
            system_prompt="You are a helpful assistant.",
            tools=[],
        ):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert events[0]["code"] == 401


@pytest.mark.asyncio
async def test_ollama_provider_connection_error():
    """OllamaProvider yields error event when Ollama is not running."""
    provider = OllamaProvider(base_url="http://localhost:19999", model="llama3.1")

    events = []
    async for event in provider.chat_stream(
        messages=[{"role": "user", "content": "hello"}],
        system_prompt="Be helpful.",
        tools=[],
    ):
        events.append(event)

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "Cannot connect" in events[0]["message"] or "ConnectError" in events[0]["message"]


# =========================================================================
# Tool schema shape tests
# =========================================================================


def test_tool_schemas_have_required_fields():
    """Every tool schema has name, description, and parameters."""
    schemas = get_tool_schemas()
    for s in schemas:
        fn = s["function"]
        assert fn["name"], f"Tool missing name: {fn}"
        assert fn["description"], f"Tool '{fn['name']}' missing description"
        assert "parameters" in fn, f"Tool '{fn['name']}' missing parameters"
        assert "type" in fn["parameters"], f"Tool '{fn['name']}' parameters missing type"
        assert "properties" in fn["parameters"], f"Tool '{fn['name']}' parameters missing properties"
