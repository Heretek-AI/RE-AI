"""RE-AI FastAPI application.

Initializes the server with CORS, routers, static file serving,
and startup/shutdown lifecycle hooks.
"""

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.agent.tools import set_rag_store
from backend.api.chat_ws import router as chat_ws_router
from backend.api.config import router as config_router
from backend.api.health import router as health_router
from backend.api.milestones import router as milestones_router
from backend.api.rag import router as rag_router
from backend.api.registry import router as registry_router
from backend.api.slices import router as slices_router
from backend.api.tasks import router as tasks_router
from backend.api.tools import router as tools_router
from backend.api.ws import manager, router as ws_router
from backend.core.config import settings
from backend.db.database import get_connection, init_db
from backend.engine import PlanningEngine
from backend.rag import init_vector_store
from backend.registry import ToolRegistry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown hooks."""
    # --- Startup ---
    await init_db()
    conn = await get_connection()
    app.state.engine = PlanningEngine(conn=conn, on_change=manager.broadcast)

    # Initialize vector store for RAG
    app.state.vector_store = init_vector_store({
        "vector_db_type": settings.vector_db_type,
        "chroma_persist_dir": settings.chroma_persist_dir,
    })
    # Make the vector store accessible to agent tools via the global reference
    set_rag_store(app.state.vector_store)
    logger.info(
        "Vector store initialization complete (type=%s)",
        settings.vector_db_type,
    )

    yield
    # --- Shutdown ---
    # Shut down all MCP server subprocesses
    await ToolRegistry.get_instance().shutdown_all()
    await conn.close()


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    lifespan=lifespan,
)

# --- CORS (permissive for dev) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
app.include_router(config_router)
app.include_router(health_router)
app.include_router(milestones_router)
app.include_router(rag_router)
app.include_router(registry_router)
app.include_router(slices_router)
app.include_router(tasks_router)
app.include_router(tools_router)
app.include_router(ws_router)
app.include_router(chat_ws_router)

# --- Static files (if directory exists) ---
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.is_dir():
    # Serve explicit /static/* paths for raw assets (favicon, icons, etc.)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Serve the SPA from root if index.html exists — html=True means
    # unrecognized paths fall through to index.html (SPA client-side routing)
    if (static_dir / "index.html").exists():
        app.mount(
            "/",
            StaticFiles(directory=str(static_dir), html=True),
            name="spa",
        )


# --- Convenience entry point ---
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
