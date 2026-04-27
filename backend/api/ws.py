"""WebSocket endpoint with ConnectionManager for broadcasting.

Provides a simple echo handler and a ConnectionManager shared by
the rest of the application for broadcasting messages (e.g. agent
loop updates, status changes).
"""

import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages active WebSocket connections and supports broadcasting."""

    def __init__(self) -> None:
        self._connections: dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self._connections[id(websocket)] = websocket

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the registry."""
        self._connections.pop(id(websocket), None)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a JSON message to every connected client."""
        payload = json.dumps(message)
        stale: list[int] = []
        for cid, ws in self._connections.items():
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(cid)
        for cid in stale:
            self._connections.pop(cid, None)

    @property
    def active_connections(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Echo WebSocket handler.

    Accepts connections, echoes back any received text as a JSON
    message, and handles disconnection cleanly.
    """
    await manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            # Try to parse as JSON, echo as-is otherwise
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"text": raw}

            await websocket.send_json({
                "type": "echo",
                "data": data,
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
