"""Shared FastAPI dependencies for the RE-AI application.

Provides a ``get_planning_engine`` dependency that returns the
application-scoped ``PlanningEngine`` instance stored on
``app.state.engine`` during lifetime startup.
"""

from fastapi import Request

from backend.engine import PlanningEngine


def get_planning_engine(request: Request) -> PlanningEngine:
    """Return the shared PlanningEngine installed during lifespan startup.

    The engine was created with the WebSocket ``ConnectionManager.broadcast``
    wired as its ``on_change`` callback, so every mutation broadcasts a
    real-time event to all connected clients.
    """
    engine: PlanningEngine = request.app.state.engine
    return engine
