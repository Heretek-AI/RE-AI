"""Slices REST API router — CRUD for slices.

Endpoints
---------
- GET    /api/milestones/{milestone_id}/slices  — List slices for a milestone
- POST   /api/milestones/{milestone_id}/slices  — Create a slice under a milestone (201)
- GET    /api/slices/{id}                       — Get one slice (404 if missing)
- PUT    /api/slices/{id}                       — Update a slice (404 if missing)
- DELETE /api/slices/{id}                       — Delete a slice (404 if missing, 409 if tasks exist)
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.dependencies import get_planning_engine
from backend.engine import (
    PlanningEngine,
    SliceCreate,
    SliceResponse,
    SliceUpdate,
)

router = APIRouter(tags=["slices"])


# ── Dependency ──────────────────────────────────────────────────────────────


async def get_engine(request: Request) -> PlanningEngine:
    """Return the shared PlanningEngine from app.state."""
    return get_planning_engine(request)


# ── List slices by milestone ────────────────────────────────────────────────


@router.get(
    "/api/milestones/{milestone_id}/slices",
    response_model=list[SliceResponse],
)
async def list_slices(
    milestone_id: int,
    engine: PlanningEngine = Depends(get_engine),
):
    """Return all slices that belong to the given milestone, ordered by order."""
    # Verify the milestone exists
    if await engine.get_milestone(milestone_id) is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return await engine.get_slices_by_milestone(milestone_id)


# ── Create slice under milestone ────────────────────────────────────────────


@router.post(
    "/api/milestones/{milestone_id}/slices",
    response_model=SliceResponse,
    status_code=201,
)
async def create_slice(
    milestone_id: int,
    data: SliceCreate,
    engine: PlanningEngine = Depends(get_engine),
):
    """Create a new slice under the specified milestone.

    Returns 201 with the created slice, or 404 if the milestone does not exist.
    """
    slice_ = await engine.create_slice(milestone_id, data)
    if slice_ is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return slice_


# ── Get by id ───────────────────────────────────────────────────────────────


@router.get("/api/slices/{id}", response_model=SliceResponse)
async def get_slice(
    id: int,
    engine: PlanningEngine = Depends(get_engine),
):
    """Return a single slice by id, or 404 if not found."""
    slice_ = await engine.get_slice(id)
    if slice_ is None:
        raise HTTPException(status_code=404, detail="Slice not found")
    return slice_


# ── Update ──────────────────────────────────────────────────────────────────


@router.put("/api/slices/{id}", response_model=SliceResponse)
async def update_slice(
    id: int,
    data: SliceUpdate,
    engine: PlanningEngine = Depends(get_engine),
):
    """Update a slice's fields. Only provided fields are changed.

    Status transitions are validated against the state machine (422 on invalid
    transition). Raises 404 if the id does not exist.
    """
    try:
        slice_ = await engine.update_slice(id, data)
        if slice_ is None:
            raise HTTPException(status_code=404, detail="Slice not found")
        return slice_
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── Delete ──────────────────────────────────────────────────────────────────


@router.delete("/api/slices/{id}", status_code=204)
async def delete_slice(
    id: int,
    engine: PlanningEngine = Depends(get_engine),
):
    """Delete a slice.

    Returns 204 on success.
    Raises 404 if the slice id does not exist.
    Raises 409 if tasks still exist under this slice (deletion blocked).
    """
    deleted = await engine.delete_slice(id)
    if not deleted:
        existing = await engine.get_slice(id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Slice not found")
        raise HTTPException(
            status_code=409,
            detail="Cannot delete slice: tasks exist under this slice",
        )
    return None
