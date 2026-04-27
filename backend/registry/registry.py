"""The ``ToolRegistry`` singleton — registers, lists, and describes tools.

The registry maintains two pools of runtime-discovered tools:

- **MCP servers** — spawned as subprocesses that speak JSON-RPC.
- **CLI tools** — documented in the system prompt as textual descriptions.

It also generates a dynamic ``mcp_invoke`` ``ToolDef`` whose description
reflects the currently registered MCP servers, and a ``shutdown_all()``
placeholder for MCP lifecycle management.

Skills (loaded from ``skills/*.md``) can enrich existing tool descriptions
with usage patterns and best practices.  ``load_skills()`` calls the
``skill_loader`` module and applies enrichments to matching tools.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from backend.agent.tools import ToolDef
from backend.registry.models import CLIToolDef, MCPToolDef, SkillDef

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Singleton registry for MCP and CLI tool definitions.

    Usage::

        registry = ToolRegistry.get_instance()
        registry.register_mcp(mcp_def)
        registry.register_cli(cli_def)
        tool_defs = registry.get_tool_defs()  # includes mcp_invoke
        cli_text = registry.get_cli_descriptions()
    """

    _instance: Optional[ToolRegistry] = None

    def __init__(self) -> None:
        self._mcp_tools: dict[str, MCPToolDef] = {}
        self._cli_tools: dict[str, CLIToolDef] = {}
        self._mcp_invoke_tool: Optional[ToolDef] = None
        self._rebuild_invoke_tool()

    # -------------------------------------------------------------------
    # Singleton
    # -------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> ToolRegistry:
        """Return the singleton registry, creating it on first call."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Clear the singleton (useful for testing)."""
        cls._instance = None

    # -------------------------------------------------------------------
    # MCP tool management
    # -------------------------------------------------------------------

    def register_mcp(self, tool: MCPToolDef) -> None:
        """Register an MCP server definition.

        If a tool with the same *name* already exists it is replaced.
        The ``mcp_invoke`` ``ToolDef`` description is rebuilt to reflect
        the updated list.
        """
        self._mcp_tools[tool.name] = tool
        self._rebuild_invoke_tool()
        logger.info("Registered MCP tool '%s'", tool.name)

    def unregister_mcp(self, name: str) -> bool:
        """Remove a registered MCP server by *name*.

        Returns ``True`` if the tool existed and was removed, ``False``
        if no tool with that name was found.
        """
        if name in self._mcp_tools:
            del self._mcp_tools[name]
            self._rebuild_invoke_tool()
            logger.info("Unregistered MCP tool '%s'", name)
            return True
        return False

    def get_mcp(self, name: str) -> Optional[MCPToolDef]:
        """Look up a registered MCP server by *name*.

        Returns the ``MCPToolDef`` or ``None``.
        """
        return self._mcp_tools.get(name)

    def list_mcp(self) -> list[MCPToolDef]:
        """Return all registered MCP server definitions."""
        return list(self._mcp_tools.values())

    def get_mcp_status(self) -> list[dict[str, Any]]:
        """Return per-server status information.

        For T01 this returns basic registration state.
        T04 will enrich this with subprocess lifecycle status.
        """
        return [
            {
                "name": t.name,
                "description": t.description,
                "command": t.command,
                "registered": True,
            }
            for t in self._mcp_tools.values()
        ]

    # -------------------------------------------------------------------
    # CLI tool management
    # -------------------------------------------------------------------

    def register_cli(self, tool: CLIToolDef) -> None:
        """Register a CLI tool definition.

        If a tool with the same *name* already exists it is replaced.
        """
        self._cli_tools[tool.name] = tool
        logger.info("Registered CLI tool '%s'", tool.name)

    def unregister_cli(self, name: str) -> bool:
        """Remove a registered CLI tool by *name*.

        Returns ``True`` if the tool existed and was removed, ``False``
        otherwise.
        """
        if name in self._cli_tools:
            del self._cli_tools[name]
            logger.info("Unregistered CLI tool '%s'", name)
            return True
        return False

    def get_cli(self, name: str) -> Optional[CLIToolDef]:
        """Look up a registered CLI tool by *name*."""
        return self._cli_tools.get(name)

    def list_cli(self) -> list[CLIToolDef]:
        """Return all registered CLI tool definitions."""
        return list(self._cli_tools.values())

    # -------------------------------------------------------------------
    # Skill enrichment
    # -------------------------------------------------------------------

    def load_skills(self, skills_dir: str = "skills") -> list[SkillDef]:
        """Discover, parse, and apply skill enrichments from markdown files.

        Reads ``skills/*.md`` via ``skill_loader.load_skills()``, then
        enriches any ``ToolDef`` whose name matches a skill's ``tool_id``
        by appending the skill's content to the tool description.

        Parameters
        ----------
        skills_dir:
            Directory path containing ``*.md`` skill files (default: ``"skills"``).

        Returns
        -------
        list[SkillDef]
            All loaded skill definitions (not just the ones that enriched
            a tool).
        """
        from backend.registry.skill_loader import load_skills as _load_skills

        skills = _load_skills(skills_dir=skills_dir)
        self._enrich_tools_with_skills(skills)
        return skills

    def _enrich_tools_with_skills(self, skills: list[SkillDef]) -> None:
        """Enrich static ``ToolDef`` descriptions with skill content.

        For each skill that has a ``tool_id`` matching a static tool name,
        append the skill's markdown content (prefixed with a heading) to
        the tool's description.
        """
        # Build a lookup of static tools by name
        static_tools: dict[str, ToolDef] = {}
        try:
            from backend.agent.tools import TOOLS as _STATIC_TOOLS

            for t in _STATIC_TOOLS:
                static_tools[t.name] = t
        except Exception:
            logger.debug("Cannot import static TOOLS for skill enrichment")
            return

        for skill in skills:
            if not skill.tool_id:
                continue
            target = static_tools.get(skill.tool_id)
            if target is None:
                logger.debug(
                    "Skill '%s' references unknown tool_id '%s' — skipping enrichment.",
                    skill.name,
                    skill.tool_id,
                )
                continue
            if not skill.content.strip():
                continue

            enrichment = f"\n\n---\n\n**Skill: {skill.name}**\n\n{skill.content.strip()}"
            target.description += enrichment
            logger.debug(
                "Enriched tool '%s' with skill '%s' (%d chars added)",
                target.name,
                skill.name,
                len(enrichment),
            )

    # -------------------------------------------------------------------
    # ToolDef generation
    # -------------------------------------------------------------------

    def _rebuild_invoke_tool(self) -> None:
        """Rebuild the dynamic ``mcp_invoke`` ``ToolDef``.

        The description lists all registered MCP servers so the agent
        knows which servers it can address.
        """
        server_list = self._build_server_summary()

        description = (
            "Call a tool on a registered MCP (Model Context Protocol) server. "
            "MCP servers provide specialized capabilities for reverse engineering, "
            "binary analysis, and external service access."
        )
        if server_list:
            description += f"\n\nAvailable servers:\n{server_list}"

        self._mcp_invoke_tool = ToolDef(
            name="mcp_invoke",
            description=description,
            input_schema={
                "type": "object",
                "properties": {
                    "server": {
                        "type": "string",
                        "description": "Name of the MCP server to invoke.",
                    },
                    "tool": {
                        "type": "string",
                        "description": "Name of the tool on the target server.",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments to pass to the tool (key-value pairs).",
                        "default": {},
                    },
                },
                "required": ["server", "tool"],
            },
            async_execute=self._exec_mcp_invoke,
        )

    def _build_server_summary(self) -> str:
        """Build a formatted summary of registered MCP servers."""
        if not self._mcp_tools:
            return "  (no servers registered)"
        lines: list[str] = []
        for name in sorted(self._mcp_tools):
            tool = self._mcp_tools[name]
            lines.append(f"  - {name}: {tool.description}")
        return "\n".join(lines)

    def get_tool_defs(self) -> list[ToolDef]:
        """Return the dynamic tool definitions (currently ``[mcp_invoke]``).

        These are appended to the static tools from
        ``backend.agent.tools.get_tool_schemas()``.
        """
        return [self._mcp_invoke_tool] if self._mcp_invoke_tool else []

    def get_cli_descriptions(self) -> str:
        """Return formatted CLI tool descriptions for the system prompt.

        Returns an empty string if no CLI tools are registered.
        """
        if not self._cli_tools:
            return ""

        lines: list[str] = ["Available CLI tools:"]
        for name in sorted(self._cli_tools):
            tool = self._cli_tools[name]
            shell_info = f" [{tool.shell}]" if tool.shell else ""
            lines.append(f"  - {name}{shell_info}: {tool.description}")
            if tool.command_hint:
                lines.append(f"    Example: {tool.command_hint}")
        return "\n".join(lines)

    # -------------------------------------------------------------------
    # Execution dispatch (placeholder — T04 wires MCP lifecycle)
    # -------------------------------------------------------------------

    async def _exec_mcp_invoke(
        self, args: dict[str, Any], engine: Any = None
    ) -> str:
        """Execute a tool on a registered MCP server.

        This is the ``async_execute`` callable for the ``mcp_invoke``
        ``ToolDef``.  At T01 it validates inputs and returns a placeholder
        result.  T04 replaces this with actual JSON-RPC subprocess calls.
        """
        server_name: str = args.get("server", "")
        tool_name: str = args.get("tool", "")
        tool_args: dict[str, Any] = args.get("arguments", {})

        if server_name not in self._mcp_tools:
            available = ", ".join(sorted(self._mcp_tools))
            return (
                f"ERROR: Unknown MCP server '{server_name}'. "
                f"Available servers: {available or '(none)'}"
            )

        # T04: actual MCP subprocess lifecycle and JSON-RPC dispatch
        return (
            f"MCP tool dispatch not yet implemented (T04). "
            f"Would call '{tool_name}' on server '{server_name}' "
            f"with arguments: {tool_args}"
        )

    async def exec_registered_tool(
        self, name: str, args: dict[str, Any], engine: Any = None
    ) -> str:
        """Execute a tool by *name* through the registry.

        Called by ``backend.agent.tools.execute_tool_call()`` when the
        name doesn't match a static tool.  Currently a placeholder that
        delegates to the ``mcp_invoke`` handler when ``name == "mcp_invoke"``.

        T04 extends this to support direct MCP tool dispatch.
        """
        if name == "mcp_invoke":
            return await self._exec_mcp_invoke(args, engine)

        # Check MCP tools by name
        if name in self._mcp_tools:
            mcp = self._mcp_tools[name]
            return (
                f"MCP tool '{name}' dispatch not yet implemented (T04). "
                f"Would invoke '{mcp.name}' server."
            )

        return f"ERROR: Unknown registered tool '{name}'."

    # -------------------------------------------------------------------
    # Lifecycle (placeholder — T04 wires real MCP subprocess shutdown)
    # -------------------------------------------------------------------

    async def shutdown_all(self) -> None:
        """Shut down all registered MCP server subprocesses.

        T01: no-op placeholder.
        T04: iterates ``MCPServerProcess`` instances, sends shutdown
        JSON-RPC, waits for termination with per-server timeout.
        """
        logger.info("ToolRegistry.shutdown_all() called — no-op at T01")
