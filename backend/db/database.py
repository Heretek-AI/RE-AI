"""Async SQLite database connection and session management.

Uses aiosqlite via SQLAlchemy's async engine. Provides a `get_db`
dependency that yields async connections for request handlers.
"""

import os

import aiosqlite
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager



def _resolve_db_path() -> str:
    """Resolve the database file path from ``DATABASE_URL`` env var.

    Falls back to ``settings.database_url`` if no env override is set.
    Uses the env var directly rather than ``settings`` because
    ``BaseSettings`` is constructed once at module-import time and
    tests need to change the path at runtime via ``os.environ``.
    """
    raw = os.environ.get(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./re-ai.db",
    )
    return raw.replace("sqlite+aiosqlite:///", "").lstrip("/")


async def get_connection() -> aiosqlite.Connection:
    """Create and return a new aiosqlite connection."""
    conn = await aiosqlite.connect(_resolve_db_path())
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Dependency: yields an aiosqlite connection, commits on success,
    rolls back on exception."""
    conn = await get_connection()
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        await conn.close()


async def init_db() -> None:
    """Create initial tables if they don't yet exist.

    Called during application startup. Includes core app tables
    (conversations, messages, analysis_tasks) and planning engine
    tables (milestones, slices, tasks).
    """
    conn = await get_connection()
    try:
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL DEFAULT 'New Conversation',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                role            TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                content         TEXT NOT NULL,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS analysis_tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status IN ('pending','running','complete','failed')),
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Planning engine tables (milestone→slices→tasks hierarchy)

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
    finally:
        await conn.close()
