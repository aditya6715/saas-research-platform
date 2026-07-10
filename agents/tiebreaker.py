"""
agents/tiebreaker.py
--------------------
Tiebreaker agent for resolving disagreements between extraction passes.
Reads both values and selects the better-supported one with reasoning.
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from agents.base import BaseAgent
from database.repository import AgentLogRepository


class TiebreakerOutput(BaseModel):
    selected_value: str = Field(description="The better-supported value")
    reasoning: str = Field(description="One sentence explaining the choice")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the selected value")


TIEBREAKER_PROMPT = """Two independent extraction passes produced different values for the field "{field_name}".

App: {app_name}

Pass A result: {value_a}
Pass A evidence: "{snippet_a}"

Pass B result: {value_b}
Pass B evidence: "{snippet_b}"

Evaluate both results and select the better-supported answer.

Rules:
- Prefer the value that has stronger documentary evidence (explicit naming > implication)
- Prefer the more specific value over the more generic one
- If both are equally supported, prefer the more conservative/safer value
- Explain your choice in ONE sentence citing the specific evidence

Return the selected_value as exactly one of the original values (Pass A or Pass B),
not a new value you invented.
""".strip()


class TiebreakerAgent(BaseAgent):
    name = "tiebreaker"

    def __init__(
        self,
        llm: ChatOpenAI,
        log_repo: AgentLogRepository,
        session_id: str,
        max_retries: int = 2,
    ) -> None:
        super().__init__(log_repo, session_id, max_retries)
        self.llm = llm.with_structured_output(TiebreakerOutput)

    async def _execute(self, state: dict[str, Any]) -> dict[str, Any]:
        app_id: int | None = state.get("app_id")
        app_name: str = state.get("app_name", "unknown")

        fields_needing_tiebreaker = [
            f
            for f in ["auth_methods", "api_types", "access_model", "mcp_support"]
            if state.get(f"{f}_needs_tiebreaker")
        ]

        if not fields_needing_tiebreaker:
            return state

        updates: dict[str, Any] = {}

        for field in fields_needing_tiebreaker:
            value_a = state.get(field)
            value_b = state.get(f"pass_b_{field}")

            if value_a is None or value_b is None:
                # One is null — use the non-null value
                updates[field] = value_a if value_a is not None else value_b
                continue

            # Get evidence snippets from state
            snippet_a = ""
            snippet_b = ""
            if field == "auth_methods":
                auth_result = state.get("auth_result") or []
                snippet_a = "; ".join(r.get("evidence_snippet", "") for r in auth_result[:2])
            elif field == "access_model":
                snippet_a = state.get("portal_evidence_text", "")

            result: TiebreakerOutput = await self.llm.ainvoke(
                TIEBREAKER_PROMPT.format(
                    field_name=field,
                    app_name=app_name,
                    value_a=str(value_a),
                    snippet_a=snippet_a[:300],
                    value_b=str(value_b),
                    snippet_b=snippet_b[:300],
                )
            )

            await self._log(
                "tiebreaker_resolved",
                f"Field '{field}' resolved to: {result.selected_value} — {result.reasoning}",
                app_id,
                metadata={
                    "field": field,
                    "value_a": str(value_a),
                    "value_b": str(value_b),
                    "selected": result.selected_value,
                    "reasoning": result.reasoning,
                },
            )

            updates[field] = result.selected_value
            updates[f"{field}_tiebreaker_reasoning"] = result.reasoning

        return {**state, **updates}
