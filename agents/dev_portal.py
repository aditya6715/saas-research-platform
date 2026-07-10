"""
agents/dev_portal.py
--------------------
Developer portal agent.
Classifies Self-Serve / Freemium / Gated by navigating the signup flow
using Browser Use and extracting pricing/access information.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from agents.base import BaseAgent
from database.repository import AgentLogRepository
from tools.browser_client import BrowserClient
from tools.search_client import SearchClient


class DevPortalOutput(BaseModel):
    access_model: str = Field(description="One of: Self-Serve, Freemium, Gated")
    pricing_tier_for_api: str | None = Field(None, description="What pricing tier gives API access")
    signup_url: str | None = Field(None, description="Direct URL to API signup/credentials page")
    evidence_text: str = Field(default="", description="Key text from the portal confirming classification")
    confidence: float = Field(ge=0.0, le=1.0)
    has_sandbox: bool = Field(default=False, description="Whether a sandbox/trial API is available")
    notes: str = Field(default="")


CLASSIFICATION_PROMPT = """You are analyzing a developer portal to determine API access model.

App: {app_name}
Portal URL visited: {portal_url}

Page content extracted:
---
{content}
---

Classify the access model:
- Self-Serve: Developer can get API credentials RIGHT NOW by filling a form. 
  No sales contact, no approval wait. (e.g., "Create free account → get API key")
- Freemium: Limited API access available immediately (free tier), 
  but full/production access requires upgrade or approval.
- Gated: API access requires contacting sales, submitting a business justification,
  or waiting for manual approval. "Contact us", "Request access", "Enterprise only"
  are strong Gated signals.

Also note:
- Is there a sandbox or trial API key available?
- What pricing tier provides API access?
- What is the URL of the credentials/signup page?

Base your classification on EVIDENCE from the page content.
""".strip()


class DevPortalAgent(BaseAgent):
    name = "dev_portal"

    def __init__(
        self,
        llm: ChatOpenAI,
        browser: BrowserClient,
        search: SearchClient,
        log_repo: AgentLogRepository,
        session_id: str,
        evidence_dir: str = "data/evidence",
        max_retries: int = 3,
    ) -> None:
        super().__init__(log_repo, session_id, max_retries)
        self.llm = llm.with_structured_output(DevPortalOutput)
        self.browser = browser
        self.search = search
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    async def _execute(self, state: dict[str, Any]) -> dict[str, Any]:
        app_name: str = state["app_name"]
        doc_url: str | None = state.get("documentation_url")
        app_id: int | None = state.get("app_id")

        # ── Step 1: Find developer signup/portal URL ──────────────────────
        portal_url = await self._find_portal_url(app_name, doc_url)

        # ── Step 2: Extract content from portal ───────────────────────────
        content = ""
        screenshot_path: str | None = None

        if portal_url:
            try:
                content = await self.browser.extract_markdown(portal_url)
                # Take screenshot as evidence
                slug = "".join(c if c.isalnum() else "_" for c in app_name.lower())
                ss_path = self.evidence_dir / f"{slug}_portal.png"
                await self.browser.screenshot(portal_url, str(ss_path))
                screenshot_path = str(ss_path)
            except Exception as e:
                self._logger.warning("Browser extraction failed for %s portal: %s", app_name, e)

        # Fall back to documentation content if browser fails
        if not content:
            chunks = state.get("chunks", [])
            pricing_chunks = [c for c in chunks if any(
                kw in c.get("content", "").lower()
                for kw in ["pricing", "plan", "free", "enterprise", "api key", "credential", "signup", "register"]
            )]
            content = "\n\n".join(c["content"] for c in pricing_chunks[:3])

        if not content:
            await self._log("no_portal_content", f"No portal content for {app_name}", app_id, level="WARNING")
            return {
                **state,
                "access_model": None,
                "pricing_tier_for_api": None,
                "portal_signup_url": portal_url,
                "portal_screenshot": screenshot_path,
                "access_model_confidence": 0.3,
                "has_sandbox": False,
            }

        # ── Step 3: Classify access model ────────────────────────────────
        result: DevPortalOutput = await self.llm.ainvoke(
            CLASSIFICATION_PROMPT.format(
                app_name=app_name,
                portal_url=portal_url or "unknown",
                content=content[:15_000],
            )
        )

        # Validate
        valid_models = {"Self-Serve", "Freemium", "Gated"}
        if result.access_model not in valid_models:
            result.access_model = "Gated"  # default to conservative if LLM returns invalid

        await self._log(
            "access_classified",
            f"{app_name} → {result.access_model} (confidence={result.confidence:.2f})",
            app_id,
            metadata={"access_model": result.access_model, "portal_url": portal_url},
        )

        return {
            **state,
            "access_model": result.access_model,
            "pricing_tier_for_api": result.pricing_tier_for_api,
            "portal_signup_url": result.signup_url or portal_url,
            "portal_screenshot": screenshot_path,
            "access_model_confidence": result.confidence,
            "has_sandbox": result.has_sandbox,
            "portal_evidence_text": result.evidence_text,
        }

    async def _find_portal_url(self, app_name: str, doc_url: str | None) -> str | None:
        """Search for the developer portal / API credentials page."""
        results = await self.search.search(f"{app_name} developer portal API key signup")
        if results:
            # Look for signup/dashboard URLs
            for r in results[:5]:
                url = r.get("url", "")
                if any(kw in url.lower() for kw in ["dashboard", "signup", "register", "console", "portal", "app."]):
                    return url
            return results[0]["url"]
        return doc_url
