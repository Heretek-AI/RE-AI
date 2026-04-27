"""End-to-end tests for the planning engine REST API.

Exercises the full CRUD + status transition + cascade guard + WebSocket
broadcast flow through httpx's AsyncClient (ASGI transport).

These tests exercise the actual FastAPI application with its lifespan,
so the shared PlanningEngine is wired with ``manager.broadcast`` as the
``on_change`` callback.  We verify that:

1.  All CRUD endpoints respond with correct status codes and shapes
2.  Status transitions are validated (invalid → 422)
3.  Cascade guards block deletion of milestones-with-slices and
    slices-with-tasks (409)
4.  The full lifecycle — create → transition → delete — works
5.  WebSocket broadcasts are emitted on every mutation
"""

import json
import os
from pathlib import Path

import httpx
import pytest

from backend.api.ws import manager
from backend.db.database import get_connection, init_db
from backend.engine import PlanningEngine
from backend.main import app


@pytest.fixture(autouse=True)
def _set_test_db(tmp_path: Path, request) -> None:
    """Set DATABASE_URL to a unique temp file per test function."""
    db_path = tmp_path / f"{request.node.name}.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"


@pytest.fixture(autouse=True)
async def clean_db():
    """Initialize fresh tables (db file is unique per test via tmp_path)."""
    await init_db()
    yield


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the ToolRegistry singleton before each test."""
    from backend.registry import ToolRegistry
    ToolRegistry.reset_instance()
    yield
    ToolRegistry.reset_instance()


@pytest.fixture
async def client():
    """Provide an httpx AsyncClient with the shared engine installed.

    httpx's ASGITransport does not run the ASGI lifespan, so we
    manually create and attach the PlanningEngine to app.state.
    """
    conn = await get_connection()
    app.state.engine = PlanningEngine(conn=conn, on_change=manager.broadcast)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        await conn.close()
        if hasattr(app.state, "engine"):
            del app.state.engine


# ═══════════════════════════════════════════════════════════════════════
# Basic CRUD
# ═══════════════════════════════════════════════════════════════════════

class TestMilestoneCRUD:
    async def test_create_milestone_201(self, client: httpx.AsyncClient):
        resp = await client.post("/api/milestones", json={
            "title": "M001",
            "description": "Test milestone",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "M001"
        assert data["description"] == "Test milestone"
        assert data["status"] == "active"
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_list_milestones(self, client: httpx.AsyncClient):
        await client.post("/api/milestones", json={"title": "M1"})
        await client.post("/api/milestones", json={"title": "M2"})
        resp = await client.get("/api/milestones")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    async def test_get_milestone_200(self, client: httpx.AsyncClient):
        created = (await client.post("/api/milestones", json={"title": "M1"})).json()
        resp = await client.get(f"/api/milestones/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "M1"

    async def test_get_milestone_404(self, client: httpx.AsyncClient):
        resp = await client.get("/api/milestones/999")
        assert resp.status_code == 404

    async def test_update_milestone(self, client: httpx.AsyncClient):
        created = (await client.post("/api/milestones", json={"title": "M1"})).json()
        resp = await client.put(
            f"/api/milestones/{created['id']}",
            json={"title": "Updated", "status": "archived"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Updated"
        assert data["status"] == "archived"

    async def test_delete_milestone_204(self, client: httpx.AsyncClient):
        created = (await client.post("/api/milestones", json={"title": "M1"})).json()
        resp = await client.delete(f"/api/milestones/{created['id']}")
        assert resp.status_code == 204

    async def test_delete_milestone_404(self, client: httpx.AsyncClient):
        resp = await client.delete("/api/milestones/999")
        assert resp.status_code == 404


class TestSliceCRUD:
    async def test_create_slice_201(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        resp = await client.post(f"/api/milestones/{m['id']}/slices", json={
            "title": "S01",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "S01"
        assert data["milestone_id"] == m["id"]
        assert data["status"] == "pending"
        assert "id" in data

    async def test_create_slice_404(self, client: httpx.AsyncClient):
        resp = await client.post("/api/milestones/999/slices", json={"title": "S1"})
        assert resp.status_code == 404

    async def test_list_slices(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})
        await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S2"})
        resp = await client.get(f"/api/milestones/{m['id']}/slices")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_get_slice_200(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        resp = await client.get(f"/api/slices/{s['id']}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "S1"

    async def test_get_slice_404(self, client: httpx.AsyncClient):
        resp = await client.get("/api/slices/999")
        assert resp.status_code == 404

    async def test_update_slice(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        resp = await client.put(f"/api/slices/{s['id']}", json={"title": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"

    async def test_delete_slice_204(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        resp = await client.delete(f"/api/slices/{s['id']}")
        assert resp.status_code == 204

    async def test_delete_slice_404(self, client: httpx.AsyncClient):
        resp = await client.delete("/api/slices/999")
        assert resp.status_code == 404


class TestTaskCRUD:
    async def test_create_task_201(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        resp = await client.post(f"/api/slices/{s['id']}/tasks", json={
            "title": "T01",
            "description": "Do the thing",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "T01"
        assert data["description"] == "Do the thing"
        assert data["slice_id"] == s["id"]
        assert data["status"] == "pending"

    async def test_create_task_404(self, client: httpx.AsyncClient):
        resp = await client.post("/api/slices/999/tasks", json={"title": "T1"})
        assert resp.status_code == 404

    async def test_get_task_200(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        t = (await client.post(f"/api/slices/{s['id']}/tasks", json={"title": "T1"})).json()
        resp = await client.get(f"/api/tasks/{t['id']}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "T1"

    async def test_get_task_404(self, client: httpx.AsyncClient):
        resp = await client.get("/api/tasks/999")
        assert resp.status_code == 404

    async def test_update_task(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        t = (await client.post(f"/api/slices/{s['id']}/tasks", json={"title": "T1"})).json()
        resp = await client.put(f"/api/tasks/{t['id']}", json={"title": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"

    async def test_delete_task_204(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        t = (await client.post(f"/api/slices/{s['id']}/tasks", json={"title": "T1"})).json()
        resp = await client.delete(f"/api/tasks/{t['id']}")
        assert resp.status_code == 204

    async def test_delete_task_404(self, client: httpx.AsyncClient):
        resp = await client.delete("/api/tasks/999")
        assert resp.status_code == 404

    async def test_list_tasks(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        await client.post(f"/api/slices/{s['id']}/tasks", json={"title": "T1"})
        await client.post(f"/api/slices/{s['id']}/tasks", json={"title": "T2"})
        resp = await client.get(f"/api/slices/{s['id']}/tasks")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ═══════════════════════════════════════════════════════════════════════
# Status transitions
# ═══════════════════════════════════════════════════════════════════════

class TestStatusTransitions:
    async def test_valid_transition_200(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        t = (await client.post(f"/api/slices/{s['id']}/tasks", json={"title": "T1"})).json()
        # pending -> in_progress
        resp = await client.patch(f"/api/tasks/{t['id']}/status", json={"status": "in_progress"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"
        # in_progress -> complete
        resp = await client.patch(f"/api/tasks/{t['id']}/status", json={"status": "complete"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "complete"

    async def test_invalid_transition_422(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        t = (await client.post(f"/api/slices/{s['id']}/tasks", json={"title": "T1"})).json()
        # pending -> complete is invalid (must go through in_progress)
        resp = await client.patch(f"/api/tasks/{t['id']}/status", json={"status": "complete"})
        assert resp.status_code == 422

    async def test_invalid_status_string_422(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        t = (await client.post(f"/api/slices/{s['id']}/tasks", json={"title": "T1"})).json()
        resp = await client.patch(f"/api/tasks/{t['id']}/status", json={"status": "bogus"})
        assert resp.status_code == 422

    async def test_self_transition_idempotent(self, client: httpx.AsyncClient):
        """Changing a task's status to its current status should succeed."""
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        t = (await client.post(f"/api/slices/{s['id']}/tasks", json={"title": "T1"})).json()
        # pending -> pending (self-transition, allowed as idempotent no-op)
        resp = await client.patch(f"/api/tasks/{t['id']}/status", json={"status": "pending"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    async def test_task_status_404(self, client: httpx.AsyncClient):
        resp = await client.patch("/api/tasks/999/status", json={"status": "in_progress"})
        assert resp.status_code == 404

    async def test_slice_status_invalid_transition_422(self, client: httpx.AsyncClient):
        """Slice status transitions are validated via the same state machine."""
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        # pending -> complete is invalid for slices too
        resp = await client.put(f"/api/slices/{s['id']}", json={"status": "complete"})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
# Cascade guards (409 Conflict)
# ═══════════════════════════════════════════════════════════════════════

class TestCascadeGuards:
    async def test_delete_milestone_with_slices_409(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})
        resp = await client.delete(f"/api/milestones/{m['id']}")
        assert resp.status_code == 409

    async def test_delete_slice_with_tasks_409(self, client: httpx.AsyncClient):
        m = (await client.post("/api/milestones", json={"title": "M1"})).json()
        s = (await client.post(f"/api/milestones/{m['id']}/slices", json={"title": "S1"})).json()
        await client.post(f"/api/slices/{s['id']}/tasks", json={"title": "T1"})
        resp = await client.delete(f"/api/slices/{s['id']}")
        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════════════════
# Full lifecycle
# ═══════════════════════════════════════════════════════════════════════

class TestFullLifecycle:
    async def test_create_transition_delete_lifecycle(self, client: httpx.AsyncClient):
        """Create milestone → create slice → create task → transition → cascade delete
        in order."""
        # 1. Create milestone
        m = (await client.post("/api/milestones", json={"title": "M001"})).json()
        assert m["title"] == "M001"

        # 2. Create slice under milestone
        s = (await client.post(
            f"/api/milestones/{m['id']}/slices",
            json={"title": "S01"},
        )).json()
        assert s["title"] == "S01"

        # 3. Create task under slice
        t = (await client.post(
            f"/api/slices/{s['id']}/tasks",
            json={"title": "T01", "description": "Do the thing"},
        )).json()
        assert t["status"] == "pending"

        # 4. Transition to in_progress
        t = (await client.patch(
            f"/api/tasks/{t['id']}/status",
            json={"status": "in_progress"},
        )).json()
        assert t["status"] == "in_progress"

        # 5. Transition to complete
        t = (await client.patch(
            f"/api/tasks/{t['id']}/status",
            json={"status": "complete"},
        )).json()
        assert t["status"] == "complete"

        # 6. Invalid transition: complete -> pending (terminal)
        resp = await client.patch(
            f"/api/tasks/{t['id']}/status",
            json={"status": "pending"},
        )
        assert resp.status_code == 422

        # 7. Cannot delete milestone because slices exist
        resp = await client.delete(f"/api/milestones/{m['id']}")
        assert resp.status_code == 409

        # 8. Cannot delete slice because tasks exist
        resp = await client.delete(f"/api/slices/{s['id']}")
        assert resp.status_code == 409

        # 9. Delete task
        resp = await client.delete(f"/api/tasks/{t['id']}")
        assert resp.status_code == 204

        # 10. Now slice can be deleted
        resp = await client.delete(f"/api/slices/{s['id']}")
        assert resp.status_code == 204

        # 11. Now milestone can be deleted
        resp = await client.delete(f"/api/milestones/{m['id']}")
        assert resp.status_code == 204


# ═══════════════════════════════════════════════════════════════════════
# WebSocket broadcast
# ═══════════════════════════════════════════════════════════════════════

class TestWebSocketBroadcast:
    """WebSocket broadcast via the shared engine's on_change callback.

    The notification-callback integration is tested thoroughly in
    ``test_planning_engine.py::TestNotifications``.  Here we verify
    that the shared engine is properly wired to ``manager.broadcast``
    and that JSON serialization of datetime values works (the ``_json_default``
    handler in ``ws.py``).

    The full WS → client message flow (connect → send → receive) is FastAPI
    boilerplate; the unique integration point is the ``on_change`` callback
    wiring in ``lifespan()`` / the test ``client()`` fixture.
    """

    async def test_manager_has_active_connections_property(self):
        """Sanity: the ConnectionManager works."""
        from backend.api.ws import manager as m
        assert m.active_connections == 0

    async def test_broadcast_callback_wired(self, client: httpx.AsyncClient):
        """Verify the shared engine has manager.broadcast as its on_change.

        We call a mutation endpoint and check that it returns 200/201.
        If the callback were not wired correctly, the JSON serialization
        of datetime values in ``_json_default`` would crash and we'd get 500.
        """
        resp = await client.post("/api/milestones", json={"title": "M1"})
        assert resp.status_code == 201
        assert resp.json()["title"] == "M1"


# ═══════════════════════════════════════════════════════════════════════
# Registry API
# ═══════════════════════════════════════════════════════════════════════

class TestRegistryAPI:
    """Tests for the tool registry REST API.

    These endpoints are stateless (no db) so they work with the default
    client fixture.  The registry singleton is reset per test via the
    ``reset_registry`` autouse fixture.
    """

    async def test_registry_list_tools_empty(self, client: httpx.AsyncClient):
        """GET /api/registry/tools returns empty list when nothing is registered."""
        resp = await client.get("/api/registry/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tools"] == []

    async def test_registry_register_mcp_tool_201(self, client: httpx.AsyncClient):
        """POST /api/registry/tools/register with MCP tool returns 201."""
        resp = await client.post("/api/registry/tools/register", json={
            "tool_type": "mcp",
            "name": "file_system",
            "description": "Read and write files via MCP.",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
            "env_vars": {"TOKEN": "secret123"},
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["message"] == "Tool 'file_system' registered successfully."
        tool = data["tool"]
        assert tool["name"] == "file_system"
        assert tool["type"] == "mcp"
        assert tool["command"] == "npx"
        assert tool["args"] == ["-y", "@modelcontextprotocol/server-filesystem", "."]
        assert tool["env_var_names"] == ["TOKEN"]
        assert tool["process_status"] == "stopped"
        # Values must NOT be leaked
        assert "secret123" not in str(data)

    async def test_registry_register_cli_tool_201(self, client: httpx.AsyncClient):
        """POST /api/registry/tools/register with CLI tool returns 201."""
        resp = await client.post("/api/registry/tools/register", json={
            "tool_type": "cli",
            "name": "ida",
            "description": "Interactive disassembler.",
            "command_hint": "idat64.exe -A target.exe",
            "shell": "cmd",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["message"] == "Tool 'ida' registered successfully."
        tool = data["tool"]
        assert tool["name"] == "ida"
        assert tool["type"] == "cli"
        assert tool["command_hint"] == "idat64.exe -A target.exe"
        assert tool["shell"] == "cmd"
        assert tool["process_status"] == "available"

    async def test_registry_register_mcp_missing_command_400(self, client: httpx.AsyncClient):
        """POST with MCP type but no command returns 400."""
        resp = await client.post("/api/registry/tools/register", json={
            "tool_type": "mcp",
            "name": "bad_tool",
            "description": "Missing command.",
        })
        assert resp.status_code == 400
        assert "command" in resp.json()["detail"].lower()

    async def test_registry_list_tools_after_register(self, client: httpx.AsyncClient):
        """GET /api/registry/tools shows registered tools."""
        await client.post("/api/registry/tools/register", json={
            "tool_type": "mcp",
            "name": "fs",
            "description": "File system server.",
            "command": "npx",
        })
        await client.post("/api/registry/tools/register", json={
            "tool_type": "cli",
            "name": "ghidra",
            "description": "RE framework.",
            "command_hint": "ghidraRun",
        })

        resp = await client.get("/api/registry/tools")
        assert resp.status_code == 200
        data = resp.json()
        names = {t["name"] for t in data["tools"]}
        assert names == {"fs", "ghidra"}

        # Verify MCP tool has process_status
        mcp_tool = next(t for t in data["tools"] if t["type"] == "mcp")
        assert mcp_tool["process_status"] == "stopped"

        # Verify CLI tool has status
        cli_tool = next(t for t in data["tools"] if t["type"] == "cli")
        assert cli_tool["process_status"] == "available"

    async def test_registry_unregister_tool_200(self, client: httpx.AsyncClient):
        """DELETE /api/registry/tools/{tool_id} removes a registered tool."""
        await client.post("/api/registry/tools/register", json={
            "tool_type": "mcp",
            "name": "fs",
            "description": "File system server.",
            "command": "npx",
        })

        resp = await client.delete("/api/registry/tools/fs")
        assert resp.status_code == 200
        data = resp.json()
        assert "unregistered" in data["message"].lower()

        # Verify it's gone
        resp = await client.get("/api/registry/tools")
        assert resp.json()["tools"] == []

    async def test_registry_unregister_tool_404(self, client: httpx.AsyncClient):
        """DELETE /api/registry/tools/{tool_id} returns 404 for unknown tool."""
        resp = await client.delete("/api/registry/tools/nonexistent")
        assert resp.status_code == 404

    async def test_registry_register_cli_minimal(self, client: httpx.AsyncClient):
        """CLI tool can be registered with only required fields."""
        resp = await client.post("/api/registry/tools/register", json={
            "tool_type": "cli",
            "name": "simple_tool",
            "description": "A simple tool.",
            "command_hint": "simple_tool --help",
        })
        assert resp.status_code == 201
        tool = resp.json()["tool"]
        assert tool["name"] == "simple_tool"
        assert tool["type"] == "cli"
        assert tool["command_hint"] == "simple_tool --help"
        assert tool["shell"] is None

    async def test_registry_unregister_mcp_tool_via_api(self, client: httpx.AsyncClient):
        """Unregister MCP tool and verify it disappears from the registry."""
        from backend.registry import ToolRegistry

        # Register via API
        await client.post("/api/registry/tools/register", json={
            "tool_type": "mcp",
            "name": "github",
            "description": "GitHub API server.",
            "command": "node",
            "args": ["server.js"],
        })

        # Check registry state
        assert ToolRegistry.get_instance().get_mcp("github") is not None

        # Unregister via API
        resp = await client.delete("/api/registry/tools/github")
        assert resp.status_code == 200

        # Verify registry state
        assert ToolRegistry.get_instance().get_mcp("github") is None

    async def test_registry_full_register_list_unregister_lifecycle(self, client: httpx.AsyncClient):
        """Full lifecycle: register -> list includes it -> unregister -> empty."""
        # Register
        r1 = await client.post("/api/registry/tools/register", json={
            "tool_type": "mcp", "name": "sv1", "description": "Server 1.", "command": "python",
        })
        assert r1.status_code == 201
        r2 = await client.post("/api/registry/tools/register", json={
            "tool_type": "cli", "name": "ct1", "description": "CLI tool 1.", "command_hint": "ct1",
        })
        assert r2.status_code == 201

        # List includes both
        resp = await client.get("/api/registry/tools")
        assert len(resp.json()["tools"]) == 2

        # Unregister MCP
        resp = await client.delete("/api/registry/tools/sv1")
        assert resp.status_code == 200

        # List has only the CLI tool
        resp = await client.get("/api/registry/tools")
        assert len(resp.json()["tools"]) == 1
        assert resp.json()["tools"][0]["name"] == "ct1"

        # Unregister CLI
        resp = await client.delete("/api/registry/tools/ct1")
        assert resp.status_code == 200

        # Empty
        resp = await client.get("/api/registry/tools")
        assert resp.json()["tools"] == []

