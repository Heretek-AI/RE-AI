"""Chat WebSocket endpoint — routes /ws/chat for agent interaction.

Connects to the ``/ws/chat`` endpoint, creates an ``AgentLoopSession``
with the app's planning engine and provider config, and streams agent
events back to the client.

Protocol
--------
**Client → Server:**
- ``{"type": "chat:message", "content": "..."}`` — Send a user message

**Server → Client:**
- ``{"type": "agent:delta", "content": "..."}`` — Streaming text
- ``{"type": "agent:tool_call", "id": "...", "name": "...", "arguments": {...}}``
- ``{"type": "agent:tool_result", "id": "...", "name": "...", "result": "..."}``
- ``{"type": "agent:error", "code": 0, "message": "..."}``
- ``{"type": "agent:done"}`` — Processing complete
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.agent.loop import AgentLoopSession
from backend.agent.provider import get_provider
from backend.api.ws import manager
from backend.core.config_store import ConfigStore
from backend.engine.planning import PlanningEngine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# ---------------------------------------------------------------------------
# JSON encoder for non-standard types
# ---------------------------------------------------------------------------


def _json_default(obj: Any) -> str:
    """JSON serializer for objects not natively handled by json.dumps."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(
        f"Object of type {obj.__class__.__name__} is not JSON serializable"
    )


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket) -> None:
    """Agent chat WebSocket endpoint.

    On connection, reads AI provider config from ``ConfigStore``,
    creates an ``AgentLoopSession``, and enters a message loop.

    Only one ``asyncio.Task`` processes messages at a time — new
    incoming messages cancel the current task before starting a new one.
    """
    # --- Accept connection ---
    await manager.connect(websocket)

    # --- Resolve provider from config ---
    try:
        store = ConfigStore()
        config = store.load()

        if not config or not config.get("ai_provider"):
            await websocket.send_json({
                "type": "agent:error",
                "code": 0,
                "message": (
                    "No AI provider configured. Please complete the setup "
                    "wizard first."
                ),
            })
            await websocket.send_json({"type": "agent:done"})
            return

        provider = get_provider(config)
    except ValueError as exc:
        await websocket.send_json({
            "type": "agent:error",
            "code": 0,
            "message": f"Provider configuration error: {exc}",
        })
        await websocket.send_json({"type": "agent:done"})
        return
    except Exception as exc:
        logger.exception("Failed to create AI provider")
        await websocket.send_json({
            "type": "agent:error",
            "code": 0,
            "message": f"Failed to create AI provider: {exc}",
        })
        await websocket.send_json({"type": "agent:done"})
        return

    # --- Resolve planning engine from app state ---
    # The engine is set on app.state during lifespan startup.
    engine: Optional[PlanningEngine] = None
    try:
        scope = websocket.scope
        app = scope.get("app")
        if app is not None:
            engine = getattr(app.state, "engine", None)
    except (AttributeError, KeyError):
        pass

    if engine is None:
        await websocket.send_json({
            "type": "agent:error",
            "code": 0,
            "message": "Planning engine not available (server not fully initialized).",
        })
        await websocket.send_json({"type": "agent:done"})
        return

    # --- Create agent session ---
    vector_store = getattr(app.state, "vector_store", None)
    session = AgentLoopSession(
        provider=provider,
        engine=engine,
        vector_store=vector_store,
    )

    # --- Message processing loop ---
    current_task: Optional[asyncio.Task[None]] = None

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "agent:error",
                    "code": 0,
                    "message": "Invalid JSON payload.",
                })
                continue

            msg_type = data.get("type", "")
            if msg_type != "chat:message":
                await websocket.send_json({
                    "type": "agent:error",
                    "code": 0,
                    "message": f"Unknown message type: {msg_type}",
                })
                continue

            content = data.get("content", "")
            if not content.strip():
                await websocket.send_json({
                    "type": "agent:error",
                    "code": 0,
                    "message": "Empty message content.",
                })
                continue

            # Cancel any in-flight processing task
            if current_task is not None and not current_task.done():
                current_task.cancel()
                try:
                    await current_task
                except asyncio.CancelledError:
                    pass

            # Start new processing task
            current_task = asyncio.create_task(
                _forward_events(session, content, websocket)
            )

    except WebSocketDisconnect:
        logger.debug("Chat WebSocket disconnected")
    except asyncio.CancelledError:
        logger.debug("Chat WebSocket task cancelled")
    finally:
        # Cancel running task on disconnect
        if current_task is not None and not current_task.done():
            current_task.cancel()
            try:
                await current_task
            except (asyncio.CancelledError, Exception):
                pass
        manager.disconnect(websocket)


async def _forward_events(
    session: AgentLoopSession,
    content: str,
    websocket: WebSocket,
) -> None:
    """Forward agent loop events to the WebSocket client.

    Runs ``session.process_message(content)`` and streams each
    yielded event as a JSON message.
    """
    try:
        async for event in session.process_message(content):
            try:
                payload = json.dumps(event, default=_json_default)
                await websocket.send_text(payload)
            except Exception:
                logger.exception("Failed to send agent event to WebSocket")
                break
    except asyncio.CancelledError:
        logger.debug("Forward task cancelled")
    except Exception:
        logger.exception("Agent loop crashed")
        try:
            await websocket.send_json({
                "type": "agent:error",
                "code": 0,
                "message": "Agent loop encountered an unexpected error.",
            })
        except Exception:
            pass
