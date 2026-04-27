"""Async SQLite database connection and session management.

Uses aiosqlite via SQLAlchemy's async engine. Provides a `get_db`
dependency that yields async connections for request handlers.
"""

import aiosqlite
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from backend.core.config import settings

# Derive the file path from database_url (strip sqlite+aiosqlite:/// prefix)
# e.g. "sqlite+aiosqlite:///./re-ai.db" -> "./re-ai.db"
_db_path = settings.database_url.replace("sqlite+aiosqlite:///", "").lstrip("/")


async def get_connection() -> aiosqlite.Connection:
    """Create and return a new aiosqlite connection."""
    conn = await aiosqlite.connect(_db_path)
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

    Called during application startup. Expanded in later slices.
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
        """)
        await conn.commit()
    finally:
        await conn.close()
