"""Tool Registry REST API.

Endpoints
---------
- GET    /api/registry/tools              — List all registered tools with status
- POST   /api/registry/tools/register     — Register an MCP or CLI tool
- DELETE /api/registry/tools/{tool_id}    — Unregister a tool by name
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.registry import CLIToolDef, MCPToolDef, ToolRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/registry", tags=["registry"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class RegisterToolRequest(BaseModel):
    """Request to register an MCP or CLI tool."""

    tool_type: str = Field(
        ...,
        pattern=r"^(mcp|cli)$",
        description="'mcp' for MCP server or 'cli' for CLI tool",
    )
    name: str = Field(..., min_length=1, description="Unique tool name")
    description: str = Field(
        ..., min_length=1, description="Human-readable description"
    )
    # MCP-specific fields
    command: str = Field(
        default="",
        description="Shell command to spawn the MCP server subprocess",
    )
    args: list[str] = Field(
        default_factory=list,
        description="Command-line arguments for the MCP subprocess",
    )
    env_vars: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables for the MCP subprocess",
    )
    # CLI-specific fields
    command_hint: str = Field(
        default="", description="Example CLI invocation for the system prompt"
    )
    shell: Optional[str] = Field(
        default=None,
        description="Shell for the CLI tool (cmd, powershell, bash)",
    )


class ToolStatusItem(BaseModel):
    """Single tool entry in the listing response."""

    name: str
    type: str  # "mcp" or "cli"
    description: str
    # MCP fields
    command: str = ""
    args: list[str] = []
    env_var_names: list[str] = Field(
        default_factory=list,
        description="Environment variable names (values redacted)",
    )
    # CLI fields
    command_hint: str = ""
    shell: Optional[str] = None
    # Status
    process_status: str = ""
    registered: bool = True


class ToolsListResponse(BaseModel):
    """Response for GET /api/registry/tools."""

    tools: list[ToolStatusItem]


class RegisterToolResponse(BaseModel):
    """Response after successful tool registration."""

    message: str
    tool: ToolStatusItem


class UnregisterToolResponse(BaseModel):
    """Response after successful tool unregistration."""

    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/tools", response_model=ToolsListResponse)
async def list_registered_tools():
    """List all registered MCP and CLI tools with their status.

    Returns per-tool metadata including the process lifecycle state for
    MCP servers (``stopped`` / ``running`` / ``errored`` / ``shutdown``)
    and ``available`` for CLI tools.  Environment variable values are
    **never** included — only key names appear in ``env_var_names``.
    """
    registry = ToolRegistry.get_instance()

    items: list[ToolStatusItem] = []

    # MCP tools — get_mcp_status() returns per-server registration info
    for entry in registry.get_mcp_status():
        mcp_tool = registry.get_mcp(entry["name"])
        items.append(
            ToolStatusItem(
                name=entry["name"],
                type="mcp",
                description=entry["description"],
                command=entry.get("command", ""),
                args=entry.get("args", []),
                env_var_names=list(mcp_tool.env_vars.keys()) if mcp_tool else [],
                process_status=entry.get("process_status", ""),
                registered=True,
            )
        )

    # CLI tools
    for cli in registry.list_cli():
        items.append(
            ToolStatusItem(
                name=cli.name,
                type="cli",
                description=cli.description,
                command_hint=cli.command_hint,
                shell=cli.shell,
                process_status="available",
                registered=True,
            )
        )

    return ToolsListResponse(tools=items)


@router.post("/tools/register", response_model=RegisterToolResponse, status_code=201)
async def register_tool(payload: RegisterToolRequest):
    """Register an MCP or CLI tool in the registry.

    For ``tool_type: "mcp"`` the ``command`` field is required and defines
    how to spawn the server subprocess.  ``args`` and ``env_vars`` are
    optional.

    For ``tool_type: "cli"`` the ``command_hint`` provides an example
    invocation the agent can copy into its system prompt.

    Returns the registered tool's status metadata.
    """
    registry = ToolRegistry.get_instance()

    if payload.tool_type == "mcp":
        if not payload.command:
            raise HTTPException(
                status_code=400,
                detail="'command' is required for MCP tool registration.",
            )
        tool = MCPToolDef(
            name=payload.name,
            description=payload.description,
            command=payload.command,
            args=payload.args,
            env_vars=payload.env_vars,
        )
        registry.register_mcp(tool)
        status_entry = ToolStatusItem(
            name=tool.name,
            type="mcp",
            description=tool.description,
            command=tool.command,
            args=tool.args,
            env_var_names=list(tool.env_vars.keys()),
            process_status="stopped",
            registered=True,
        )
    else:
        tool = CLIToolDef(
            name=payload.name,
            description=payload.description,
            command_hint=payload.command_hint,
            shell=payload.shell,
        )
        registry.register_cli(tool)
        status_entry = ToolStatusItem(
            name=tool.name,
            type="cli",
            description=tool.description,
            command_hint=tool.command_hint,
            shell=tool.shell,
            process_status="available",
            registered=True,
        )

    logger.info("Registered tool '%s' via API (%s)", payload.name, payload.tool_type)
    return RegisterToolResponse(
        message=f"Tool '{payload.name}' registered successfully.",
        tool=status_entry,
    )


@router.delete("/tools/{tool_id}", response_model=UnregisterToolResponse)
async def unregister_tool(tool_id: str):
    """Unregister a tool by its unique name.

    Searches both the MCP and CLI pools.  Returns 404 if the tool is not
    found in either.
    """
    registry = ToolRegistry.get_instance()

    if registry.unregister_mcp(tool_id):
        logger.info("Unregistered MCP tool '%s' via API", tool_id)
        return UnregisterToolResponse(
            message=f"MCP tool '{tool_id}' unregistered."
        )

    if registry.unregister_cli(tool_id):
        logger.info("Unregistered CLI tool '%s' via API", tool_id)
        return UnregisterToolResponse(
            message=f"CLI tool '{tool_id}' unregistered."
        )

    raise HTTPException(
        status_code=404,
        detail=f"Tool '{tool_id}' not found in registry.",
    )
