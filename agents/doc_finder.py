"""
agents/doc_finder.py
--------------------
Documentation URL discovery agent.
Searches for the official developer documentation URL using web search
and scores each candidate based on domain authority and path structure.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from agents.base import BaseAgent
from database.repository import AgentLogRepository
from tools.search_client import SearchClient

DOC_PATH_PATTERNS = [
    "/docs",
    "/api",
    "/developers",
    "/reference",
    "/developer",
    "/api-reference",
    "/dev",
    "/documentation",
    "/getting-started",
]


class DocFinderAgent(BaseAgent):
    name = "doc_finder"

    def __init__(
        self,
        search_client: SearchClient,
        log_repo: AgentLogRepository,
        session_id: str,
        max_retries: int = 3,
    ) -> None:
        super().__init__(log_repo, session_id, max_retries)
        self.search = search_client

    async def _execute(self, state: dict[str, Any]) -> dict[str, Any]:
        app_name: str = state["app_name"]
        seed_url: str | None = state.get("seed_url")
        app_id: int | None = state.get("app_id")

        candidates: list[dict[str, Any]] = []

        # ── Query 1: developer API documentation ─────────────────────────
        q1_results = await self.search.search(f"{app_name} API documentation developers")
        for r in q1_results[:5]:
            score = self._score_url(r["url"], app_name, seed_url)
            candidates.append(
                {
                    "url": r["url"],
                    "score": score,
                    "source": "web_search_q1",
                    "title": r.get("title", ""),
                }
            )

        # ── Query 2: REST API reference ───────────────────────────────────
        q2_results = await self.search.search(f"{app_name} REST API reference documentation")
        for r in q2_results[:5]:
            score = self._score_url(r["url"], app_name, seed_url)
            # Bonus if URL already seen (cross-query agreement)
            existing_urls = {c["url"] for c in candidates}
            if r["url"] in existing_urls:
                for c in candidates:
                    if c["url"] == r["url"]:
                        c["score"] = min(c["score"] + 0.10, 1.0)
            else:
                candidates.append(
                    {
                        "url": r["url"],
                        "score": score,
                        "source": "web_search_q2",
                        "title": r.get("title", ""),
                    }
                )

        # ── Sort and select best ──────────────────────────────────────────
        candidates.sort(key=lambda x: x["score"], reverse=True)
        best = candidates[0] if candidates else None

        if not best or best["score"] < 0.5:
            await self._log(
                "low_confidence_url",
                f"No documentation URL found with confidence >= 0.5 for {app_name}",
                app_id,
                level="WARNING",
            )
            return {
                **state,
                "documentation_url": None,
                "doc_url_confidence": 0.0,
                "doc_candidates": candidates,
                "human_review_required": True,
            }

        await self._log(
            "url_found",
            f"Selected documentation URL: {best['url']} (score={best['score']:.2f})",
            app_id,
            metadata={"url": best["url"], "score": best["score"]},
        )

        return {
            **state,
            "documentation_url": best["url"],
            "doc_url_confidence": best["score"],
            "doc_candidates": candidates[:10],
            "human_review_required": state.get("human_review_required", False),
        }

    def _score_url(self, url: str, app_name: str, seed_url: str | None) -> float:
        """
        Score a candidate URL based on relevance signals.

        Scoring breakdown:
        +0.40 — Domain contains the app's expected domain
        +0.30 — URL path contains doc-like patterns (/docs, /api, /reference...)
        +0.20 — URL from web search (already applied at call site)
        +0.10 — Seed URL domain matches this URL's domain
        """
        score = 0.0
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path.lower()

        # Domain relevance: does the domain contain an app-name-derived slug?
        app_slug = re.sub(r"[^a-z0-9]", "", app_name.lower())
        if app_slug in domain.replace("-", "").replace(".", ""):
            score += 0.40
        elif any(word in domain for word in app_name.lower().split() if len(word) > 3):
            score += 0.25

        # Path relevance
        if any(pat in path for pat in DOC_PATH_PATTERNS):
            score += 0.30

        # Seed domain match
        if seed_url:
            seed_domain = urlparse(seed_url).netloc.lower()
            if seed_domain and seed_domain in domain:
                score += 0.10

        # Penalize third-party aggregators
        third_party = ["rapidapi.com", "programmableweb.com", "apifox.com", "any-api.com"]
        if any(tp in domain for tp in third_party):
            score -= 0.20

        return round(max(0.0, min(score, 1.0)), 3)
