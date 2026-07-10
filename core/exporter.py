"""
core/exporter.py
----------------
Exports SQLite data to JSON files:
  - data_export.json: Full structured export of all app records + evidence
  - human_review.json: Only flagged records needing human review
  - run_summary.json: Session-level metrics
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

from database.models import AppRecord
from database.repository import AppRepository, EvidenceRepository, SessionRepository

logger = logging.getLogger(__name__)


class DataExporter:
    def __init__(
        self,
        conn: aiosqlite.Connection,
        session_id: str,
        output_dir: str | Path = "data/exports",
    ) -> None:
        self.conn = conn
        self.session_id = session_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._app_repo = AppRepository(conn)
        self._ev_repo = EvidenceRepository(conn)
        self._sess_repo = SessionRepository(conn)

    async def export_all(self) -> dict[str, str]:
        """Run all exports. Returns dict of export_type → filepath."""
        paths: dict[str, str] = {}
        paths["data_export"] = await self.export_data()
        paths["human_review"] = await self.export_human_review()
        paths["run_summary"] = await self.export_run_summary()
        return paths

    async def export_data(self) -> str:
        """Export all verified app records with nested evidence arrays."""
        apps = await self._app_repo.get_all_verified(self.session_id)
        records = []
        for app in apps:
            app_dict = app.model_dump()
            # Attach evidence
            evidence_list = await self._ev_repo.get_for_app(app.id)  # type: ignore[arg-type]
            app_dict["evidence"] = [e.model_dump() for e in evidence_list]
            records.append(app_dict)

        output = {
            "session_id": self.session_id,
            "total_records": len(records),
            "apps": records,
        }
        path = self.output_dir / f"data_export_{self.session_id[:8]}.json"
        path.write_text(json.dumps(output, indent=2, default=str))
        logger.info("Exported %d app records to %s", len(records), path)
        return str(path)

    async def export_human_review(self) -> str:
        """Export only apps flagged for human review with context for reviewers."""
        cursor = await self.conn.execute(
            "SELECT * FROM apps WHERE session_id=? AND human_review_required=1",
            (self.session_id,),
        )
        rows = await cursor.fetchall()
        review_items = []
        for row in rows:
            import json as _json
            d = dict(row)
            d["auth_methods"] = _json.loads(d.pop("auth_methods_json", "[]") or "[]")
            d["api_types"] = _json.loads(d.pop("api_types_json", "[]") or "[]")
            d["oauth_flows"] = _json.loads(d.pop("oauth_flows_json", "[]") or "[]")
            app_id = d["id"]

            # Attach evidence for reviewers
            evidence_list = await self._ev_repo.get_for_app(app_id)
            d["evidence"] = [e.model_dump() for e in evidence_list]

            # Add review instructions
            d["_review_instructions"] = (
                "Edit the fields marked with low confidence. "
                "Add 'reviewer_name' and optionally 'review_notes'. "
                "Set 'allow_overwrite': true to allow future automated runs to update this record."
            )
            review_items.append(d)

        output = {
            "session_id": self.session_id,
            "review_count": len(review_items),
            "instructions": (
                "Edit the fields below and run: python main.py import-review --file human_review.json"
            ),
            "items": review_items,
        }
        path = self.output_dir / "human_review.json"
        path.write_text(json.dumps(output, indent=2, default=str))
        logger.info("Exported %d human review items to %s", len(review_items), path)
        return str(path)

    async def export_run_summary(self) -> str:
        """Export session-level run summary metrics."""
        session = await self._sess_repo.get(self.session_id)
        if not session:
            return ""

        counts = await self._app_repo.count_by_status(self.session_id)
        summary = {
            "session_id": self.session_id,
            "started_at": session.started_at,
            "completed_at": session.completed_at,
            "total_apps": session.total_apps,
            "completed_apps": counts.get("completed", 0) + counts.get("verified", 0),
            "failed_apps": counts.get("failed", 0),
            "avg_confidence_score": session.avg_confidence,
            "human_review_count": session.human_review_count,
            "total_api_calls": session.total_api_calls,
            "cache_hit_ratio": session.cache_hit_ratio,
            "estimated_cost_usd": session.estimated_cost_usd,
            "status_breakdown": counts,
        }
        path = self.output_dir / "run_summary.json"
        path.write_text(json.dumps(summary, indent=2, default=str))
        logger.info("Run summary exported to %s", path)
        return str(path)

    async def import_human_review(self, review_file: str | Path) -> int:
        """
        Apply human corrections from a human_review.json file.
        Returns count of records updated.
        """
        data = json.loads(Path(review_file).read_text())
        items = data.get("items", [])
        updated = 0

        for item in items:
            app_id = item.get("id")
            reviewer = item.get("reviewer_name", "").strip()
            if not app_id or not reviewer:
                continue

            # Build update dict from corrected fields
            import json as _json
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            updates: dict[str, Any] = {
                "human_reviewed_by": reviewer,
                "human_reviewed_at": now,
                "human_review_required": 0,
                "confidence_score": 1.0,
                "status": "verified",
            }

            # Apply editable fields
            for field in [
                "category", "description", "primary_auth", "access_model",
                "buildability_verdict", "biggest_blocker", "documentation_url",
                "mcp_support", "mcp_repo_url", "base_api_url", "rate_limits",
            ]:
                if field in item and item[field] is not None:
                    updates[field] = item[field]

            if "auth_methods" in item:
                updates["auth_methods_json"] = _json.dumps(item["auth_methods"])
            if "api_types" in item:
                updates["api_types_json"] = _json.dumps(item["api_types"])

            # Record the review in human_reviews table
            await self.conn.execute(
                "INSERT INTO human_reviews (app_id, field_name, original_value, corrected_value, "
                "reviewer_name, reason, allow_overwrite) VALUES (?,?,?,?,?,?,?)",
                (
                    app_id, "bulk_review", "pre-review",
                    _json.dumps({k: v for k, v in item.items() if not k.startswith("_")}),
                    reviewer,
                    item.get("review_notes", ""),
                    int(item.get("allow_overwrite", False)),
                ),
            )

            await self._app_repo.update_fields(app_id, updates)
            updated += 1

        await self.conn.commit()
        logger.info("Imported %d human review corrections", updated)
        return updated
