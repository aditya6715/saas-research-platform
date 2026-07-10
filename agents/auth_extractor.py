"""
agents/auth_extractor.py
------------------------
Authentication method extraction agent.
Uses GPT-4o with structured output to identify all auth methods from docs.
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from agents.base import BaseAgent
from database.repository import AgentLogRepository

VALID_AUTH_METHODS = [
    "API Key",
    "OAuth 2.0",
    "OAuth 1.0a",
    "Basic Auth",
    "JWT",
    "SAML",
    "OpenID Connect",
    "Session Cookie",
    "HMAC",
    "Custom",
]

OAUTH_FLOWS = [
    "authorization_code",
    "client_credentials",
    "implicit",
    "device_code",
    "pkce",
]


class AuthMethodResult(BaseModel):
    method: str = Field(description="One of the valid auth method names")
    confidence: float = Field(ge=0.0, le=1.0, description="Extraction confidence 0-1")
    oauth_flows: list[str] = Field(
        default_factory=list, description="OAuth flows if method is OAuth 2.0"
    )
    evidence_snippet: str = Field(default="", description="Exact quote from docs (max 300 chars)")
    source_url: str = Field(default="", description="Source URL for this finding")


class AuthExtractionOutput(BaseModel):
    auth_methods: list[AuthMethodResult] = Field(description="All detected auth methods")
    primary_method: str = Field(description="The most prominent/recommended auth method")
    notes: str = Field(default="", description="Any relevant auth notes not captured above")


EXTRACTION_PROMPT = """You are an API authentication specialist analyzing developer documentation.

Extract ALL authentication methods supported by this API.

Valid authentication methods:
{methods}

For each method found:
1. Quote the EXACT text that proves it (max 200 characters)
2. Note the source URL of the documentation page
3. Assign confidence:
   - 0.90–1.00: Method is explicitly named in the documentation
   - 0.70–0.89: Method is strongly implied (e.g., "Bearer token" implies API Key)
   - 0.50–0.69: Method is uncertain or inferred from code examples
4. For OAuth 2.0, extract which flows are supported: {oauth_flows}

IMPORTANT: Do not invent or guess methods not supported by evidence in the text.
If no authentication information is present, return an empty list.

Documentation content:
---
{content}
---
""".strip()


class AuthExtractorAgent(BaseAgent):
    name = "auth_extractor"

    def __init__(
        self,
        llm: ChatOpenAI,
        log_repo: AgentLogRepository,
        session_id: str,
        max_retries: int = 3,
    ) -> None:
        super().__init__(log_repo, session_id, max_retries)
        self.llm = llm.with_structured_output(AuthExtractionOutput)

    async def _execute(self, state: dict[str, Any]) -> dict[str, Any]:
        chunks: list[dict] = state.get("chunks", [])
        app_id: int | None = state.get("app_id")
        app_name: str = state.get("app_name", "unknown")

        if not chunks:
            await self._log(
                "no_content", "No chunks available for auth extraction", app_id, level="WARNING"
            )
            return {**state, "auth_result": None, "auth_confidence": 0.0}

        # Prioritize auth-relevant chunks
        auth_chunks = [
            c
            for c in chunks
            if any(
                kw in c.get("content", "").lower()
                for kw in ["auth", "api key", "oauth", "bearer", "token", "credential", "secret"]
            )
        ]
        target_chunks = (auth_chunks or chunks)[:6]  # max ~48k chars

        combined_content = "\n\n---\n\n".join(
            f"[Source: {c['source_url']}]\n{c['content']}" for c in target_chunks
        )

        prompt = EXTRACTION_PROMPT.format(
            methods=", ".join(VALID_AUTH_METHODS),
            oauth_flows=", ".join(OAUTH_FLOWS),
            content=combined_content[:40_000],
        )

        result: AuthExtractionOutput = await self.llm.ainvoke(prompt)

        # Filter to valid method names only
        valid_results = [r for r in result.auth_methods if r.method in VALID_AUTH_METHODS]

        if not valid_results:
            await self._log(
                "no_auth_found",
                f"No authentication methods identified for {app_name}",
                app_id,
                level="WARNING",
            )
            return {
                **state,
                "auth_result": None,
                "auth_methods": [],
                "primary_auth": None,
                "oauth_flows": [],
                "auth_confidence": 0.0,
            }

        primary = (
            result.primary_method
            if result.primary_method in VALID_AUTH_METHODS
            else valid_results[0].method
        )
        avg_confidence = sum(r.confidence for r in valid_results) / len(valid_results)

        await self._log(
            "auth_extracted",
            f"Found {len(valid_results)} auth methods for {app_name}: {[r.method for r in valid_results]}",
            app_id,
            metadata={"methods": [r.method for r in valid_results], "primary": primary},
        )

        # Collect OAuth flows from any OAuth 2.0 result
        all_oauth_flows: list[str] = []
        for r in valid_results:
            if r.method == "OAuth 2.0":
                all_oauth_flows.extend(r.oauth_flows)
        all_oauth_flows = list(set(all_oauth_flows))

        return {
            **state,
            "auth_result": [r.model_dump() for r in valid_results],
            "auth_methods": [r.method for r in valid_results],
            "primary_auth": primary,
            "oauth_flows": all_oauth_flows,
            "auth_confidence": round(avg_confidence, 4),
        }
