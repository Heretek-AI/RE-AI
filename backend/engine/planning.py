"""Core planning engine — DB-backed CRUD with validated status transitions.

``PlanningEngine`` is the shared source of truth for milestone, slice,
and task operations.  It wraps an ``aiosqlite.Connection`` and exposes
async CRUD methods that enforce state-machine validation on status
changes.  An optional ``on_change`` callback is invoked after every
mutation, enabling real-time broadcasting via WebSocket or agent
loop integration.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Optional

import aiosqlite

from backend.engine.state_machine import VALID_STATUSES, validate_transition
from backend.engine.models import (
    MilestoneCreate,
    MilestoneResponse,
    MilestoneUpdate,
    SliceCreate,
    SliceResponse,
    SliceUpdate,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
    TaskStatusUpdate,
)


EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
"""Signature for change-notification callbacks.

The callback receives a single dict with keys ``type``, ``entity``,
``action``, and ``data``.
"""


def _to_datetime(raw: str) -> datetime:
    """Convert an ISO-ish SQLite timestamp to a datetime object."""
    return datetime.fromisoformat(raw)


def _row_to_milestone(row: aiosqlite.Row) -> MilestoneResponse:
    return MilestoneResponse(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        created_at=_to_datetime(row["created_at"]),
        updated_at=_to_datetime(row["updated_at"]),
    )


def _row_to_slice(row: aiosqlite.Row) -> SliceResponse:
    return SliceResponse(
        id=row["id"],
        milestone_id=row["milestone_id"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        order=row["order"],
        created_at=_to_datetime(row["created_at"]),
        updated_at=_to_datetime(row["updated_at"]),
    )


def _row_to_task(row: aiosqlite.Row) -> TaskResponse:
    return TaskResponse(
        id=row["id"],
        slice_id=row["slice_id"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        order=row["order"],
        created_at=_to_datetime(row["created_at"]),
        updated_at=_to_datetime(row["updated_at"]),
    )


class PlanningEngine:
    """DB-backed CRUD engine for milestones, slices, and tasks.

    Parameters
    ----------
    conn:
        An open ``aiosqlite.Connection`` with row_factory set.
    on_change:
        Optional async callback notified after every mutation.
    """

    def __init__(
        self,
        conn: aiosqlite.Connection,
        on_change: Optional[EventCallback] = None,
    ) -> None:
        self._conn = conn
        self.on_change = on_change

    # ── Notification ─────────────────────────────────────────────────────

    async def _notify(
        self,
        entity: str,
        action: str,
        data: dict[str, Any],
    ) -> None:
        """Invoke the *on_change* callback (if set) with a structured event."""
        if self.on_change is None:
            return
        payload: dict[str, Any] = {
            "type": "entity_change",
            "entity": entity,
            "action": action,
            "data": data,
        }
        await self.on_change(payload)

    # ── Milestones ───────────────────────────────────────────────────────

    async def create_milestone(self, data: MilestoneCreate) -> MilestoneResponse:
        cursor = await self._conn.execute(
            "INSERT INTO milestones (title, description) VALUES (?, ?)",
            (data.title, data.description),
        )
        await self._conn.commit()
        milestone = await self.get_milestone(cursor.lastrowid)
        assert milestone is not None  # freshly inserted
        await self._notify("milestone", "created", milestone.model_dump())
        return milestone

    async def get_milestone(self, id: int) -> Optional[MilestoneResponse]:
        cursor = await self._conn.execute(
            "SELECT * FROM milestones WHERE id = ?", (id,)
        )
        row = await cursor.fetchone()
        return _row_to_milestone(row) if row else None

    async def update_milestone(
        self, id: int, data: MilestoneUpdate
    ) -> Optional[MilestoneResponse]:
        # Build SET clause dynamically from non-None fields
        sets: list[str] = []
        params: list[Any] = []
        if data.title is not None:
            sets.append("title = ?")
            params.append(data.title)
        if data.description is not None:
            sets.append("description = ?")
            params.append(data.description)
        if data.status is not None:
            # Milestones use an open-ended status set ('active', 'archived', ...)
            # — not the task state machine — so we skip validate_transition here.
            sets.append("status = ?")
            params.append(data.status)
        if not sets:
            return await self.get_milestone(id)  # no-op

        sets.append("updated_at = datetime('now')")
        params.append(id)

        await self._conn.execute(
            f"UPDATE milestones SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        await self._conn.commit()
        milestone = await self.get_milestone(id)
        if milestone:
            await self._notify("milestone", "updated", milestone.model_dump())
        return milestone

    async def delete_milestone(self, id: int) -> bool:
        # Block deletion if slices exist under this milestone
        cursor = await self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM slices WHERE milestone_id = ?", (id,)
        )
        row = await cursor.fetchone()
        if row and row["cnt"] > 0:
            return False
        cursor = await self._conn.execute(
            "DELETE FROM milestones WHERE id = ?", (id,)
        )
        await self._conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            await self._notify("milestone", "deleted", {"id": id})
        return deleted

    async def list_milestones(self) -> list[MilestoneResponse]:
        cursor = await self._conn.execute(
            "SELECT * FROM milestones ORDER BY id ASC"
        )
        rows = await cursor.fetchall()
        return [_row_to_milestone(r) for r in rows]

    # ── Slices ───────────────────────────────────────────────────────────

    async def create_slice(
        self, milestone_id: int, data: SliceCreate
    ) -> Optional[SliceResponse]:
        # Verify milestone exists
        parent = await self.get_milestone(milestone_id)
        if parent is None:
            return None

        cursor = await self._conn.execute(
            """INSERT INTO slices (milestone_id, title, description, "order")
               VALUES (?, ?, ?,
                       (SELECT COALESCE(MAX("order"), 0) + 1 FROM slices
                        WHERE milestone_id = ?))""",
            (milestone_id, data.title, data.description, milestone_id),
        )
        await self._conn.commit()
        slice_ = await self.get_slice(cursor.lastrowid)
        assert slice_ is not None
        await self._notify("slice", "created", slice_.model_dump())
        return slice_

    async def get_slice(self, id: int) -> Optional[SliceResponse]:
        cursor = await self._conn.execute(
            "SELECT * FROM slices WHERE id = ?", (id,)
        )
        row = await cursor.fetchone()
        return _row_to_slice(row) if row else None

    async def get_slices_by_milestone(
        self, milestone_id: int
    ) -> list[SliceResponse]:
        cursor = await self._conn.execute(
            """SELECT * FROM slices
               WHERE milestone_id = ?
               ORDER BY "order" ASC""",
            (milestone_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_slice(r) for r in rows]

    async def update_slice(
        self, id: int, data: SliceUpdate
    ) -> Optional[SliceResponse]:
        sets: list[str] = []
        params: list[Any] = []
        if data.title is not None:
            sets.append("title = ?")
            params.append(data.title)
        if data.description is not None:
            sets.append("description = ?")
            params.append(data.description)
        if data.status is not None:
            current = await self.get_slice(id)
            if current is None:
                return None
            validate_transition(current.status, data.status)
            sets.append("status = ?")
            params.append(data.status)
        if data.order is not None:
            sets.append('"order" = ?')
            params.append(data.order)
        if not sets:
            return await self.get_slice(id)

        sets.append("updated_at = datetime('now')")
        params.append(id)

        await self._conn.execute(
            f"UPDATE slices SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        await self._conn.commit()
        slice_ = await self.get_slice(id)
        if slice_:
            await self._notify("slice", "updated", slice_.model_dump())
        return slice_

    async def delete_slice(self, id: int) -> bool:
        # Block deletion if tasks exist under this slice
        cursor = await self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM tasks WHERE slice_id = ?", (id,)
        )
        row = await cursor.fetchone()
        if row and row["cnt"] > 0:
            return False
        cursor = await self._conn.execute(
            "DELETE FROM slices WHERE id = ?", (id,)
        )
        await self._conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            await self._notify("slice", "deleted", {"id": id})
        return deleted

    # ── Tasks ────────────────────────────────────────────────────────────

    async def create_task(
        self, slice_id: int, data: TaskCreate
    ) -> Optional[TaskResponse]:
        # Verify slice exists
        parent = await self.get_slice(slice_id)
        if parent is None:
            return None

        cursor = await self._conn.execute(
            """INSERT INTO tasks (slice_id, title, description, "order")
               VALUES (?, ?, ?,
                       (SELECT COALESCE(MAX("order"), 0) + 1 FROM tasks
                        WHERE slice_id = ?))""",
            (slice_id, data.title, data.description, slice_id),
        )
        await self._conn.commit()
        task = await self.get_task(cursor.lastrowid)
        assert task is not None
        await self._notify("task", "created", task.model_dump())
        return task

    async def get_task(self, id: int) -> Optional[TaskResponse]:
        cursor = await self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (id,)
        )
        row = await cursor.fetchone()
        return _row_to_task(row) if row else None

    async def get_tasks_by_slice(self, slice_id: int) -> list[TaskResponse]:
        cursor = await self._conn.execute(
            """SELECT * FROM tasks
               WHERE slice_id = ?
               ORDER BY "order" ASC""",
            (slice_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_task(r) for r in rows]

    async def update_task(
        self, id: int, data: TaskUpdate
    ) -> Optional[TaskResponse]:
        sets: list[str] = []
        params: list[Any] = []
        if data.title is not None:
            sets.append("title = ?")
            params.append(data.title)
        if data.description is not None:
            sets.append("description = ?")
            params.append(data.description)
        if not sets:
            return await self.get_task(id)

        sets.append("updated_at = datetime('now')")
        params.append(id)

        await self._conn.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        await self._conn.commit()
        task = await self.get_task(id)
        if task:
            await self._notify("task", "updated", task.model_dump())
        return task

    async def update_task_status(
        self, id: int, new_status: str
    ) -> Optional[TaskResponse]:
        # Validate new_status itself is a known status
        if new_status not in VALID_STATUSES:
            valid = ", ".join(VALID_STATUSES)
            raise ValueError(
                f"Invalid status: {new_status!r}. Must be one of: {valid}"
            )

        # Fetch current task to validate transition
        task = await self.get_task(id)
        if task is None:
            return None

        # Validate transition
        if not validate_transition(task.status, new_status):
            raise ValueError(
                f"Invalid status transition: {task.status!r} -> {new_status!r}"
            )

        # Race-safe update: only update if status hasn't changed
        cursor = await self._conn.execute(
            "UPDATE tasks SET status = ?, updated_at = datetime('now') "
            "WHERE id = ? AND status = ?",
            (new_status, id, task.status),
        )
        await self._conn.commit()

        if cursor.rowcount == 0:
            # Race lost or no-op (someone else changed it first)
            return await self.get_task(id)

        updated = await self.get_task(id)
        if updated:
            await self._notify(
                "task", "status_changed", updated.model_dump()
            )
        return updated

    async def delete_task(self, id: int) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM tasks WHERE id = ?", (id,)
        )
        await self._conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            await self._notify("task", "deleted", {"id": id})
        return deleted
