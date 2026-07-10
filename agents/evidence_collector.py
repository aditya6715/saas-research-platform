"""
agents/evidence_collector.py
-----------------------------
Evidence consolidation agent.
Creates structured Evidence objects from all extraction agent outputs,
validates source URLs, and writes to SQLite.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from agents.base import BaseAgent
from database.models import EvidenceRecord
from database.repository import AgentLogRepository, EvidenceRepository


class EvidenceCollectorAgent(BaseAgent):
    name = "evidence_collector"

    def __init__(
        self,
        evidence_repo: EvidenceRepository,
        log_repo: AgentLogRepository,
        session_id: str,
        max_retries: int = 2,
    ) -> None:
        super().__init__(log_repo, session_id, max_retries)
        self.evidence_repo = evidence_repo
        self._url_cache: dict[str, bool] = {}  # URL → is_valid

    async def _execute(self, state: dict[str, Any]) -> dict[str, Any]:
        app_id: int | None = state.get("app_id")
        app_name: str = state.get("app_name", "unknown")

        if not app_id:
            await self._log(
                "skip", "No app_id in state — cannot persist evidence", app_id, level="WARNING"
            )
            return state

        evidence_created = 0

        # ── Auth methods evidence ─────────────────────────────────────────
        auth_result = state.get("auth_result") or []
        for auth_item in auth_result:
            src = auth_item.get("source_url") or state.get("documentation_url") or ""
            if src and self._is_https(src):
                await self.evidence_repo.create(
                    EvidenceRecord(
                        app_id=app_id,
                        field_name="auth_methods",
                        field_value=auth_item.get("method"),
                        source_url=src,
                        extracted_text=auth_item.get("evidence_snippet", "")[:500],
                        extraction_method="gpt4o_structured",
                        confidence=auth_item.get("confidence", 0.0),
                    )
                )
                evidence_created += 1
            else:
                await self._log(
                    "invalid_evidence_url",
                    f"Auth evidence missing valid URL for {app_name}",
                    app_id,
                    level="WARNING",
                )

        # ── API types evidence ────────────────────────────────────────────
        api_snippet = state.get("api_evidence_snippet", "")
        api_src = state.get("api_source_url") or state.get("documentation_url") or ""
        if api_src and self._is_https(api_src) and state.get("api_types"):
            await self.evidence_repo.create(
                EvidenceRecord(
                    app_id=app_id,
                    field_name="api_types",
                    field_value=", ".join(state["api_types"]),
                    source_url=api_src,
                    extracted_text=api_snippet[:500],
                    extraction_method="gpt4o_structured",
                    confidence=state.get("api_confidence", 0.0),
                )
            )
            evidence_created += 1

        # ── Access model evidence ────────────────────────────────────────
        portal_src = state.get("portal_signup_url") or state.get("documentation_url") or ""
        portal_text = state.get("portal_evidence_text", "")
        if state.get("access_model") and portal_src and self._is_https(portal_src):
            await self.evidence_repo.create(
                EvidenceRecord(
                    app_id=app_id,
                    field_name="access_model",
                    field_value=state["access_model"],
                    source_url=portal_src,
                    extracted_text=portal_text[:500],
                    extraction_method="browser_use+gpt4o",
                    confidence=state.get("access_model_confidence", 0.0),
                )
            )
            evidence_created += 1

        # ── MCP support evidence ──────────────────────────────────────────
        mcp_src = state.get("mcp_repo_url") or state.get("documentation_url") or ""
        if state.get("mcp_support") and mcp_src and self._is_https(mcp_src):
            await self.evidence_repo.create(
                EvidenceRecord(
                    app_id=app_id,
                    field_name="mcp_support",
                    field_value=state["mcp_support"],
                    source_url=mcp_src,
                    extracted_text=f"MCP support: {state['mcp_support']}",
                    extraction_method="web_search+gpt4o",
                    confidence=state.get("mcp_confidence", 0.0),
                )
            )
            evidence_created += 1

        # ── Documentation URL evidence ────────────────────────────────────
        doc_url = state.get("documentation_url")
        if doc_url and self._is_https(doc_url):
            await self.evidence_repo.create(
                EvidenceRecord(
                    app_id=app_id,
                    field_name="documentation_url",
                    field_value=doc_url,
                    source_url=doc_url,
                    extracted_text="Official developer documentation",
                    extraction_method="web_search",
                    confidence=state.get("doc_url_confidence", 0.0),
                )
            )
            evidence_created += 1

        await self._log(
            "evidence_collected",
            f"Created {evidence_created} evidence records for {app_name}",
            app_id,
            metadata={"count": evidence_created},
        )

        return {**state, "evidence_count": evidence_created}

    def _is_https(self, url: str) -> bool:
        """Check if URL is a valid HTTPS URL (cached)."""
        if url in self._url_cache:
            return self._url_cache[url]
        try:
            parsed = urlparse(url)
            valid = parsed.scheme in ("https", "http") and bool(parsed.netloc)
            self._url_cache[url] = valid
            return valid
        except Exception:
            self._url_cache[url] = False
            return False
