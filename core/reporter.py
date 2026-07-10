"""
core/reporter.py
----------------
Jinja2-based HTML report generator.
Produces a single self-contained HTML file from SQLite data + statistics.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from jinja2 import Environment, FileSystemLoader, select_autoescape

from database.repository import AppRepository, SessionRepository

logger = logging.getLogger(__name__)


class ReportGenerator:
    def __init__(
        self,
        conn: aiosqlite.Connection,
        session_id: str,
        templates_dir: str | Path = "templates",
        reports_dir: str | Path = "reports",
    ) -> None:
        self.conn = conn
        self.session_id = session_id
        self.templates_dir = Path(templates_dir)
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._app_repo = AppRepository(conn)
        self._sess_repo = SessionRepository(conn)
        self._env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(["html"]),
        )
        self._env.filters["tojson"] = lambda v: json.dumps(v, default=str)

    async def generate(self, statistics: dict[str, Any]) -> str:
        """
        Generate the HTML report. Returns output file path.
        """
        apps = await self._app_repo.get_all_verified(self.session_id)
        session = await self._sess_repo.get(self.session_id)

        # Fetch evidence for each app (for drill-down)
        apps_with_evidence = []
        for app in apps:
            ev_cursor = await self.conn.execute(
                "SELECT field_name, field_value, source_url, extracted_text, confidence "
                "FROM evidence WHERE app_id=? ORDER BY field_name, confidence DESC",
                (app.id,),
            )
            evidence_rows = await ev_cursor.fetchall()
            app_dict = app.model_dump()
            app_dict["evidence"] = [dict(r) for r in evidence_rows]
            # Serialize list fields for JS
            app_dict["auth_methods_str"] = ", ".join(app.auth_methods or [])
            app_dict["api_types_str"] = ", ".join(app.api_types or [])
            apps_with_evidence.append(app_dict)

        # Build chart datasets
        chart_data = self._build_chart_data(statistics)

        context = {
            "session": session.model_dump() if session else {},
            "apps": apps_with_evidence,
            "apps_json": json.dumps(apps_with_evidence, default=str),
            "statistics": statistics,
            "chart_data": chart_data,
            "chart_data_json": json.dumps(chart_data),
            "insights": statistics.get("insights", {}),
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "session_id": self.session_id,
            "total_apps": len(apps),
        }

        template = self._env.get_template("report.html")
        html = template.render(**context)

        short_id = self.session_id[:8]
        output_path = self.reports_dir / f"report_{short_id}.html"
        output_path.write_text(html, encoding="utf-8")
        logger.info("Report generated: %s (%d apps)", output_path, len(apps))
        return str(output_path)

    def _build_chart_data(self, stats: dict[str, Any]) -> dict[str, Any]:
        """Prepare Chart.js-ready datasets from statistics."""

        def to_chartjs(distribution: dict[str, int], colors: list[str] | None = None) -> dict:
            labels = list(distribution.keys())
            data = list(distribution.values())
            default_colors = [
                "#6366f1",
                "#8b5cf6",
                "#06b6d4",
                "#10b981",
                "#f59e0b",
                "#ef4444",
                "#3b82f6",
                "#84cc16",
            ]
            bg = (colors or default_colors)[: len(labels)]
            return {"labels": labels, "datasets": [{"data": data, "backgroundColor": bg}]}

        return {
            "auth": to_chartjs(
                stats.get("auth_distribution", {}),
                ["#6366f1", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b", "#ef4444"],
            ),
            "api_surface": to_chartjs(
                stats.get("api_surface_distribution", {}),
                ["#3b82f6", "#8b5cf6", "#10b981", "#f59e0b", "#ef4444", "#6b7280"],
            ),
            "access_model": to_chartjs(
                stats.get("access_model_distribution", {}),
                ["#10b981", "#f59e0b", "#ef4444"],
            ),
            "buildability": to_chartjs(
                stats.get("buildability_distribution", {}),
                ["#10b981", "#f59e0b", "#ef4444"],
            ),
            "mcp_support": to_chartjs(
                stats.get("mcp_support_distribution", {}),
                ["#6366f1", "#8b5cf6", "#06b6d4", "#6b7280"],
            ),
        }
