"""Data models for the tool registry.

These dataclasses define the shape of registered tools — MCP servers,
CLI helpers, and skill enrichments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MCPToolDef:
    """Definition of an MCP (Model Context Protocol) server tool.

    Attributes
    ----------
    name:
        Unique server name used by the agent to address it via ``mcp_invoke``.
    description:
        Human-readable description of what this MCP server provides.
    command:
        Shell command to spawn the MCP server subprocess
        (e.g. ``"npx"``, ``"python"``, ``"node"``).
    args:
        Command-line arguments for the subprocess.
    env_vars:
        Optional environment variables to pass to the subprocess.
        Values may contain secrets (API keys, tokens).
    """

    name: str
    description: str
    command: str
    args: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)


@dataclass
class CLIToolDef:
    """Definition of a command-line tool available to the agent.

    CLI tools are documented in the system prompt as textual descriptions
    rather than function schemas, since they don't follow a structured
    invocation protocol.

    Attributes
    ----------
    name:
        Short identifier (e.g. ``"ida"``, ``"ghidra"``).
    description:
        What the tool does and when to use it.
    command_hint:
        Example command-line invocation(s) the agent can copy.
    shell:
        Shell to use (``"cmd"``, ``"powershell"``, ``"bash"``).
        Defaults to the system default shell.
    """

    name: str
    description: str
    command_hint: str
    shell: Optional[str] = None


@dataclass
class SkillDef:
    """Definition of a loaded skill — a ``skills/*.md`` document.

    Skills enrich existing tool descriptions with usage patterns,
    best practices, and contextual guidance.

    Attributes
    ----------
    name:
        Skill name (from YAML frontmatter).
    description:
        Brief summary of what the skill covers.
    tool_id:
        Optional ``ToolDef.name`` this skill enriches.
        If set, the skill's content is appended to that tool's description.
    command_hint:
        Optional example command associated with this skill.
    content:
        Full markdown body of the skill file (minus frontmatter).
    """

    name: str
    description: str
    tool_id: Optional[str] = None
    command_hint: Optional[str] = None
    content: str = ""
