"""Tasks REST API router — CRUD for tasks with status transitions.

Endpoints
---------
- GET    /api/slices/{slice_id}/tasks      — List tasks for a slice
- POST   /api/slices/{slice_id}/tasks      — Create a task under a slice (201)
- GET    /api/tasks/{id}                   — Get one task (404 if missing)
- PUT    /api/tasks/{id}                   — Update a task (404 if missing)
- PATCH  /api/tasks/{id}/status            — Transition task status (422 invalid)
- DELETE /api/tasks/{id}                   — Delete a task (404 if missing)
"""

from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException

from backend.db.database import get_connection
from backend.engine import (
    PlanningEngine,
    TaskCreate,
    TaskResponse,
    TaskStatusUpdate,
    TaskUpdate,
)

router = APIRouter(tags=["tasks"])


# ── Dependency ──────────────────────────────────────────────────────────────


async def get_engine() -> AsyncGenerator[PlanningEngine, None]:
    """Yield a PlanningEngine with a fresh DB connection per request."""
    conn = await get_connection()
    try:
        yield PlanningEngine(conn=conn)
    finally:
        await conn.close()


# ── List tasks by slice ─────────────────────────────────────────────────────


@router.get(
    "/api/slices/{slice_id}/tasks",
    response_model=list[TaskResponse],
)
async def list_tasks(
    slice_id: int,
    engine: PlanningEngine = Depends(get_engine),
):
    """Return all tasks that belong to the given slice, ordered by order."""
    # Verify the slice exists
    if await engine.get_slice(slice_id) is None:
        raise HTTPException(status_code=404, detail="Slice not found")
    return await engine.get_tasks_by_slice(slice_id)


# ── Create task under slice ─────────────────────────────────────────────────


@router.post(
    "/api/slices/{slice_id}/tasks",
    response_model=TaskResponse,
    status_code=201,
)
async def create_task(
    slice_id: int,
    data: TaskCreate,
    engine: PlanningEngine = Depends(get_engine),
):
    """Create a new task under the specified slice.

    Returns 201 with the created task, or 404 if the slice does not exist.
    """
    task = await engine.create_task(slice_id, data)
    if task is None:
        raise HTTPException(status_code=404, detail="Slice not found")
    return task


# ── Get by id ───────────────────────────────────────────────────────────────


@router.get("/api/tasks/{id}", response_model=TaskResponse)
async def get_task(
    id: int,
    engine: PlanningEngine = Depends(get_engine),
):
    """Return a single task by id, or 404 if not found."""
    task = await engine.get_task(id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ── Update ──────────────────────────────────────────────────────────────────


@router.put("/api/tasks/{id}", response_model=TaskResponse)
async def update_task(
    id: int,
    data: TaskUpdate,
    engine: PlanningEngine = Depends(get_engine),
):
    """Update a task's fields (title, description). Only provided fields change.

    Raises 404 if the id does not exist.
    """
    task = await engine.update_task(id, data)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ── Status transition ───────────────────────────────────────────────────────


@router.patch("/api/tasks/{id}/status", response_model=TaskResponse)
async def update_task_status(
    id: int,
    data: TaskStatusUpdate,
    engine: PlanningEngine = Depends(get_engine),
):
    """Transition a task's status.

    Body: ``{"status": "in_progress"}``

    Returns the updated task on success.
    Raises 404 if the task id does not exist.
    Raises 422 if the status transition is invalid (e.g. ``pending`` → ``complete``
    is not a valid transition without going through ``in_progress`` first),
    or if the requested status is not one of the valid statuses.
    """
    try:
        task = await engine.update_task_status(id, data.status)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── Delete ──────────────────────────────────────────────────────────────────


@router.delete("/api/tasks/{id}", status_code=204)
async def delete_task(
    id: int,
    engine: PlanningEngine = Depends(get_engine),
):
    """Delete a task.

    Returns 204 on success.  Raises 404 if the task id does not exist.
    """
    deleted = await engine.delete_task(id)
    if not deleted:
        existing = await engine.get_task(id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Task not found")
        # Task existed but delete returned False — unexpected
        raise HTTPException(status_code=500, detail="Failed to delete task")
    return None
