"""
agents/verifier.py
------------------
Independent verification agent.
Performs a second extraction pass using different prompts and sources,
then compares with pass A results to compute agreement and confidence.
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from agents.base import BaseAgent
from core.confidence import compute_field_confidence
from database.models import VerificationRecord
from database.repository import AgentLogRepository, VerificationRepository


class VerificationPassOutput(BaseModel):
    auth_methods: list[str] = Field(default_factory=list)
    primary_auth: str | None = None
    api_types: list[str] = Field(default_factory=list)
    access_model: str | None = None
    mcp_support: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    notes: str = ""


VERIFICATION_PROMPT = """You are a skeptical API integration auditor performing an independent verification.

Your job is to VERIFY (not just accept) information about this API.
Be critical. Look for contradictions. Do not simply echo what seems obvious.

App: {app_name}
Documentation URL: {doc_url}

Documentation content (independent sample):
---
{content}
---

Verify the following fields by finding evidence:
1. Authentication methods (what auth does this API actually use?)
2. API types (REST? GraphQL? Something else?)
3. Access model (can you truly sign up RIGHT NOW without contacting sales?)
4. MCP support (is there actually a working MCP server for this?)

Return only what you can VERIFY from the text above.
If you cannot confirm a field, return null for that field.
""".strip()


# Fields to verify and compare between passes
VERIFICATION_FIELDS = ["auth_methods", "api_types", "access_model", "mcp_support"]


class VerifierAgent(BaseAgent):
    name = "verifier"

    def __init__(
        self,
        llm: ChatOpenAI,
        verification_repo: VerificationRepository,
        log_repo: AgentLogRepository,
        session_id: str,
        max_retries: int = 2,
    ) -> None:
        super().__init__(log_repo, session_id, max_retries)
        self.llm = llm.with_structured_output(VerificationPassOutput)
        self.verification_repo = verification_repo

    async def _execute(self, state: dict[str, Any]) -> dict[str, Any]:
        app_id: int | None = state.get("app_id")
        app_name: str = state.get("app_name", "unknown")
        doc_url: str | None = state.get("documentation_url")
        chunks: list[dict] = state.get("chunks", [])

        if not chunks:
            await self._log("skip", "No chunks for verification", app_id, level="WARNING")
            return {**state, "verification_complete": False}

        # Use a DIFFERENT sample of chunks than pass A (last half)
        mid = max(1, len(chunks) // 2)
        verify_chunks = chunks[mid : mid + 4] or chunks[:4]
        combined = "\n\n---\n\n".join(
            f"[Source: {c['source_url']}]\n{c['content']}" for c in verify_chunks
        )

        pass_b: VerificationPassOutput = await self.llm.ainvoke(
            VERIFICATION_PROMPT.format(
                app_name=app_name,
                doc_url=doc_url or "unknown",
                content=combined[:30_000],
            )
        )

        # ── Compare Pass A vs Pass B ──────────────────────────────────────
        field_updates: dict[str, Any] = {}
        verification_records: list[VerificationRecord] = []

        for field in VERIFICATION_FIELDS:
            pass_a_val = self._get_pass_a_value(state, field)
            pass_b_val = self._get_pass_b_value(pass_b, field)

            agreement = self._values_agree(pass_a_val, pass_b_val)
            tiebreaker_needed = not agreement and pass_a_val is not None and pass_b_val is not None

            base_confidence = state.get(f"{field.replace('_methods', '')}_confidence", 0.7)
            if field == "auth_methods":
                base_confidence = state.get("auth_confidence", 0.7)
            elif field == "api_types":
                base_confidence = state.get("api_confidence", 0.7)
            elif field == "access_model":
                base_confidence = state.get("access_model_confidence", 0.7)

            field_conf = compute_field_confidence(
                evidence_confidence=base_confidence,
                source_agreement=agreement,
                tiebreaker_used=False,  # tiebreaker hasn't run yet
            )

            final_val = pass_a_val  # Default to pass A; tiebreaker may override

            vr = VerificationRecord(
                app_id=app_id,
                field_name=field,
                pass_a_value=str(pass_a_val) if pass_a_val is not None else None,
                pass_b_value=str(pass_b_val) if pass_b_val is not None else None,
                final_value=str(final_val) if final_val is not None else None,
                agreement=agreement,
                tiebreaker_used=tiebreaker_needed,
                confidence_before=base_confidence,
                confidence_after=field_conf,
            )
            await self.verification_repo.create(vr)
            verification_records.append(vr)

            field_updates[f"{field}_verified_confidence"] = field_conf
            field_updates[f"{field}_needs_tiebreaker"] = tiebreaker_needed
            field_updates[f"pass_b_{field}"] = pass_b_val

        await self._log(
            "verification_complete",
            f"Verified {len(VERIFICATION_FIELDS)} fields for {app_name}",
            app_id,
            metadata={
                "agreements": sum(1 for vr in verification_records if vr.agreement),
                "tiebreakers_needed": sum(1 for vr in verification_records if vr.tiebreaker_used),
            },
        )

        return {
            **state,
            **field_updates,
            "verification_complete": True,
            "pass_b_result": pass_b.model_dump(),
        }

    def _get_pass_a_value(self, state: dict[str, Any], field: str) -> Any:
        if field == "auth_methods":
            return state.get("auth_methods")
        if field == "api_types":
            return state.get("api_types")
        if field == "access_model":
            return state.get("access_model")
        if field == "mcp_support":
            return state.get("mcp_support")
        return None

    def _get_pass_b_value(self, result: VerificationPassOutput, field: str) -> Any:
        return getattr(result, field, None)

    def _values_agree(self, a: Any, b: Any) -> bool:
        """Compare two values for agreement. Lists compared as sets."""
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        if isinstance(a, list) and isinstance(b, list):
            return {str(x) for x in a} == {str(x) for x in b}
        return str(a).strip().lower() == str(b).strip().lower()
