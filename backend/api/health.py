"""Health-check endpoint."""

from fastapi import APIRouter

from backend.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Return service status."""
    return {
        "status": "ok",
        "version": settings.version,
        "service": "re-ai",
    }
