"""
database/repository.py
----------------------
All database queries centralized here.
Agents and core modules NEVER write raw SQL — they call these methods.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from database.models import AppRecord, EvidenceRecord, ResearchSession, VerificationRecord

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class AppRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    async def create(self, app: AppRecord) -> int:
        """Insert new app record, return assigned id."""
        row = app.to_db_row()
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        cursor = await self.conn.execute(
            f"INSERT INTO apps ({cols}) VALUES ({placeholders})",
            list(row.values()),
        )
        await self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_by_name(self, app_name: str, session_id: str) -> AppRecord | None:
        cursor = await self.conn.execute(
            "SELECT * FROM apps WHERE app_name=? AND session_id=? LIMIT 1",
            (app_name, session_id),
        )
        row = await cursor.fetchone()
        return AppRecord.from_db_row(dict(row)) if row else None

    async def get_by_id(self, app_id: int) -> AppRecord | None:
        cursor = await self.conn.execute("SELECT * FROM apps WHERE id=?", (app_id,))
        row = await cursor.fetchone()
        return AppRecord.from_db_row(dict(row)) if row else None

    async def get_pending(self, session_id: str) -> list[AppRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM apps WHERE session_id=? AND status='pending' ORDER BY id",
            (session_id,),
        )
        rows = await cursor.fetchall()
        return [AppRecord.from_db_row(dict(r)) for r in rows]

    async def get_all_verified(self, session_id: str) -> list[AppRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM apps WHERE session_id=? AND status IN ('completed','verified') ORDER BY app_name",
            (session_id,),
        )
        rows = await cursor.fetchall()
        return [AppRecord.from_db_row(dict(r)) for r in rows]

    async def update_status(self, app_id: int, status: str, error: str | None = None) -> None:
        await self.conn.execute(
            "UPDATE apps SET status=?, last_error=?, updated_at=? WHERE id=?",
            (status, error, _now(), app_id),
        )
        await self.conn.commit()

    async def increment_retry(self, app_id: int) -> int:
        """Increment retry counter and return new count."""
        await self.conn.execute(
            "UPDATE apps SET retry_count=retry_count+1, updated_at=? WHERE id=?",
            (_now(), app_id),
        )
        await self.conn.commit()
        cursor = await self.conn.execute("SELECT retry_count FROM apps WHERE id=?", (app_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def update_fields(self, app_id: int, fields: dict[str, Any]) -> None:
        """Update arbitrary fields on an app record."""
        if not fields:
            return
        fields["updated_at"] = _now()
        set_clause = ", ".join(f"{k}=?" for k in fields)
        await self.conn.execute(
            f"UPDATE apps SET {set_clause} WHERE id=?",
            [*fields.values(), app_id],
        )
        await self.conn.commit()

    async def restore_orphaned(self, session_id: str) -> int:
        """Reset in_progress apps to pending (for crash recovery)."""
        cursor = await self.conn.execute(
            "UPDATE apps SET status='pending', updated_at=? "
            "WHERE session_id=? AND status='in_progress'",
            (_now(), session_id),
        )
        await self.conn.commit()
        return cursor.rowcount

    async def exists_completed(self, app_name: str) -> bool:
        """Check if an app was already completed in any previous session."""
        cursor = await self.conn.execute(
            "SELECT 1 FROM apps WHERE app_name=? AND status IN ('completed','verified') LIMIT 1",
            (app_name,),
        )
        return await cursor.fetchone() is not None

    async def count_by_status(self, session_id: str) -> dict[str, int]:
        cursor = await self.conn.execute(
            "SELECT status, COUNT(*) FROM apps WHERE session_id=? GROUP BY status",
            (session_id,),
        )
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}


class EvidenceRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    async def create(self, ev: EvidenceRecord) -> int:
        row = ev.to_db_row()
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        cursor = await self.conn.execute(
            f"INSERT INTO evidence ({cols}) VALUES ({placeholders})",
            list(row.values()),
        )
        await self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_for_app(self, app_id: int) -> list[EvidenceRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM evidence WHERE app_id=? ORDER BY field_name, id",
            (app_id,),
        )
        rows = await cursor.fetchall()
        return [
            EvidenceRecord(**{k: v for k, v in dict(r).items() if k in EvidenceRecord.model_fields})
            for r in rows
        ]

    async def get_for_field(self, app_id: int, field_name: str) -> list[EvidenceRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM evidence WHERE app_id=? AND field_name=? ORDER BY confidence DESC",
            (app_id, field_name),
        )
        rows = await cursor.fetchall()
        return [
            EvidenceRecord(**{k: v for k, v in dict(r).items() if k in EvidenceRecord.model_fields})
            for r in rows
        ]


class VerificationRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    async def create(self, vr: VerificationRecord) -> int:
        row = vr.to_db_row()
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        cursor = await self.conn.execute(
            f"INSERT INTO verification_records ({cols}) VALUES ({placeholders})",
            list(row.values()),
        )
        await self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_for_app(self, app_id: int) -> list[VerificationRecord]:
        cursor = await self.conn.execute(
            "SELECT * FROM verification_records WHERE app_id=? ORDER BY field_name",
            (app_id,),
        )
        rows = await cursor.fetchall()
        return [
            VerificationRecord(
                **{k: v for k, v in dict(r).items() if k in VerificationRecord.model_fields}
            )
            for r in rows
        ]


class SessionRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    async def create(self, session: ResearchSession) -> None:
        row = session.to_db_row()
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        await self.conn.execute(
            f"INSERT INTO research_sessions ({cols}) VALUES ({placeholders})",
            list(row.values()),
        )
        await self.conn.commit()

    async def get(self, session_id: str) -> ResearchSession | None:
        cursor = await self.conn.execute(
            "SELECT * FROM research_sessions WHERE id=?", (session_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["config_snapshot"] = json.loads(d.get("config_snapshot") or "{}")
        return ResearchSession(**{k: v for k, v in d.items() if k in ResearchSession.model_fields})

    async def update(self, session_id: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        set_clause = ", ".join(f"{k}=?" for k in fields)
        await self.conn.execute(
            f"UPDATE research_sessions SET {set_clause} WHERE id=?",
            [*fields.values(), session_id],
        )
        await self.conn.commit()


class AgentLogRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    async def log(
        self,
        session_id: str,
        agent_name: str,
        event_type: str,
        message: str,
        app_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        level: str = "INFO",
    ) -> None:
        await self.conn.execute(
            "INSERT INTO agent_logs (session_id, app_id, agent_name, event_type, message, metadata_json, level) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                app_id,
                agent_name,
                event_type,
                message,
                json.dumps(metadata) if metadata else None,
                level,
            ),
        )
        await self.conn.commit()
