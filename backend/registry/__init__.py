"""Tool registry package — dynamic tool registration for MCP and CLI tools.

The ``ToolRegistry`` singleton maintains runtime tool definitions that can
be discovered by the agent loop and injected into the system prompt.
"""

from backend.registry.models import CLIToolDef, MCPToolDef, SkillDef
from backend.registry.registry import ToolRegistry

__all__ = [
    "CLIToolDef",
    "MCPToolDef",
    "SkillDef",
    "ToolRegistry",
]
