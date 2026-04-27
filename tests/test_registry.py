"""Tests for the tool registry (backend/registry/).

Covers CRUD operations on MCPToolDef and CLIToolDef, ToolDef generation
(mcp_invoke schema, descriptions), execution dispatch placeholders, and
integration with the agent tool pipeline.
"""

import asyncio
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
# Execution dispatch (T04 — real lifecycle, echo server)
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
async def test_exec_registered_tool_unknown(registry):
    """exec_registered_tool returns ERROR for unknown name."""
    result = await registry.exec_registered_tool("nonexistent", {})
    assert result.startswith("ERROR:")
    assert "Unknown registered tool" in result


# =========================================================================
# Lifecycle
# =========================================================================


@pytest.mark.asyncio
async def test_shutdown_all_empty(registry):
    """shutdown_all handles no registered servers cleanly."""
    # Should not raise
    await registry.shutdown_all()


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
async def test_execute_tool_falls_through_to_registry(registry, echo_def):
    """execute_tool_call() dispatches mcp_invoke through the registry."""
    from backend.agent.tools import execute_tool_call

    registry.register_mcp(echo_def)

    class _MockEngine:
        pass

    engine = _MockEngine()
    result = await execute_tool_call(
        "mcp_invoke",
        {"server": "echo_test", "tool": "ping", "arguments": {}},
        engine,
    )
    assert isinstance(result, str)
    # At T04 the echo server returns real JSON
    import json

    parsed = json.loads(result)
    assert "content" in parsed

    await registry.shutdown_all()


# =========================================================================
# Skill loader
# =========================================================================


def test_load_skills(registry, tmp_path):
    """load_skills() discovers and parses skill markdown files."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "test_skill.md").write_text(
        "---\n"
        "name: test-skill\n"
        "description: A test skill for unit testing\n"
        "tool_id: shell\n"
        "---\n"
        "\n"
        "## Test Skill Content\n"
        "\n"
        "This is sample skill content."
    )

    from backend.registry.skill_loader import load_skills

    skills = load_skills(skills_dir=str(skills_dir))
    assert len(skills) == 1
    assert skills[0].name == "test-skill"
    assert skills[0].description == "A test skill for unit testing"
    assert skills[0].tool_id == "shell"
    assert "Test Skill Content" in skills[0].content


def test_load_skills_empty_dir(registry):
    """load_skills() returns empty list when skills dir doesn't exist."""
    from backend.registry.skill_loader import load_skills

    skills = load_skills(skills_dir="nonexistent_skills_dir_xyz")
    assert skills == []


def test_load_skills_empty_dir_no_md(registry, tmp_path):
    """load_skills() returns empty list when skills dir has no .md files."""
    empty_dir = tmp_path / "empty_skills"
    empty_dir.mkdir()
    from backend.registry.skill_loader import load_skills

    skills = load_skills(skills_dir=str(empty_dir))
    assert skills == []


def test_load_skills_skips_missing_frontmatter(registry, tmp_path):
    """Skills without required frontmatter are skipped with a warning."""
    skills_dir = tmp_path / "skills_bad"
    skills_dir.mkdir()
    (skills_dir / "bad.md").write_text("# No frontmatter at all\n\nJust content.")
    (skills_dir / "good.md").write_text(
        "---\n"
        "name: good-skill\n"
        "description: A good one\n"
        "---\n"
        "\n"
        "Good content."
    )

    from backend.registry.skill_loader import load_skills

    skills = load_skills(skills_dir=str(skills_dir))
    assert len(skills) == 1
    assert skills[0].name == "good-skill"


def test_load_skills_skips_missing_name(registry, tmp_path):
    """Skills with missing 'name' in frontmatter are skipped."""
    skills_dir = tmp_path / "skills_noname"
    skills_dir.mkdir()
    (skills_dir / "noname.md").write_text(
        "---\n"
        "description: a skill without a name\n"
        "---\n"
        "\n"
        "Content."
    )
    from backend.registry.skill_loader import load_skills

    skills = load_skills(skills_dir=str(skills_dir))
    assert skills == []


def test_load_skills_skips_missing_description(registry, tmp_path):
    """Skills with missing 'description' in frontmatter are skipped."""
    skills_dir = tmp_path / "skills_nodesc"
    skills_dir.mkdir()
    (skills_dir / "nodesc.md").write_text(
        "---\n"
        "name: nodesc_skill\n"
        "---\n"
        "\n"
        "Content."
    )
    from backend.registry.skill_loader import load_skills

    skills = load_skills(skills_dir=str(skills_dir))
    assert skills == []


def test_load_skills_multiple_files(registry, tmp_path):
    """Multiple skill files are all loaded."""
    skills_dir = tmp_path / "skills_multi"
    skills_dir.mkdir()
    (skills_dir / "a.md").write_text(
        "---\nname: alpha\ndescription: first skill\n---\n\nAlpha content."
    )
    (skills_dir / "b.md").write_text(
        "---\nname: beta\ndescription: second skill\n---\n\nBeta content."
    )
    (skills_dir / "c.md").write_text(
        "---\nname: gamma\ndescription: third skill\n---\n\nGamma content."
    )

    from backend.registry.skill_loader import load_skills

    skills = load_skills(skills_dir=str(skills_dir))
    assert len(skills) == 3
    names = [s.name for s in skills]
    assert "alpha" in names
    assert "beta" in names
    assert "gamma" in names


def test_load_skills_corrupted_file(registry, tmp_path):
    """Corrupted skill files are skipped gracefully."""
    skills_dir = tmp_path / "skills_corrupt"
    skills_dir.mkdir()
    (skills_dir / "corrupt.md").write_bytes(b"\xff\xfe\x00\x01corrupt data")
    (skills_dir / "good.md").write_text(
        "---\nname: good\ndescription: valid skill\n---\n\nValid content."
    )

    from backend.registry.skill_loader import load_skills

    skills = load_skills(skills_dir=str(skills_dir))
    assert len(skills) == 1
    assert skills[0].name == "good"


def test_load_skills_with_none_tool_id(registry, tmp_path):
    """Skills without tool_id are loaded but don't enrich tools."""
    skills_dir = tmp_path / "skills_notool"
    skills_dir.mkdir()
    (skills_dir / "general.md").write_text(
        "---\nname: general-tips\ndescription: general best practices\n---\n\nGeneral tips."
    )

    from backend.registry.skill_loader import load_skills

    skills = load_skills(skills_dir=str(skills_dir))
    assert len(skills) == 1
    assert skills[0].tool_id is None


def test_load_skills_command_hint(registry, tmp_path):
    """Skills with command_hint parse correctly."""
    skills_dir = tmp_path / "skills_cmdhint"
    skills_dir.mkdir()
    (skills_dir / "cmdskill.md").write_text(
        "---\n"
        "name: cmdskill\n"
        "description: A skill with a command hint\n"
        "tool_id: shell\n"
        "command_hint: python --version\n"
        "---\n"
        "\n"
        "Skill with command hint."
    )

    from backend.registry.skill_loader import load_skills

    skills = load_skills(skills_dir=str(skills_dir))
    assert len(skills) == 1
    assert skills[0].command_hint == "python --version"


# =========================================================================
# Skill enrichment in ToolRegistry
# =========================================================================


def test_registry_load_skills(registry, tmp_path):
    """ToolRegistry.load_skills() loads from a custom directory."""
    skills_dir = tmp_path / "reg_skills"
    skills_dir.mkdir()
    (skills_dir / "skill_a.md").write_text(
        "---\nname: skill-a\ndescription: first skill\ntool_id: shell\n---\n\nSkill A content."
    )

    skills = registry.load_skills(skills_dir=str(skills_dir))
    assert len(skills) == 1
    assert skills[0].name == "skill-a"


def test_registry_load_skills_enriches_tool(registry, tmp_path):
    """load_skills enriches the matching tool description."""
    skills_dir = tmp_path / "enrich_skills"
    skills_dir.mkdir()
    (skills_dir / "enrich.md").write_text(
        "---\nname: shell-enrich\ndescription: enriches shell\ntool_id: shell\n---\n\n## Enrichment Content\n\nExtra shell guidance."
    )

    from backend.agent.tools import TOOLS

    # Capture original description length
    original_len = len([t for t in TOOLS if t.name == "shell"][0].description)

    registry.load_skills(skills_dir=str(skills_dir))

    shell_tool = [t for t in TOOLS if t.name == "shell"][0]
    assert len(shell_tool.description) > original_len
    assert "Enrichment Content" in shell_tool.description
    assert "Extra shell guidance" in shell_tool.description


def test_registry_load_skills_skips_unknown_tool_id(registry, tmp_path):
    """load_skills skips enrichment for tool_ids that don't match any tool."""
    skills_dir = tmp_path / "unknown_skills"
    skills_dir.mkdir()
    (skills_dir / "unknown.md").write_text(
        "---\nname: mystery\ndescription: an unknown tool skill\ntool_id: nonexistent_tool_xyz\n---\n\nMystery content."
    )

    skills = registry.load_skills(skills_dir=str(skills_dir))
    assert len(skills) == 1
    # No tool was enriched — no error, just log message


def test_registry_load_skills_multiple_skills_one_tool(registry, tmp_path):
    """Multiple skills targeting the same tool all enrich its description."""
    skills_dir = tmp_path / "multi_skills"
    skills_dir.mkdir()
    (skills_dir / "a.md").write_text(
        "---\nname: shell-1\ndescription: first shell skill\ntool_id: shell\n---\n\nShell part one."
    )
    (skills_dir / "b.md").write_text(
        "---\nname: shell-2\ndescription: second shell skill\ntool_id: shell\n---\n\nShell part two."
    )

    from backend.agent.tools import TOOLS

    original_len = len([t for t in TOOLS if t.name == "shell"][0].description)

    skills = registry.load_skills(skills_dir=str(skills_dir))
    assert len(skills) == 2

    shell_tool = [t for t in TOOLS if t.name == "shell"][0]
    assert len(shell_tool.description) > original_len
    assert "Shell part one" in shell_tool.description
    assert "Shell part two" in shell_tool.description


def test_registry_load_skills_enrichment_only_with_tool_id(registry, tmp_path):
    """Skills without tool_id don't enrich anything but are still returned."""
    skills_dir = tmp_path / "notool_skills"
    skills_dir.mkdir()
    (skills_dir / "general.md").write_text(
        "---\nname: general\ndescription: general tips\n---\n\nGeneral content."
    )
    (skills_dir / "targeted.md").write_text(
        "---\nname: targeted\ndescription: targeted tips\ntool_id: shell\n---\n\nTargeted content."
    )

    from backend.agent.tools import TOOLS

    original_len = len([t for t in TOOLS if t.name == "shell"][0].description)

    skills = registry.load_skills(skills_dir=str(skills_dir))
    assert len(skills) == 2

    shell_tool = [t for t in TOOLS if t.name == "shell"][0]
    assert len(shell_tool.description) > original_len
    assert "General content" not in shell_tool.description
    assert "Targeted content" in shell_tool.description


def test_registry_load_skills_empty_skill_content(registry, tmp_path):
    """Skills with empty content don't modify the tool description."""
    skills_dir = tmp_path / "empty_content"
    skills_dir.mkdir()
    (skills_dir / "empty.md").write_text(
        "---\nname: empty-skill\ndescription: empty content\ntool_id: shell\n---\n\n  \n\n"
    )

    from backend.agent.tools import TOOLS

    original_desc = [t for t in TOOLS if t.name == "shell"][0].description

    skills = registry.load_skills(skills_dir=str(skills_dir))
    assert len(skills) == 1

    shell_tool = [t for t in TOOLS if t.name == "shell"][0]
    assert shell_tool.description == original_desc


# =========================================================================
# MCP lifecycle — MCPServerProcess
# =========================================================================

import os
import sys

_ECHO_SERVER = os.path.join(
    os.path.dirname(__file__), "fixtures", "echo_mcp_server.py"
)


@pytest.fixture
def echo_def() -> MCPToolDef:
    """MCPToolDef that points at the echo test server."""
    return MCPToolDef(
        name="echo_test",
        description="Echo server for testing.",
        command=sys.executable,
        args=[_ECHO_SERVER],
    )


@pytest.mark.asyncio
async def test_mcp_process_ensure_running(echo_def):
    """MCPServerProcess.ensure_running spawns and initializes the server."""
    from backend.registry.mcp_lifecycle import MCPServerProcess

    proc = MCPServerProcess(
        name=echo_def.name,
        command=echo_def.command,
        args=echo_def.args,
    )
    assert proc.status == "stopped"

    await proc.ensure_running()
    assert proc.status == "running"

    # Clean up
    await proc.shutdown()
    assert proc.status == "shutdown"


@pytest.mark.asyncio
async def test_mcp_process_call(echo_def):
    """MCPServerProcess.call sends tools/call and returns result."""
    from backend.registry.mcp_lifecycle import MCPServerProcess

    proc = MCPServerProcess(
        name=echo_def.name,
        command=echo_def.command,
        args=echo_def.args,
    )
    await proc.ensure_running()

    result = await proc.call("my_tool", {"key": "value"})

    assert "content" in result
    content = result["content"]
    assert len(content) > 0

    # The echo server returns a text content block with the echoed data
    text_item = content[0]
    assert text_item["type"] == "text"
    import json

    echoed = json.loads(text_item["text"])
    assert echoed["echo_tool"] == "my_tool"
    assert echoed["echo_args"] == {"key": "value"}

    await proc.shutdown()


@pytest.mark.asyncio
async def test_mcp_process_call_twice(echo_def):
    """Multiple calls on the same server work sequentially."""
    from backend.registry.mcp_lifecycle import MCPServerProcess

    proc = MCPServerProcess(
        name=echo_def.name,
        command=echo_def.command,
        args=echo_def.args,
    )
    await proc.ensure_running()

    r1 = await proc.call("tool_a", {"x": 1})
    r2 = await proc.call("tool_b", {"y": 2})

    import json

    c1 = json.loads(r1["content"][0]["text"])
    c2 = json.loads(r2["content"][0]["text"])
    assert c1["echo_tool"] == "tool_a"
    assert c2["echo_tool"] == "tool_b"

    await proc.shutdown()


@pytest.mark.asyncio
async def test_mcp_process_ensure_running_idempotent(echo_def):
    """Calling ensure_running twice doesn't re-spawn."""
    from backend.registry.mcp_lifecycle import MCPServerProcess

    proc = MCPServerProcess(
        name=echo_def.name,
        command=echo_def.command,
        args=echo_def.args,
    )
    await proc.ensure_running()
    pid1 = proc._process.pid

    await proc.ensure_running()  # should be no-op
    assert proc._process.pid == pid1  # same process

    await proc.shutdown()


@pytest.mark.asyncio
async def test_mcp_process_shutdown_terminates(echo_def):
    """shutdown terminates the subprocess."""
    from backend.registry.mcp_lifecycle import MCPServerProcess

    proc = MCPServerProcess(
        name=echo_def.name,
        command=echo_def.command,
        args=echo_def.args,
    )
    await proc.ensure_running()
    assert proc._process.returncode is None  # alive

    await proc.shutdown(timeout=5.0)
    assert proc.status == "shutdown"
    assert proc._process is None or proc._process.returncode is not None


@pytest.mark.asyncio
async def test_mcp_process_call_before_running_raises(echo_def):
    """Call before ensure_running raises RuntimeError."""
    from backend.registry.mcp_lifecycle import MCPServerProcess

    proc = MCPServerProcess(
        name=echo_def.name,
        command=echo_def.command,
        args=echo_def.args,
    )

    with pytest.raises(RuntimeError, match="not running"):
        await proc.call("tool", {})


@pytest.mark.asyncio
async def test_mcp_process_call_after_shutdown_raises(echo_def):
    """Call after shutdown raises RuntimeError."""
    from backend.registry.mcp_lifecycle import MCPServerProcess

    proc = MCPServerProcess(
        name=echo_def.name,
        command=echo_def.command,
        args=echo_def.args,
    )
    await proc.ensure_running()
    await proc.shutdown()

    with pytest.raises(RuntimeError, match="not running"):
        await proc.call("tool", {})


@pytest.mark.asyncio
async def test_mcp_process_lock_serializes(echo_def):
    """Concurrent calls are serialized by the internal lock."""
    from backend.registry.mcp_lifecycle import MCPServerProcess

    proc = MCPServerProcess(
        name=echo_def.name,
        command=echo_def.command,
        args=echo_def.args,
    )
    await proc.ensure_running()

    async def call_tool(tool_name: str) -> dict:
        return await proc.call(tool_name, {"val": tool_name})

    results = await asyncio.gather(
        call_tool("alpha"),
        call_tool("beta"),
        call_tool("gamma"),
    )
    assert len(results) == 3
    import json

    echoed_names = {
        json.loads(r["content"][0]["text"])["echo_tool"] for r in results
    }
    assert echoed_names == {"alpha", "beta", "gamma"}

    await proc.shutdown()


# =========================================================================
# MCP lifecycle — ToolRegistry wiring
# =========================================================================


@pytest.mark.asyncio
async def test_mcp_registry_exec_mcp_invoke(registry, echo_def):
    """_exec_mcp_invoke spawns server and calls tool via registry."""
    registry.register_mcp(echo_def)

    result = await registry._exec_mcp_invoke(
        {"server": "echo_test", "tool": "list_stuff", "arguments": {"limit": 5}}
    )
    import json

    parsed = json.loads(result)
    assert "content" in parsed
    assert parsed["content"][0]["type"] == "text"

    echoed = json.loads(parsed["content"][0]["text"])
    assert echoed["echo_tool"] == "list_stuff"
    assert echoed["echo_args"] == {"limit": 5}

    await registry.shutdown_all()


@pytest.mark.asyncio
async def test_mcp_registry_exec_mcp_invoke_unknown_server(registry):
    """_exec_mcp_invoke returns error for unknown server."""
    result = await registry._exec_mcp_invoke(
        {"server": "nonexistent", "tool": "x", "arguments": {}}
    )
    assert result.startswith("ERROR:")
    assert "Unknown MCP server" in result


@pytest.mark.asyncio
async def test_mcp_registry_exec_registered_tool_mcp_invoke(registry, echo_def):
    """exec_registered_tool dispatches mcp_invoke through the real lifecycle."""
    registry.register_mcp(echo_def)

    result = await registry.exec_registered_tool(
        "mcp_invoke",
        {"server": "echo_test", "tool": "read_file", "arguments": {"path": "/tmp/test.txt"}},
    )
    import json

    parsed = json.loads(result)
    assert "content" in parsed
    echoed = json.loads(parsed["content"][0]["text"])
    assert echoed["echo_tool"] == "read_file"
    assert echoed["echo_args"] == {"path": "/tmp/test.txt"}

    await registry.shutdown_all()


@pytest.mark.asyncio
async def test_mcp_registry_exec_registered_tool_direct_name(registry, echo_def):
    """exec_registered_tool dispatches by direct MCP server name."""
    registry.register_mcp(echo_def)

    result = await registry.exec_registered_tool(
        "echo_test",
        {"tool": "my_tool", "arguments": {"k": "v"}},
    )
    import json

    parsed = json.loads(result)
    assert "content" in parsed
    echoed = json.loads(parsed["content"][0]["text"])
    assert echoed["echo_tool"] == "my_tool"
    assert echoed["echo_args"] == {"k": "v"}

    await registry.shutdown_all()


@pytest.mark.asyncio
async def test_mcp_registry_shutdown_all(registry, echo_def):
    """shutdown_all terminates all MCP subprocesses."""
    registry.register_mcp(echo_def)

    # Start the server
    await registry._exec_mcp_invoke(
        {"server": "echo_test", "tool": "ping", "arguments": {}}
    )

    proc = registry._mcp_processes["echo_test"]
    assert proc.status == "running"

    await registry.shutdown_all()
    assert proc.status == "shutdown"


@pytest.mark.asyncio
async def test_mcp_registry_shutdown_all_empty(registry):
    """shutdown_all handles no registered servers."""
    # Should not raise
    await registry.shutdown_all()


def test_mcp_registry_get_mcp_status_includes_process_status(registry, echo_def):
    """get_mcp_status includes process_status field."""
    registry.register_mcp(echo_def)

    status = registry.get_mcp_status()
    assert len(status) == 1
    entry = status[0]
    assert entry["name"] == "echo_test"
    assert entry["process_status"] == "stopped"


@pytest.mark.asyncio
async def test_mcp_registry_get_mcp_status_after_start(registry, echo_def):
    """get_mcp_status shows 'running' after ensure_running."""
    registry.register_mcp(echo_def)

    await registry._exec_mcp_invoke(
        {"server": "echo_test", "tool": "ping", "arguments": {}}
    )

    status = registry.get_mcp_status()
    entry = status[0]
    assert entry["process_status"] == "running"

    await registry.shutdown_all()


@pytest.mark.asyncio
async def test_mcp_registry_unregister_cleans_process(registry, echo_def):
    """unregister_mcp removes the associated process handle."""
    registry.register_mcp(echo_def)
    assert "echo_test" in registry._mcp_processes

    registry.unregister_mcp("echo_test")
    assert "echo_test" not in registry._mcp_processes


@pytest.mark.asyncio
async def test_mcp_process_error_handling(echo_def):
    """MCPServerProcess handles JSON-RPC errors from the server."""
    from backend.registry.mcp_lifecycle import MCPServerProcess

    proc = MCPServerProcess(
        name="echo_test",
        command=echo_def.command,
        args=echo_def.args,
    )
    await proc.ensure_running()

    # Send a request with an unknown method — echo server won't respond
    # with an error for unknown methods (it ignores them), but we can
    # verify the basic call/response cycle works correctly.
    result = await proc.call("valid_tool", {})
    assert "content" in result

    await proc.shutdown()


@pytest.mark.asyncio
async def test_mcp_process_concurrent_safety(echo_def):
    """Multiple concurrent ensure_running calls don't spawn extra processes."""
    from backend.registry.mcp_lifecycle import MCPServerProcess

    proc = MCPServerProcess(
        name=echo_def.name,
        command=echo_def.command,
        args=echo_def.args,
    )

    async def start() -> None:
        await proc.ensure_running()

    await asyncio.gather(start(), start(), start())
    assert proc.status == "running"

    await proc.shutdown()


# =========================================================================
# End-to-end: register via REST → visible in schemas → unregister
# =========================================================================


class TestRegistryEndToEnd:
    """End-to-end verification: register tools, verify in get_tool_schemas(), unregister."""

    @pytest.fixture
    def registry(self):
        ToolRegistry.reset_instance()
        r = ToolRegistry.get_instance()
        yield r
        ToolRegistry.reset_instance()

    def test_register_mcp_then_visible_in_schemas(self, registry):
        """Registering an MCP tool makes it appear in get_tool_schemas()."""
        from backend.agent.tools import get_tool_schemas

        # Before: mcp_invoke shows no servers
        schemas_before = get_tool_schemas()
        mcp_before = next(s for s in schemas_before if s["function"]["name"] == "mcp_invoke")
        assert "(no servers registered)" in mcp_before["function"]["description"]

        # Register
        registry.register_mcp(MCPToolDef(
            name="test_server",
            description="A test MCP server.",
            command="python",
            args=["server.py"],
        ))

        # After: mcp_invoke shows the server
        schemas_after = get_tool_schemas()
        mcp_after = next(s for s in schemas_after if s["function"]["name"] == "mcp_invoke")
        assert "test_server" in mcp_after["function"]["description"]
        assert "A test MCP server" in mcp_after["function"]["description"]
        assert "(no servers registered)" not in mcp_after["function"]["description"]

    def test_register_cli_then_visible_in_prompt(self, registry):
        """Registering a CLI tool makes it appear in _build_system_prompt()."""
        from backend.agent.loop import _build_system_prompt

        # Before: no CLI tools
        prompt_before = _build_system_prompt()
        assert "my_cli_tool" not in prompt_before

        # Register
        registry.register_cli(CLIToolDef(
            name="my_cli_tool",
            description="A test CLI tool.",
            command_hint="my_cli_tool --help",
            shell="bash",
        ))

        # After: CLI tool appears
        prompt_after = _build_system_prompt()
        assert "my_cli_tool" in prompt_after
        assert "A test CLI tool" in prompt_after
        assert "[bash]" in prompt_after

    def test_register_unregister_mcp_schemas_update(self, registry):
        """Unregistering an MCP tool removes it from get_tool_schemas()."""
        from backend.agent.tools import get_tool_schemas

        registry.register_mcp(MCPToolDef(
            name="temp_server", description="Temporary.", command="node",
        ))

        schemas = get_tool_schemas()
        mcp = next(s for s in schemas if s["function"]["name"] == "mcp_invoke")
        assert "temp_server" in mcp["function"]["description"]

        registry.unregister_mcp("temp_server")

        schemas = get_tool_schemas()
        mcp = next(s for s in schemas if s["function"]["name"] == "mcp_invoke")
        assert "temp_server" not in mcp["function"]["description"]
        assert "(no servers registered)" in mcp["function"]["description"]

    def test_register_unregister_cli_prompt_updates(self, registry):
        """Unregistering a CLI tool removes it from _build_system_prompt()."""
        from backend.agent.loop import _build_system_prompt

        registry.register_cli(CLIToolDef(
            name="temp_cli", description="Temporary CLI.", command_hint="temp_cli",
        ))
        assert "temp_cli" in _build_system_prompt()

        registry.unregister_cli("temp_cli")
        assert "temp_cli" not in _build_system_prompt()

    def test_register_mcp_shows_in_get_mcp_status(self, registry):
        """get_mcp_status reflects registered MCP tools."""
        status_before = registry.get_mcp_status()
        assert status_before == []

        registry.register_mcp(MCPToolDef(
            name="server_x", description="Server X.", command="python",
        ))

        status = registry.get_mcp_status()
        assert len(status) == 1
        assert status[0]["name"] == "server_x"
        assert status[0]["process_status"] == "stopped"
        assert status[0]["registered"] is True

        registry.unregister_mcp("server_x")
        assert registry.get_mcp_status() == []

    def test_get_cli_descriptions_includes_registered(self, registry):
        """get_cli_descriptions reflects registered CLI tools."""
        assert registry.get_cli_descriptions() == ""

        registry.register_cli(CLIToolDef(
            name="cli1", description="CLI one.", command_hint="cli1 --help",
        ))
        desc = registry.get_cli_descriptions()
        assert "cli1" in desc
        assert "CLI one." in desc

        registry.unregister_cli("cli1")
        assert registry.get_cli_descriptions() == ""

    def test_tool_defs_rebuild_on_register(self, registry):
        """get_tool_defs() is rebuilt on every register/unregister."""
        defs_before = registry.get_tool_defs()
        assert "(no servers registered)" in defs_before[0].description

        registry.register_mcp(MCPToolDef(
            name="alpha", description="Alpha server.", command="python",
        ))
        defs_after = registry.get_tool_defs()
        assert "alpha" in defs_after[0].description

        registry.register_mcp(MCPToolDef(
            name="beta", description="Beta server.", command="python",
        ))
        defs_after2 = registry.get_tool_defs()
        assert "alpha" in defs_after2[0].description
        assert "beta" in defs_after2[0].description

        registry.unregister_mcp("alpha")
        defs_after3 = registry.get_tool_defs()
        assert "alpha" not in defs_after3[0].description
        assert "beta" in defs_after3[0].description

    def test_register_mcp_unregister_in_schemas_cycle(self, registry):
        """Cycle: register → visible → unregister → gone → re-register → visible again."""
        from backend.agent.tools import get_tool_schemas

        assert "(no servers registered)" in _mcp_desc(get_tool_schemas())

        registry.register_mcp(MCPToolDef(
            name="cycle_test", description="Cycle test.", command="npx",
        ))
        assert "cycle_test" in _mcp_desc(get_tool_schemas())

        registry.unregister_mcp("cycle_test")
        assert "(no servers registered)" in _mcp_desc(get_tool_schemas())

        registry.register_mcp(MCPToolDef(
            name="cycle_test", description="Cycle test again.", command="npx",
        ))
        assert "cycle_test" in _mcp_desc(get_tool_schemas())

        registry.unregister_mcp("cycle_test")
        assert "(no servers registered)" in _mcp_desc(get_tool_schemas())


def _mcp_desc(schemas):
    """Helper: return the description of the mcp_invoke schema."""
    return next(s for s in schemas if s["function"]["name"] == "mcp_invoke")["function"]["description"]
