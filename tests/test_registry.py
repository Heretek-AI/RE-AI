"""Tests for the tool registry (backend/registry/).

Covers CRUD operations on MCPToolDef and CLIToolDef, ToolDef generation
(mcp_invoke schema, descriptions), execution dispatch placeholders, and
integration with the agent tool pipeline.
"""

import pytest

from backend.registry import CLIToolDef, MCPToolDef, ToolRegistry
from backend.agent.tools import ToolDef as AgentToolDef


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the ToolRegistry singleton before each test."""
    ToolRegistry.reset_instance()
    yield
    ToolRegistry.reset_instance()


@pytest.fixture
def registry():
    return ToolRegistry.get_instance()


@pytest.fixture
def sample_mcp():
    return MCPToolDef(
        name="file_system",
        description="Read and write files on the local filesystem via MCP.",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "."],
    )


@pytest.fixture
def sample_mcp_2():
    return MCPToolDef(
        name="github",
        description="Interact with GitHub repositories, issues, and PRs.",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env_vars={"GITHUB_TOKEN": "ghp_test123"},
    )


@pytest.fixture
def sample_cli():
    return CLIToolDef(
        name="ida",
        description="Interactive disassembler and debugger.",
        command_hint="idat64.exe -A -Sscript.py target.exe",
        shell="cmd",
    )


@pytest.fixture
def sample_cli_2():
    return CLIToolDef(
        name="ghidra",
        description="Suite of reverse engineering tools.",
        command_hint="analyzeHeadless /tmp/project -import target.exe",
        shell="cmd",
    )


# =========================================================================
# Singleton
# =========================================================================


def test_registry_singleton():
    """ToolRegistry.get_instance() returns the same instance."""
    r1 = ToolRegistry.get_instance()
    r2 = ToolRegistry.get_instance()
    assert r1 is r2


def test_registry_reset_instance():
    """reset_instance() clears the singleton."""
    r1 = ToolRegistry.get_instance()
    ToolRegistry.reset_instance()
    r2 = ToolRegistry.get_instance()
    assert r1 is not r2


# =========================================================================
# MCP CRUD
# =========================================================================


def test_register_mcp(registry, sample_mcp):
    """register_mcp adds a tool and it appears in list_mcp."""
    registry.register_mcp(sample_mcp)
    tools = registry.list_mcp()
    assert len(tools) == 1
    assert tools[0].name == "file_system"


def test_register_mcp_multiple(registry, sample_mcp, sample_mcp_2):
    """Multiple MCP tools can be registered."""
    registry.register_mcp(sample_mcp)
    registry.register_mcp(sample_mcp_2)
    tools = registry.list_mcp()
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"file_system", "github"}


def test_register_mcp_replaces_existing(registry, sample_mcp):
    """Registering with an existing name replaces the old definition."""
    registry.register_mcp(sample_mcp)
    replacement = MCPToolDef(
        name="file_system",
        description="Updated description.",
        command="python",
    )
    registry.register_mcp(replacement)
    tool = registry.get_mcp("file_system")
    assert tool is not None
    assert tool.description == "Updated description."
    assert tool.command == "python"


def test_unregister_mcp(registry, sample_mcp):
    """unregister_mcp removes a tool and returns True."""
    registry.register_mcp(sample_mcp)
    result = registry.unregister_mcp("file_system")
    assert result is True
    assert registry.list_mcp() == []


def test_unregister_mcp_not_found(registry):
    """unregister_mcp returns False for unknown names."""
    result = registry.unregister_mcp("nonexistent")
    assert result is False


def test_get_mcp(registry, sample_mcp):
    """get_mcp returns the correct tool by name."""
    registry.register_mcp(sample_mcp)
    tool = registry.get_mcp("file_system")
    assert tool is not None
    assert tool.command == "npx"
    assert tool.args == ["-y", "@modelcontextprotocol/server-filesystem", "."]


def test_get_mcp_not_found(registry):
    """get_mcp returns None for unknown names."""
    tool = registry.get_mcp("nonexistent")
    assert tool is None


def test_get_mcp_status(registry, sample_mcp, sample_mcp_2):
    """get_mcp_status returns per-server registration info."""
    registry.register_mcp(sample_mcp)
    registry.register_mcp(sample_mcp_2)
    status = registry.get_mcp_status()
    assert len(status) == 2
    names = {s["name"] for s in status}
    assert names == {"file_system", "github"}
    for s in status:
        assert s["registered"] is True
        assert "description" in s
        assert "command" in s


# =========================================================================
# CLI CRUD
# =========================================================================


def test_register_cli(registry, sample_cli):
    """register_cli adds a tool and it appears in list_cli."""
    registry.register_cli(sample_cli)
    tools = registry.list_cli()
    assert len(tools) == 1
    assert tools[0].name == "ida"


def test_register_cli_multiple(registry, sample_cli, sample_cli_2):
    """Multiple CLI tools can be registered."""
    registry.register_cli(sample_cli)
    registry.register_cli(sample_cli_2)
    tools = registry.list_cli()
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"ida", "ghidra"}


def test_register_cli_replaces_existing(registry, sample_cli):
    """Registering with an existing name replaces the old definition."""
    registry.register_cli(sample_cli)
    replacement = CLIToolDef(
        name="ida",
        description="Updated CLI tool.",
        command_hint="idat64.exe -A target.exe",
    )
    registry.register_cli(replacement)
    tool = registry.get_cli("ida")
    assert tool is not None
    assert tool.description == "Updated CLI tool."


def test_unregister_cli(registry, sample_cli):
    """unregister_cli removes a tool and returns True."""
    registry.register_cli(sample_cli)
    result = registry.unregister_cli("ida")
    assert result is True
    assert registry.list_cli() == []


def test_unregister_cli_not_found(registry):
    """unregister_cli returns False for unknown names."""
    result = registry.unregister_cli("nonexistent")
    assert result is False


def test_get_cli(registry, sample_cli):
    """get_cli returns the correct tool by name."""
    registry.register_cli(sample_cli)
    tool = registry.get_cli("ida")
    assert tool is not None
    assert tool.command_hint == "idat64.exe -A -Sscript.py target.exe"
    assert tool.shell == "cmd"


def test_get_cli_not_found(registry):
    """get_cli returns None for unknown names."""
    tool = registry.get_cli("nonexistent")
    assert tool is None


# =========================================================================
# ToolDef generation (mcp_invoke)
# =========================================================================


def test_get_tool_defs_empty(registry):
    """get_tool_defs returns one mcp_invoke ToolDef even with no servers."""
    defs = registry.get_tool_defs()
    assert len(defs) == 1
    tool = defs[0]
    assert isinstance(tool, AgentToolDef)
    assert tool.name == "mcp_invoke"


def test_get_tool_defs_schema_shape(registry):
    """mcp_invoke ToolDef has the expected schema."""
    defs = registry.get_tool_defs()
    tool = defs[0]
    assert tool.name == "mcp_invoke"
    assert "Available servers" in tool.description
    assert "(no servers registered)" in tool.description

    schema = tool.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "mcp_invoke"
    params = schema["function"]["parameters"]
    assert params["type"] == "object"
    props = params["properties"]
    assert "server" in props
    assert "tool" in props
    assert "arguments" in props
    assert params["required"] == ["server", "tool"]


def test_get_tool_defs_with_servers(registry, sample_mcp, sample_mcp_2):
    """mcp_invoke description lists registered servers."""
    registry.register_mcp(sample_mcp)
    registry.register_mcp(sample_mcp_2)

    defs = registry.get_tool_defs()
    tool = defs[0]
    assert "file_system" in tool.description
    assert "github" in tool.description
    assert "Read and write files" in tool.description
    assert "Interact with GitHub" in tool.description


def test_get_tool_defs_updates_on_register(registry, sample_mcp):
    """Description updates when a new MCP server is registered."""
    defs_before = registry.get_tool_defs()
    assert "(no servers registered)" in defs_before[0].description

    registry.register_mcp(sample_mcp)
    defs_after = registry.get_tool_defs()
    assert "file_system" in defs_after[0].description
    assert "(no servers registered)" not in defs_after[0].description


def test_get_tool_defs_updates_on_unregister(registry, sample_mcp, sample_mcp_2):
    """Description updates when an MCP server is unregistered."""
    registry.register_mcp(sample_mcp)
    registry.register_mcp(sample_mcp_2)
    registry.unregister_mcp("file_system")

    defs = registry.get_tool_defs()
    assert "file_system" not in defs[0].description
    assert "github" in defs[0].description


# =========================================================================
# CLI descriptions
# =========================================================================


def test_get_cli_descriptions_empty(registry):
    """get_cli_descriptions returns empty string when no CLI tools."""
    text = registry.get_cli_descriptions()
    assert text == ""


def test_get_cli_descriptions(registry, sample_cli, sample_cli_2):
    """get_cli_descriptions returns formatted text for all CLI tools."""
    registry.register_cli(sample_cli)
    registry.register_cli(sample_cli_2)

    text = registry.get_cli_descriptions()
    assert "Available CLI tools:" in text
    assert "ida" in text
    assert "ghidra" in text
    assert "Interactive disassembler" in text
    assert "Suite of reverse engineering" in text
    assert "idat64.exe -A -Sscript.py" in text
    assert "analyzeHeadless" in text
    assert "[cmd]" in text  # shell annotation


def test_get_cli_descriptions_without_shell(registry):
    """CLI tools without a shell don't show shell annotation."""
    tool = CLIToolDef(
        name="test_tool",
        description="A test tool.",
        command_hint="test_tool --help",
    )
    registry.register_cli(tool)
    text = registry.get_cli_descriptions()
    assert "test_tool" in text
    assert "[" not in text  # no shell annotation


# =========================================================================
# Execution dispatch (T01 placeholder)
# =========================================================================


@pytest.mark.asyncio
async def test_exec_mcp_invoke_unknown_server(registry):
    """mcp_invoke returns ERROR for unknown server."""
    result = await registry._exec_mcp_invoke(
        {"server": "nonexistent", "tool": "some_tool", "arguments": {}}
    )
    assert result.startswith("ERROR:")
    assert "Unknown MCP server" in result


@pytest.mark.asyncio
async def test_exec_mcp_invoke_known_server(registry, sample_mcp):
    """mcp_invoke returns placeholder for known server at T01."""
    registry.register_mcp(sample_mcp)
    result = await registry._exec_mcp_invoke(
        {"server": "file_system", "tool": "read_file", "arguments": {"path": "/tmp/test.txt"}}
    )
    assert "not yet implemented" in result
    assert "file_system" in result
    assert "read_file" in result


@pytest.mark.asyncio
async def test_exec_registered_tool_mcp_invoke(registry, sample_mcp):
    """exec_registered_tool dispatches mcp_invoke by name."""
    registry.register_mcp(sample_mcp)
    result = await registry.exec_registered_tool(
        "mcp_invoke",
        {"server": "file_system", "tool": "read_file", "arguments": {}},
    )
    assert "not yet implemented" in result


@pytest.mark.asyncio
async def test_exec_registered_tool_unknown(registry):
    """exec_registered_tool returns ERROR for unknown name."""
    result = await registry.exec_registered_tool("nonexistent", {})
    assert result.startswith("ERROR:")
    assert "Unknown registered tool" in result


@pytest.mark.asyncio
async def test_exec_registered_tool_mcp_by_name(registry, sample_mcp):
    """exec_registered_tool matches MCP tool by direct name."""
    registry.register_mcp(sample_mcp)
    result = await registry.exec_registered_tool("file_system", {})
    assert "not yet implemented" in result
    assert "file_system" in result


# =========================================================================
# Lifecycle
# =========================================================================


@pytest.mark.asyncio
async def test_shutdown_all_noop(registry):
    """shutdown_all is a no-op at T01 (no error)."""
    # Should not raise any exception
    await registry.shutdown_all()
    # No state to assert — placeholder for T04


# =========================================================================
# End-to-end: register, describe, unregister
# =========================================================================


def test_register_describe_unregister(registry, sample_mcp, sample_cli):
    """Full lifecycle: register MCP+CLI, verify ToolDefs and descriptions, unregister."""
    # Register
    registry.register_mcp(sample_mcp)
    registry.register_cli(sample_cli)

    # Check ToolDefs
    defs = registry.get_tool_defs()
    assert len(defs) == 1
    assert "file_system" in defs[0].description
    assert "Read and write files" in defs[0].description

    # Check CLI descriptions
    cli_text = registry.get_cli_descriptions()
    assert "ida" in cli_text

    # Unregister
    registry.unregister_mcp("file_system")
    registry.unregister_cli("ida")

    # Verify empty
    assert registry.list_mcp() == []
    assert registry.list_cli() == []
    assert "(no servers registered)" in registry.get_tool_defs()[0].description
    assert registry.get_cli_descriptions() == ""


# =========================================================================
# Integration: registry tools appear in agent tool pipeline
# =========================================================================


def test_schemas_include_mcp_invoke(registry, sample_mcp):
    """get_tool_schemas() includes the mcp_invoke schema from the registry."""
    from backend.agent.tools import get_tool_schemas

    # Before registering any MCP servers
    schemas = get_tool_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "mcp_invoke" in names, "mcp_invoke should appear in schemas"

    # Verify it has the expected shape
    mcp_schema = next(s for s in schemas if s["function"]["name"] == "mcp_invoke")
    params = mcp_schema["function"]["parameters"]
    assert "server" in params["properties"]
    assert "tool" in params["properties"]
    assert params["required"] == ["server", "tool"]


def test_schemas_mcp_description_updates_with_registry(registry, sample_mcp):
    """mcp_invoke description in schemas updates when MCP servers are registered."""
    from backend.agent.tools import get_tool_schemas

    registry.register_mcp(sample_mcp)

    schemas = get_tool_schemas()
    mcp_schema = next(s for s in schemas if s["function"]["name"] == "mcp_invoke")
    desc = mcp_schema["function"]["description"]
    assert "file_system" in desc
    assert "Read and write files" in desc


def test_schemas_multiple_registry_servers(registry, sample_mcp, sample_mcp_2):
    """Multiple registered MCP servers all appear in the mcp_invoke description."""
    from backend.agent.tools import get_tool_schemas

    registry.register_mcp(sample_mcp)
    registry.register_mcp(sample_mcp_2)

    schemas = get_tool_schemas()
    mcp_schema = next(s for s in schemas if s["function"]["name"] == "mcp_invoke")
    desc = mcp_schema["function"]["description"]
    assert "file_system" in desc
    assert "github" in desc


def test_schemas_static_tools_still_present(registry):
    """Static tools (shell, kanban) still appear alongside registry tools."""
    from backend.agent.tools import get_tool_schemas

    schemas = get_tool_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "shell" in names
    assert "create_task" in names
    assert "update_task_status" in names
    assert "get_task_status" in names
    assert "get_slice_tasks" in names
    assert "mcp_invoke" in names


def test_prompt_includes_cli_descriptions(registry, sample_cli):
    """_build_system_prompt() includes CLI descriptions from the registry."""
    from backend.agent.loop import _build_system_prompt

    registry.register_cli(sample_cli)
    prompt = _build_system_prompt()
    assert "ida" in prompt
    assert "Interactive disassembler" in prompt
    assert "idat64.exe" in prompt
    assert "[cmd]" in prompt


def test_prompt_multiple_cli_tools(registry, sample_cli, sample_cli_2):
    """Multiple CLI tools all appear in the prompt."""
    from backend.agent.loop import _build_system_prompt

    registry.register_cli(sample_cli)
    registry.register_cli(sample_cli_2)
    prompt = _build_system_prompt()
    assert "ida" in prompt
    assert "ghidra" in prompt
    assert "Available CLI tools:" in prompt


@pytest.mark.asyncio
async def test_execute_tool_falls_through_to_registry(registry, sample_mcp):
    """execute_tool_call() dispatches mcp_invoke through the registry."""
    from backend.agent.tools import execute_tool_call

    registry.register_mcp(sample_mcp)

    # Use a lightweight mock engine — PlanningEngine requires aiosqlite,
    # so we provide a minimal object with the attributes the tool path touches.
    class _MockEngine:
        pass

    engine = _MockEngine()
    result = await execute_tool_call(
        "mcp_invoke",
        {"server": "file_system", "tool": "read_file", "arguments": {}},
        engine,
    )
    assert isinstance(result, str)
    # Currently returns placeholder until T04
    assert "not yet implemented" in result or result.startswith("ERROR:")
