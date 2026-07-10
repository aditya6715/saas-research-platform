"""
core/queue.py
-------------
SQLite-backed task queue with atomic status transitions.
Manages pending/in_progress/completed/failed states per app.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from database.models import AppRecord
from database.repository import AppRepository

logger = logging.getLogger(__name__)


@dataclass
class QueueStats:
    pending: int = 0
    in_progress: int = 0
    completed: int = 0
    failed: int = 0
    verified: int = 0

    @property
    def total(self) -> int:
        return self.pending + self.in_progress + self.completed + self.failed + self.verified

    @property
    def done(self) -> int:
        return self.completed + self.verified + self.failed


class TaskQueue:
    """
    Manages the research job queue using the apps table in SQLite.
    All status transitions are atomic (SQLite transaction).
    """

    def __init__(
        self,
        conn: aiosqlite.Connection,
        session_id: str,
        max_retries: int = 3,
        timeout_seconds: int = 120,
    ) -> None:
        self.conn = conn
        self.session_id = session_id
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._repo = AppRepository(conn)
        self._lock = asyncio.Lock()

    async def enqueue(self, app_name: str, seed_url: str | None = None) -> int | None:
        """
        Add an app to the queue. Returns new app_id or None if already exists.
        """
        existing = await self._repo.get_by_name(app_name, self.session_id)
        if existing:
            return existing.id

        app = AppRecord(
            session_id=self.session_id,
            app_name=app_name,
            seed_url=seed_url,
            status="pending",
        )
        app_id = await self._repo.create(app)
        logger.debug("Enqueued app '%s' (id=%s)", app_name, app_id)
        return app_id

    async def claim_next(self) -> AppRecord | None:
        """
        Atomically claim the next pending app, marking it in_progress.
        Returns None if queue is empty.
        """
        async with self._lock:
            cursor = await self.conn.execute(
                "SELECT * FROM apps WHERE session_id=? AND status='pending' "
                "ORDER BY id LIMIT 1",
                (self.session_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            app = AppRecord.from_db_row(dict(row))
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            await self.conn.execute(
                "UPDATE apps SET status='in_progress', updated_at=? WHERE id=?",
                (now, app.id),
            )
            await self.conn.commit()
            return app

    async def complete(self, app_id: int) -> None:
        await self._repo.update_status(app_id, "completed")

    async def mark_verified(self, app_id: int) -> None:
        await self._repo.update_status(app_id, "verified")

    async def fail(self, app_id: int, error: str) -> None:
        """Mark as failed. Increments retry counter; if under limit, reset to pending."""
        retry_count = await self._repo.increment_retry(app_id)
        if retry_count < self.max_retries:
            await self._repo.update_status(app_id, "pending", error)
            logger.info("App %s reset to pending (retry %d/%d)", app_id, retry_count, self.max_retries)
        else:
            await self._repo.update_status(app_id, "failed", error)
            logger.warning("App %s permanently failed after %d retries", app_id, retry_count)

    async def restore_orphaned(self) -> int:
        """Reset in_progress apps to pending (crash recovery)."""
        count = await self._repo.restore_orphaned(self.session_id)
        if count:
            logger.info("Restored %d orphaned in_progress apps to pending", count)
        return count

    async def get_stats(self) -> QueueStats:
        counts = await self._repo.count_by_status(self.session_id)
        return QueueStats(
            pending=counts.get("pending", 0),
            in_progress=counts.get("in_progress", 0),
            completed=counts.get("completed", 0),
            failed=counts.get("failed", 0),
            verified=counts.get("verified", 0),
        )

    async def is_complete(self) -> bool:
        stats = await self.get_stats()
        return stats.pending == 0 and stats.in_progress == 0
