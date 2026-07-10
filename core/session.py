"""
core/session.py
---------------
Research session lifecycle management.
Creates, loads, and finalizes sessions with UUID and config snapshot.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from database.models import ResearchSession
from database.repository import SessionRepository

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SessionManager:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn
        self._repo = SessionRepository(conn)

    async def create(self, config_snapshot: dict[str, Any]) -> ResearchSession:
        """Create a new research session with a fresh UUID."""
        session = ResearchSession(
            id=str(uuid.uuid4()),
            started_at=_now(),
            config_snapshot=config_snapshot,
        )
        await self._repo.create(session)
        logger.info("Created research session: %s", session.id)
        return session

    async def load_latest(self) -> ResearchSession | None:
        """Load the most recently started session."""
        cursor = await self.conn.execute(
            "SELECT * FROM research_sessions ORDER BY started_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["config_snapshot"] = json.loads(d.get("config_snapshot") or "{}")
        return ResearchSession(**{k: v for k, v in d.items() if k in ResearchSession.model_fields})

    async def load(self, session_id: str) -> ResearchSession | None:
        return await self._repo.get(session_id)

    async def finalize(
        self,
        session_id: str,
        completed_apps: int,
        failed_apps: int,
        avg_confidence: float,
        human_review_count: int,
        total_api_calls: int,
        cache_hit_ratio: float,
        estimated_cost_usd: float,
    ) -> None:
        """Mark the session as complete and record final metrics."""
        await self._repo.update(
            session_id,
            {
                "completed_at": _now(),
                "completed_apps": completed_apps,
                "failed_apps": failed_apps,
                "avg_confidence": round(avg_confidence, 4),
                "human_review_count": human_review_count,
                "total_api_calls": total_api_calls,
                "cache_hit_ratio": round(cache_hit_ratio, 4),
                "estimated_cost_usd": round(estimated_cost_usd, 4),
            },
        )
        logger.info(
            "Session %s finalized: %d completed, %d failed, avg_conf=%.3f",
            session_id, completed_apps, failed_apps, avg_confidence,
        )

    async def update_counts(self, session_id: str, total_apps: int) -> None:
        await self._repo.update(session_id, {"total_apps": total_apps})
