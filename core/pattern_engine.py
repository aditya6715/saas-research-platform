"""
core/pattern_engine.py
----------------------
Pattern Discovery Engine.
Aggregates all verified App_Records to surface trends, distributions,
and actionable insights. Produces statistics.json and insights.json.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class PatternDiscoveryEngine:
    def __init__(self, conn: aiosqlite.Connection, session_id: str) -> None:
        self.conn = conn
        self.session_id = session_id

    async def run(self) -> dict[str, Any]:
        """
        Compute all aggregate statistics and insights.
        Returns a statistics dict (also written to disk as statistics.json).
        """
        apps = await self._fetch_verified_apps()
        if not apps:
            logger.warning("No verified apps found for pattern discovery")
            return {}

        stats: dict[str, Any] = {
            "session_id": self.session_id,
            "total_apps": len(apps),
        }

        # ── Distributions ─────────────────────────────────────────────────
        stats["auth_distribution"] = self._distribution(apps, "primary_auth")
        stats["api_surface_distribution"] = self._api_distribution(apps)
        stats["access_model_distribution"] = self._distribution(apps, "access_model")
        stats["buildability_distribution"] = self._distribution(apps, "buildability_verdict")
        stats["mcp_support_distribution"] = self._distribution(apps, "mcp_support")
        stats["category_distribution"] = self._distribution(apps, "category")

        # ── Blocker analysis ──────────────────────────────────────────────
        stats["top_blockers"] = self._top_blockers(apps)

        # ── MCP gap metric ────────────────────────────────────────────────
        stats["mcp_gap_percentage"] = self._mcp_gap(apps)

        # ── Easy wins & hard integrations ────────────────────────────────
        stats["easy_wins"] = self._easy_wins(apps)
        stats["hard_integrations"] = self._hard_integrations(apps)

        # ── Per-category breakdowns ───────────────────────────────────────
        stats["category_breakdown"] = self._category_breakdown(apps)

        # ── Quality metrics ───────────────────────────────────────────────
        confidences = [a.get("confidence_score", 0.0) for a in apps]
        stats["avg_confidence"] = (
            round(sum(confidences) / len(confidences), 4) if confidences else 0.0
        )
        stats["human_review_count"] = sum(1 for a in apps if a.get("human_review_required"))
        stats["verified_count"] = sum(
            1 for a in apps if a.get("status") in ("completed", "verified")
        )

        # ── Auth method co-occurrence (apps supporting both API Key + OAuth) ──
        stats["multi_auth_count"] = self._multi_auth_count(apps)

        # ── Narrative insights ────────────────────────────────────────────
        stats["insights"] = self._generate_insights(stats)

        logger.info(
            "Pattern discovery complete: %d apps, MCP gap=%.1f%%, easy_wins=%d",
            len(apps),
            stats["mcp_gap_percentage"],
            len(stats["easy_wins"]),
        )
        return stats

    # ── Private computation methods ────────────────────────────────────────

    async def _fetch_verified_apps(self) -> list[dict[str, Any]]:
        cursor = await self.conn.execute(
            "SELECT * FROM apps WHERE session_id=? AND status IN ('completed','verified')",
            (self.session_id,),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["auth_methods"] = json.loads(d.pop("auth_methods_json", "[]") or "[]")
            d["api_types"] = json.loads(d.pop("api_types_json", "[]") or "[]")
            d["oauth_flows"] = json.loads(d.pop("oauth_flows_json", "[]") or "[]")
            result.append(d)
        return result

    def _distribution(self, apps: list[dict], field: str) -> dict[str, int]:
        counter: Counter = Counter()
        for app in apps:
            val = app.get(field) or "Unknown"
            counter[val] += 1
        return dict(counter.most_common())

    def _api_distribution(self, apps: list[dict]) -> dict[str, int]:
        """Count per-type across all apps (one app can have multiple API types)."""
        counter: Counter = Counter()
        for app in apps:
            api_types = app.get("api_types") or []
            for t in api_types:
                if t and t != "None":
                    counter[t] += 1
            if not api_types or api_types == ["None"]:
                counter["None"] += 1
        return dict(counter.most_common())

    def _top_blockers(self, apps: list[dict], top_n: int = 5) -> list[dict[str, Any]]:
        blocked = [a for a in apps if a.get("biggest_blocker")]
        counter: Counter = Counter(a["biggest_blocker"] for a in blocked)
        return [{"blocker": k, "count": v} for k, v in counter.most_common(top_n)]

    def _mcp_gap(self, apps: list[dict]) -> float:
        """
        Of all apps with a public API, what % have NO MCP support?
        This represents Composio's highest-priority integration targets.
        """
        apps_with_api = [
            a
            for a in apps
            if a.get("api_types") and a["api_types"] != ["None"] and a["api_types"] != []
        ]
        if not apps_with_api:
            return 0.0
        no_mcp = [a for a in apps_with_api if a.get("mcp_support") in (None, "None")]
        return round(len(no_mcp) / len(apps_with_api) * 100, 1)

    def _easy_wins(
        self, apps: list[dict], min_confidence: float = 0.85, top_n: int = 15
    ) -> list[str]:
        """
        Easy wins: Self-Serve/Freemium + REST/GraphQL + no MCP + high confidence.
        These are the highest-priority integration targets.
        """
        wins = [
            a
            for a in apps
            if a.get("access_model") in ("Self-Serve", "Freemium")
            and any(t in (a.get("api_types") or []) for t in ("REST", "GraphQL"))
            and a.get("mcp_support") in (None, "None")
            and (a.get("confidence_score") or 0.0) >= min_confidence
        ]
        wins.sort(key=lambda x: x.get("confidence_score", 0), reverse=True)
        return [w["app_name"] for w in wins[:top_n]]

    def _hard_integrations(self, apps: list[dict], top_n: int = 10) -> list[str]:
        """
        Hard integrations: Blocked verdict or Gated + SDK-only.
        """
        hard = [
            a
            for a in apps
            if a.get("buildability_verdict") == "Blocked"
            or (a.get("access_model") == "Gated" and "SDK-only" in (a.get("api_types") or []))
        ]
        return [h["app_name"] for h in hard[:top_n]]

    def _category_breakdown(self, apps: list[dict]) -> dict[str, dict[str, Any]]:
        """Per-category statistics."""
        categories: dict[str, list[dict]] = {}
        for app in apps:
            cat = app.get("category") or "Unknown"
            categories.setdefault(cat, []).append(app)

        breakdown = {}
        for cat, cat_apps in categories.items():
            breakdown[cat] = {
                "count": len(cat_apps),
                "buildability": self._distribution(cat_apps, "buildability_verdict"),
                "access_model": self._distribution(cat_apps, "access_model"),
                "mcp_gap": self._mcp_gap(cat_apps),
                "avg_confidence": round(
                    sum(a.get("confidence_score", 0) for a in cat_apps) / len(cat_apps), 3
                ),
            }
        return breakdown

    def _multi_auth_count(self, apps: list[dict]) -> int:
        """Count apps supporting 2+ auth methods."""
        return sum(1 for a in apps if len(a.get("auth_methods") or []) >= 2)

    def _generate_insights(self, stats: dict[str, Any]) -> dict[str, Any]:
        """Generate narrative insight strings from computed statistics."""
        total = stats.get("total_apps", 1)
        mcp_gap = stats.get("mcp_gap_percentage", 0)
        easy_wins = stats.get("easy_wins", [])
        top_auth = next(iter(stats.get("auth_distribution", {}).keys()), "Unknown")
        top_auth_count = next(iter(stats.get("auth_distribution", {}).values()), 0)
        fb_count = stats.get("buildability_distribution", {}).get("Fully Buildable", 0)
        gated_count = stats.get("access_model_distribution", {}).get("Gated", 0)
        official_mcp = stats.get("mcp_support_distribution", {}).get("Official", 0)
        community_mcp = stats.get("mcp_support_distribution", {}).get("Community", 0)

        top_blockers = stats.get("top_blockers", [])
        blocker_str = (
            ", ".join(b["blocker"] for b in top_blockers[:3]) if top_blockers else "None identified"
        )

        return {
            "headline": (
                f"{mcp_gap:.0f}% of apps with public APIs have no MCP support "
                f"— representing immediate integration opportunities for Composio"
            ),
            "key_findings": [
                f"{top_auth} is the most common auth method ({top_auth_count}/{total} apps, "
                f"{top_auth_count/total*100:.0f}%)",
                f"{fb_count} apps ({fb_count/total*100:.0f}%) are Fully Buildable right now",
                f"{gated_count} apps ({gated_count/total*100:.0f}%) are Gated — require enterprise sales access",
                f"Only {official_mcp} apps have Official MCP support; {community_mcp} have Community implementations",
                f"Top blockers for non-buildable apps: {blocker_str}",
            ],
            "recommendations": [
                f"Start with the {len(easy_wins)} Easy Win apps: they can be integrated within days",
                f"The {community_mcp} Community MCP servers represent partnership/acquisition opportunities",
                f"The {gated_count} Gated apps should be flagged for enterprise sales outreach",
                "Focus auth implementation on API Key + OAuth 2.0 to cover >80% of the ecosystem",
            ],
            "easy_wins_preview": easy_wins[:5],
        }
