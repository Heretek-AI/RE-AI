"""Milestones REST API router — CRUD for milestones.

Endpoints
---------
- GET    /api/milestones       — List all milestones
- POST   /api/milestones       — Create a new milestone (201)
- GET    /api/milestones/{id}  — Get one milestone (404 if missing)
- PUT    /api/milestones/{id}  — Update a milestone (404 if missing)
- DELETE /api/milestones/{id}  — Delete a milestone (404 if missing, 409 if slices exist)
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.dependencies import get_planning_engine
from backend.engine import (
    MilestoneCreate,
    MilestoneResponse,
    MilestoneUpdate,
    PlanningEngine,
)

router = APIRouter(prefix="/api/milestones", tags=["milestones"])


# ── Dependency ──────────────────────────────────────────────────────────────


async def get_engine(request: Request) -> PlanningEngine:
    """Return the shared PlanningEngine from app.state."""
    return get_planning_engine(request)


# ── List ────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[MilestoneResponse])
async def list_milestones(
    engine: PlanningEngine = Depends(get_engine),
):
    """Return all milestones ordered by id ascending."""
    return await engine.list_milestones()


# ── Create ──────────────────────────────────────────────────────────────────


@router.post("", response_model=MilestoneResponse, status_code=201)
async def create_milestone(
    data: MilestoneCreate,
    engine: PlanningEngine = Depends(get_engine),
):
    """Create a new milestone and return it with server-generated fields."""
    return await engine.create_milestone(data)


# ── Get by id ───────────────────────────────────────────────────────────────


@router.get("/{id}", response_model=MilestoneResponse)
async def get_milestone(
    id: int,
    engine: PlanningEngine = Depends(get_engine),
):
    """Return a single milestone by id, or 404 if not found."""
    milestone = await engine.get_milestone(id)
    if milestone is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return milestone


# ── Update ──────────────────────────────────────────────────────────────────


@router.put("/{id}", response_model=MilestoneResponse)
async def update_milestone(
    id: int,
    data: MilestoneUpdate,
    engine: PlanningEngine = Depends(get_engine),
):
    """Update a milestone's fields. Only provided fields are changed.

    Returns the updated milestone.  Raises 404 if the id does not exist.
    """
    milestone = await engine.update_milestone(id, data)
    if milestone is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return milestone


# ── Delete ──────────────────────────────────────────────────────────────────


@router.delete("/{id}", status_code=204)
async def delete_milestone(
    id: int,
    engine: PlanningEngine = Depends(get_engine),
):
    """Delete a milestone.

    Returns 204 on success.
    Raises 404 if the milestone id does not exist.
    Raises 409 if slices still exist under this milestone (deletion blocked).
    """
    deleted = await engine.delete_milestone(id)
    if not deleted:
        existing = await engine.get_milestone(id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Milestone not found")
        raise HTTPException(
            status_code=409,
            detail="Cannot delete milestone: slices exist under this milestone",
        )
    return None
