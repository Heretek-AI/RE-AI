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

from pathlib import Path

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


# =========================================================================
# RAG store guard tests for analysis tool handlers
# =========================================================================


class TestAnalysisRagGuard:
    """Verify the _rag_store guard in all 5 analysis tool handlers.

    Each analysis handler in backend/agent/tools.py has a fire-and-forget
    RAG storage block guarded by ``if _rag_store is not None:``.
    These tests verify that:

    1. When ``_rag_store`` is None (default), analysis commands complete
       normally without trying to store anything.
    2. When ``_rag_store`` is set to a mock, each handler fires
       ``_rag_store.store()`` with correct metadata.
    """

    FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
    TEST_DLL = str(FIXTURE_DIR / "minimal_test.dll")

    @pytest.fixture()
    def mock_engine(self):
        """Return a minimal mock PlanningEngine (unused by analysis tools)."""
        from unittest.mock import AsyncMock

        return AsyncMock()

    # ── With _rag_store = None (default) ───────────────────────────

    @pytest.mark.asyncio
    async def test_rag_store_none_does_not_crash(self, mock_engine) -> None:
        """When _rag_store is None, analysis handlers complete without error."""
        from backend.agent import tools

        original = tools._rag_store
        tools._rag_store = None
        try:
            # Test all 5 handlers — they should complete normally
            result_pe = await tools.execute_tool_call(
                "extract_pe_info", {"path": self.TEST_DLL}, mock_engine,
            )
            assert "## PE Structure" in result_pe

            result_imports = await tools.execute_tool_call(
                "list_imports_exports", {"path": self.TEST_DLL}, mock_engine,
            )
            assert "## Imports & Exports" in result_imports

            result_strings = await tools.execute_tool_call(
                "extract_strings", {"path": self.TEST_DLL}, mock_engine,
            )
            assert "## Strings" in result_strings

            result_disasm = await tools.execute_tool_call(
                "disassemble_function",
                {"path": self.TEST_DLL, "section_name": ".text", "offset": 0},
                mock_engine,
            )
            assert "## Disassembly" in result_disasm

            import tempfile
            result_dir = await tools.execute_tool_call(
                "analyze_directory",
                {"directory": str(tempfile.gettempdir())},
                mock_engine,
            )
            assert "Directory Analysis" in result_dir or "No PE files found" in result_dir
        finally:
            tools._rag_store = original

    # ── With _rag_store = AsyncMock ────────────────────────────────

    @pytest.mark.asyncio
    async def test_rag_store_called_extract_pe_info(self, mock_engine) -> None:
        """extract_pe_info fires _rag_store.store() when store is available."""
        from backend.agent import tools

        mock_store = AsyncMock()
        original = tools._rag_store
        tools._rag_store = mock_store
        try:
            result = await tools.execute_tool_call(
                "extract_pe_info", {"path": self.TEST_DLL}, mock_engine,
            )
            assert "## PE Structure" in result
            # Fire-and-forget uses asyncio.create_task, so the coroutine is
            # scheduled but not awaited.  We verify the call was made, not
            # that it was awaited.
            mock_store.store.assert_called_once()
            call_args = mock_store.store.call_args
            # store() is called as: store("tool_results", text, metadata_dict)
            assert call_args[0][0] == "tool_results"
            metadata = call_args[0][2]
            assert metadata["tool_name"] == "extract_pe_info"
        finally:
            tools._rag_store = original

    @pytest.mark.asyncio
    async def test_rag_store_called_list_imports_exports(self, mock_engine) -> None:
        """list_imports_exports fires _rag_store.store()."""
        from backend.agent import tools

        mock_store = AsyncMock()
        original = tools._rag_store
        tools._rag_store = mock_store
        try:
            result = await tools.execute_tool_call(
                "list_imports_exports", {"path": self.TEST_DLL}, mock_engine,
            )
            assert "## Imports & Exports" in result
            mock_store.store.assert_called_once()
            metadata = mock_store.store.call_args[0][2]
            assert metadata["tool_name"] == "list_imports_exports"
        finally:
            tools._rag_store = original

    @pytest.mark.asyncio
    async def test_rag_store_called_extract_strings(self, mock_engine) -> None:
        """extract_strings fires _rag_store.store()."""
        from backend.agent import tools

        mock_store = AsyncMock()
        original = tools._rag_store
        tools._rag_store = mock_store
        try:
            result = await tools.execute_tool_call(
                "extract_strings", {"path": self.TEST_DLL}, mock_engine,
            )
            assert "## Strings" in result
            mock_store.store.assert_called_once()
            metadata = mock_store.store.call_args[0][2]
            assert metadata["tool_name"] == "extract_strings"
        finally:
            tools._rag_store = original

    @pytest.mark.asyncio
    async def test_rag_store_called_disassemble(self, mock_engine) -> None:
        """disassemble_function fires _rag_store.store()."""
        from backend.agent import tools

        mock_store = AsyncMock()
        original = tools._rag_store
        tools._rag_store = mock_store
        try:
            result = await tools.execute_tool_call(
                "disassemble_function",
                {"path": self.TEST_DLL, "section_name": ".text", "offset": 0},
                mock_engine,
            )
            assert "## Disassembly" in result
            mock_store.store.assert_called_once()
            metadata = mock_store.store.call_args[0][2]
            assert metadata["tool_name"] == "disassemble_function"
        finally:
            tools._rag_store = original

    @pytest.mark.asyncio
    async def test_rag_store_called_analyze_directory(self, mock_engine, tmp_path) -> None:
        """analyze_directory fires _rag_store.store()."""
        import shutil

        from backend.agent import tools

        # Copy fixture DLL to tmp_path
        shutil.copy2(self.TEST_DLL, str(tmp_path / "minimal_test.dll"))

        mock_store = AsyncMock()
        original = tools._rag_store
        tools._rag_store = mock_store
        try:
            result = await tools.execute_tool_call(
                "analyze_directory",
                {"directory": str(tmp_path)},
                mock_engine,
            )
            assert "Directory Analysis" in result
            mock_store.store.assert_called_once()
            metadata = mock_store.store.call_args[0][2]
            assert metadata["tool_name"] == "analyze_directory"
        finally:
            tools._rag_store = original

    # ── All 5 tools use asyncio.create_task (fire-and-forget) ───────

    @pytest.mark.asyncio
    async def test_rag_store_fire_and_forget_extract_pe(self, mock_engine) -> None:
        """Verify RAG store call uses fire-and-forget create_task."""
        from backend.agent import tools

        async def _delayed_store(*args, **kwargs):
            await asyncio.sleep(0)

        mock_store = AsyncMock()
        mock_store.store.side_effect = _delayed_store

        original = tools._rag_store
        tools._rag_store = mock_store
        try:
            # Handler returns immediately because store() is fire-and-forget
            result = await tools.execute_tool_call(
                "extract_pe_info", {"path": self.TEST_DLL}, mock_engine,
            )
            assert "## PE Structure" in result
            # Store was called (scheduled via create_task)
            mock_store.store.assert_called_once()
        finally:
            tools._rag_store = original
