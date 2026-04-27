"""Tests for the planning engine — CRUD, status transitions, notifications."""

import asyncio
import os
import tempfile

import aiosqlite
import pytest

from backend.engine.models import (
    MilestoneCreate,
    MilestoneUpdate,
    SliceCreate,
    SliceUpdate,
    TaskCreate,
    TaskUpdate,
    TaskStatusUpdate,
)
from backend.engine.planning import PlanningEngine
from backend.engine.state_machine import VALID_STATUSES, validate_transition


@pytest.fixture
async def db():
    """Create a temporary in-memory database with planning tables."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.executescript("""
        CREATE TABLE IF NOT EXISTS milestones (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'active',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS slices (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            milestone_id INTEGER NOT NULL REFERENCES milestones(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'pending',
            "order"     INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            slice_id    INTEGER NOT NULL REFERENCES slices(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending','in_progress','complete','errored')),
            "order"     INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    await conn.commit()
    yield conn
    await conn.close()


@pytest.fixture
def engine(db):
    return PlanningEngine(db)


@pytest.fixture
def engine_with_callback(db):
    events = []

    async def collector(payload: dict) -> None:
        events.append(payload)

    eng = PlanningEngine(db, on_change=collector)
    return eng, events


# ── Milestone CRUD ──────────────────────────────────────────────────────

class TestMilestones:
    async def test_create_and_get(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1", description="First milestone"))
        assert m.id == 1
        assert m.title == "M1"
        assert m.description == "First milestone"
        assert m.status == "active"

        fetched = await engine.get_milestone(m.id)
        assert fetched is not None
        assert fetched.id == m.id
        assert fetched.title == "M1"

    async def test_get_missing(self, engine: PlanningEngine):
        assert await engine.get_milestone(999) is None

    async def test_update(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        updated = await engine.update_milestone(m.id, MilestoneUpdate(title="Updated", description="new desc"))
        assert updated is not None
        assert updated.title == "Updated"
        assert updated.description == "new desc"

    async def test_update_partial(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1", description="desc"))
        updated = await engine.update_milestone(m.id, MilestoneUpdate(description="only desc"))
        assert updated is not None
        assert updated.title == "M1"  # unchanged
        assert updated.description == "only desc"

    async def test_update_none(self, engine: PlanningEngine):
        """No-op update returns current entity."""
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        updated = await engine.update_milestone(m.id, MilestoneUpdate())
        assert updated is not None
        assert updated.id == m.id

    async def test_delete(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        deleted = await engine.delete_milestone(m.id)
        assert deleted is True
        assert await engine.get_milestone(m.id) is None

    async def test_delete_blocked_by_slices(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        assert s is not None
        # Milestone with slices cannot be deleted
        assert await engine.delete_milestone(m.id) is False
        # Milestone still exists
        assert await engine.get_milestone(m.id) is not None

    async def test_list(self, engine: PlanningEngine):
        await engine.create_milestone(MilestoneCreate(title="M1"))
        await engine.create_milestone(MilestoneCreate(title="M2"))
        all_m = await engine.list_milestones()
        assert len(all_m) == 2

    async def test_update_status_valid(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        # milestones use 'active' status by default; no state machine for milestones,
        # but the engine lets you set any string via update
        updated = await engine.update_milestone(m.id, MilestoneUpdate(status="archived"))
        assert updated is not None
        assert updated.status == "archived"


# ── Slice CRUD ──────────────────────────────────────────────────────────

class TestSlices:
    async def test_create_and_get(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1", description="slice desc"))
        assert s is not None
        assert s.id == 1
        assert s.title == "S1"
        assert s.description == "slice desc"
        assert s.milestone_id == m.id
        assert s.status == "pending"

    async def test_create_missing_milestone(self, engine: PlanningEngine):
        s = await engine.create_slice(999, SliceCreate(title="orphan"))
        assert s is None

    async def test_get_missing(self, engine: PlanningEngine):
        assert await engine.get_slice(999) is None

    async def test_get_by_milestone(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s1 = await engine.create_slice(m.id, SliceCreate(title="S1"))
        s2 = await engine.create_slice(m.id, SliceCreate(title="S2"))
        slices = await engine.get_slices_by_milestone(m.id)
        assert len(slices) == 2
        assert slices[0].id == s1.id
        assert slices[1].id == s2.id

    async def test_update(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        updated = await engine.update_slice(s.id, SliceUpdate(title="Updated", description="new"))
        assert updated is not None
        assert updated.title == "Updated"
        assert updated.description == "new"

    async def test_update_status_valid(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        updated = await engine.update_slice(s.id, SliceUpdate(status="in_progress"))
        assert updated is not None
        assert updated.status == "in_progress"

    async def test_update_status_invalid(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        with pytest.raises(ValueError):
            await engine.update_slice(s.id, SliceUpdate(status="invalid_status"))

    async def test_delete(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        assert await engine.delete_slice(s.id) is True
        assert await engine.get_slice(s.id) is None

    async def test_delete_blocked_by_tasks(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        t = await engine.create_task(s.id, TaskCreate(title="T1"))
        assert t is not None
        assert await engine.delete_slice(s.id) is False
        assert await engine.get_slice(s.id) is not None

    async def test_auto_ordering(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s1 = await engine.create_slice(m.id, SliceCreate(title="S1"))
        s2 = await engine.create_slice(m.id, SliceCreate(title="S2"))
        s3 = await engine.create_slice(m.id, SliceCreate(title="S3"))
        assert s1.order == 1
        assert s2.order == 2
        assert s3.order == 3


# ── Task CRUD ───────────────────────────────────────────────────────────

class TestTasks:
    async def test_create_and_get(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        t = await engine.create_task(s.id, TaskCreate(title="T1", description="task desc"))
        assert t is not None
        assert t.id == 1
        assert t.title == "T1"
        assert t.description == "task desc"
        assert t.slice_id == s.id
        assert t.status == "pending"

    async def test_create_missing_slice(self, engine: PlanningEngine):
        t = await engine.create_task(999, TaskCreate(title="orphan"))
        assert t is None

    async def test_get_missing(self, engine: PlanningEngine):
        assert await engine.get_task(999) is None

    async def test_get_by_slice(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        t1 = await engine.create_task(s.id, TaskCreate(title="T1"))
        t2 = await engine.create_task(s.id, TaskCreate(title="T2"))
        tasks = await engine.get_tasks_by_slice(s.id)
        assert len(tasks) == 2
        assert tasks[0].id == t1.id
        assert tasks[1].id == t2.id

    async def test_update(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        t = await engine.create_task(s.id, TaskCreate(title="T1"))
        updated = await engine.update_task(t.id, TaskUpdate(title="Updated", description="new"))
        assert updated is not None
        assert updated.title == "Updated"
        assert updated.description == "new"

    async def test_delete(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        t = await engine.create_task(s.id, TaskCreate(title="T1"))
        assert await engine.delete_task(t.id) is True
        assert await engine.get_task(t.id) is None

    async def test_auto_ordering(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        t1 = await engine.create_task(s.id, TaskCreate(title="T1"))
        t2 = await engine.create_task(s.id, TaskCreate(title="T2"))
        t3 = await engine.create_task(s.id, TaskCreate(title="T3"))
        assert t1.order == 1
        assert t2.order == 2
        assert t3.order == 3


# ── Status transitions ──────────────────────────────────────────────────

class TestStatusTransitions:
    async def test_valid_transition(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        t = await engine.create_task(s.id, TaskCreate(title="T1"))
        assert t.status == "pending"

        t = await engine.update_task_status(t.id, "in_progress")
        assert t is not None
        assert t.status == "in_progress"

    async def test_invalid_transition(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        t = await engine.create_task(s.id, TaskCreate(title="T1"))
        # pending -> complete is invalid (must go through in_progress)
        with pytest.raises(ValueError, match="Invalid status transition"):
            await engine.update_task_status(t.id, "complete")

    async def test_terminal_idempotent(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        t = await engine.create_task(s.id, TaskCreate(title="T1"))
        t = await engine.update_task_status(t.id, "in_progress")
        t = await engine.update_task_status(t.id, "complete")
        assert t is not None
        assert t.status == "complete"
        # complete -> complete is valid (idempotent terminal)
        t = await engine.update_task_status(t.id, "complete")
        assert t is not None
        assert t.status == "complete"

    async def test_invalid_status_string(self, engine: PlanningEngine):
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        t = await engine.create_task(s.id, TaskCreate(title="T1"))
        with pytest.raises(ValueError, match="Invalid status"):
            await engine.update_task_status(t.id, "bogus")

    async def test_race_safe_update(self, engine: PlanningEngine):
        """update_task_status uses WHERE status = :old_status for race safety."""
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        t = await engine.create_task(s.id, TaskCreate(title="T1"))
        # Directly update the row to simulate concurrent change
        await engine._conn.execute(
            "UPDATE tasks SET status = 'in_progress' WHERE id = ?", (t.id,)
        )
        await engine._conn.commit()
        # Now call update_task_status assuming it's still 'pending'
        # It should still succeed because it reads current status first,
        # validates transition, then uses the read status in the WHERE clause
        result = await engine.update_task_status(t.id, "complete")
        assert result is not None
        assert result.status == "complete"


# ── Notification callback ───────────────────────────────────────────────

class TestNotifications:
    async def test_milestone_created_event(self, engine_with_callback):
        eng, events = engine_with_callback
        m = await eng.create_milestone(MilestoneCreate(title="M1"))
        assert len(events) == 1
        ev = events[0]
        assert ev["type"] == "entity_change"
        assert ev["entity"] == "milestone"
        assert ev["action"] == "created"
        assert ev["data"]["id"] == m.id

    async def test_milestone_updated_event(self, engine_with_callback):
        eng, events = engine_with_callback
        m = await eng.create_milestone(MilestoneCreate(title="M1"))
        events.clear()
        await eng.update_milestone(m.id, MilestoneUpdate(title="Updated"))
        assert len(events) == 1
        assert events[0]["entity"] == "milestone"
        assert events[0]["action"] == "updated"

    async def test_milestone_deleted_event(self, engine_with_callback):
        eng, events = engine_with_callback
        m = await eng.create_milestone(MilestoneCreate(title="M1"))
        events.clear()
        await eng.delete_milestone(m.id)
        assert len(events) == 1
        assert events[0]["entity"] == "milestone"
        assert events[0]["action"] == "deleted"

    async def test_slice_events(self, engine_with_callback):
        eng, events = engine_with_callback
        m = await eng.create_milestone(MilestoneCreate(title="M1"))
        events.clear()
        s = await eng.create_slice(m.id, SliceCreate(title="S1"))
        assert len(events) == 1
        assert events[0]["entity"] == "slice"
        assert events[0]["action"] == "created"

        events.clear()
        await eng.update_slice(s.id, SliceUpdate(title="Updated"))
        assert len(events) == 1
        assert events[0]["action"] == "updated"

        events.clear()
        await eng.delete_slice(s.id)
        assert len(events) == 1
        assert events[0]["action"] == "deleted"

    async def test_task_events(self, engine_with_callback):
        eng, events = engine_with_callback
        m = await eng.create_milestone(MilestoneCreate(title="M1"))
        s = await eng.create_slice(m.id, SliceCreate(title="S1"))
        events.clear()
        t = await eng.create_task(s.id, TaskCreate(title="T1"))
        assert len(events) == 1
        assert events[0]["entity"] == "task"
        assert events[0]["action"] == "created"

        events.clear()
        await eng.update_task(t.id, TaskUpdate(title="Updated"))
        assert len(events) == 1
        assert events[0]["action"] == "updated"

        events.clear()
        await eng.update_task_status(t.id, "in_progress")
        assert len(events) == 1
        assert events[0]["entity"] == "task"
        assert events[0]["action"] == "status_changed"

        events.clear()
        await eng.delete_task(t.id)
        assert len(events) == 1
        assert events[0]["action"] == "deleted"

    async def test_no_callback(self, engine: PlanningEngine):
        """Without a callback, no notification should be attempted."""
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        assert m is not None  # no crash


# ── Slice deletion cascade ──────────────────────────────────────────────

class TestCascadeDelete:
    async def test_cascade_delete_slice(self, engine: PlanningEngine):
        """Deleting a milestone should cascade-delete its slices (FK CASCADE)."""
        m = await engine.create_milestone(MilestoneCreate(title="M1"))
        s = await engine.create_slice(m.id, SliceCreate(title="S1"))
        assert s is not None
        # Force-delete the milestone (bypass blocked check for test)
        await engine._conn.execute("DELETE FROM milestones WHERE id = ?", (m.id,))
        await engine._conn.commit()
        # Slices should be gone
        slices = await engine.get_slices_by_milestone(m.id)
        assert len(slices) == 0
