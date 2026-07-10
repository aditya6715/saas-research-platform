"""
database/connection.py
----------------------
aiosqlite connection factory with WAL mode, foreign key enforcement,
and automatic schema migration runner.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def get_connection(db_path: str | Path) -> aiosqlite.Connection:
    """
    Open an aiosqlite connection with WAL mode and FK enforcement.
    Caller is responsible for closing.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA cache_size=-64000")  # 64 MB page cache
    return conn


async def apply_migrations(conn: aiosqlite.Connection) -> None:
    """
    Apply any pending SQL migration files from the migrations/ directory.
    Migrations are applied in numeric order based on filename prefix (001_, 002_, ...).
    Idempotent: already-applied versions are skipped.
    """
    # Ensure schema_versions table exists before querying it
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_versions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            version     INTEGER NOT NULL UNIQUE,
            applied_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            description TEXT    NOT NULL
        )
        """
    )
    await conn.commit()

    cursor = await conn.execute("SELECT version FROM schema_versions")
    applied = {row[0] for row in await cursor.fetchall()}

    migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    for mf in migration_files:
        version = int(mf.name.split("_")[0])
        if version in applied:
            continue
        logger.info("Applying migration %s", mf.name)
        sql = mf.read_text()
        # Execute statement by statement (aiosqlite doesn't support executescript in async)
        for statement in _split_sql(sql):
            if statement.strip():
                await conn.execute(statement)
        await conn.commit()
        logger.info("Migration %s applied successfully", mf.name)


def _split_sql(sql: str) -> list[str]:
    """Split a SQL script into individual statements, ignoring comments."""
    statements = []
    current: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current))
            current = []
    if current:
        statements.append("\n".join(current))
    return statements


class DatabaseManager:
    """Context manager wrapping a shared connection with migration support."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> aiosqlite.Connection:
        self._conn = await get_connection(self.db_path)
        await apply_migrations(self._conn)
        return self._conn

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
