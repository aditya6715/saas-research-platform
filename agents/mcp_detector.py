"""
agents/mcp_detector.py
----------------------
MCP (Model Context Protocol) support detection agent.
Searches GitHub, the MCP registry, and app documentation.
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from agents.base import BaseAgent
from database.repository import AgentLogRepository
from tools.search_client import SearchClient

MCP_REGISTRY_URL = "https://github.com/modelcontextprotocol/servers"

VALID_MCP_STATUS = ["Official", "Community", "In-Progress", "None"]


class MCPDetectionOutput(BaseModel):
    mcp_support: str = Field(description="One of: Official, Community, In-Progress, None")
    mcp_repo_url: str | None = Field(None, description="GitHub repository URL for MCP server")
    mcp_version: str | None = Field(None, description="Version if found")
    last_commit_date: str | None = Field(None, description="ISO date of last commit")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_text: str = Field(default="")


DETECTION_PROMPT = """You are analyzing search results to determine if {app_name} has MCP (Model Context Protocol) support.

MCP is an open standard for exposing tools to AI agents via standardized servers.

Search results to analyze:
---
{search_results}
---

Classify MCP support:
- Official: The app company itself has published an MCP server
- Community: A third-party developer has published an MCP server for this app
- In-Progress: There is an open issue, PR, or announcement about MCP support coming
- None: No evidence of MCP support exists

If a repository is found, extract:
- Repository URL
- Version (from tags/releases)
- Last commit date

Assign confidence based on:
- 0.9+: Direct GitHub repo found with working MCP implementation
- 0.7–0.89: Repository found but may be incomplete or outdated
- 0.5–0.69: Indirect evidence (issue, mention in docs)
- 0.3–0.49: Uncertain, could not verify
""".strip()


class MCPDetectorAgent(BaseAgent):
    name = "mcp_detector"

    def __init__(
        self,
        llm: ChatOpenAI,
        search: SearchClient,
        log_repo: AgentLogRepository,
        session_id: str,
        github_token: str | None = None,
        max_retries: int = 3,
    ) -> None:
        super().__init__(log_repo, session_id, max_retries)
        self.llm = llm.with_structured_output(MCPDetectionOutput)
        self.search = search
        self.github_token = github_token

    async def _execute(self, state: dict[str, Any]) -> dict[str, Any]:
        app_name: str = state["app_name"]
        app_id: int | None = state.get("app_id")

        # ── Multiple search strategies ────────────────────────────────────
        all_results: list[str] = []

        # Strategy 1: Direct GitHub search
        q1 = await self.search.search(f'"{app_name}" MCP server model context protocol github')
        all_results.extend(self._format_results(q1))

        # Strategy 2: MCP registry search
        q2 = await self.search.search(f"site:github.com/modelcontextprotocol {app_name}")
        all_results.extend(self._format_results(q2))

        # Strategy 3: App's own MCP announcement
        q3 = await self.search.search(
            f'{app_name} "model context protocol" OR "MCP server" announcement'
        )
        all_results.extend(self._format_results(q3))

        if not all_results:
            await self._log("no_mcp_results", f"No MCP search results for {app_name}", app_id)
            return {
                **state,
                "mcp_support": "None",
                "mcp_repo_url": None,
                "mcp_last_commit": None,
                "mcp_confidence": 0.8,  # fairly confident in "None" if no results
            }

        combined_results = "\n\n".join(all_results[:10])
        result: MCPDetectionOutput = await self.llm.ainvoke(
            DETECTION_PROMPT.format(app_name=app_name, search_results=combined_results)
        )

        if result.mcp_support not in VALID_MCP_STATUS:
            result.mcp_support = "None"

        await self._log(
            "mcp_detected",
            f"{app_name} MCP status: {result.mcp_support} (confidence={result.confidence:.2f})",
            app_id,
            metadata={"mcp_support": result.mcp_support, "repo": result.mcp_repo_url},
        )

        return {
            **state,
            "mcp_support": result.mcp_support,
            "mcp_repo_url": result.mcp_repo_url,
            "mcp_last_commit": result.last_commit_date,
            "mcp_confidence": result.confidence,
        }

    def _format_results(self, results: list[dict]) -> list[str]:
        """Format search results as readable text for LLM analysis."""
        formatted = []
        for r in results[:5]:
            formatted.append(
                f"Title: {r.get('title', 'N/A')}\nURL: {r.get('url', '')}\n{r.get('snippet', '')}"
            )
        return formatted
