"""
agents/api_analyzer.py
----------------------
API surface analysis agent.
Classifies REST/GraphQL/gRPC/WebSocket/Webhook and extracts technical metadata.
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from agents.base import BaseAgent
from database.repository import AgentLogRepository

VALID_API_TYPES = ["REST", "GraphQL", "gRPC", "WebSocket", "Webhook", "SDK-only", "None"]


class APIAnalysisOutput(BaseModel):
    api_types: list[str] = Field(description="All API surface types detected")
    base_url: str | None = Field(None, description="Base API URL e.g. https://api.example.com/v1")
    versioning_scheme: str | None = Field(
        None, description="e.g. 'URL path (/v1)', 'Header', 'Query param'"
    )
    rate_limits: str | None = Field(None, description="Rate limit description from docs")
    openapi_url: str | None = Field(None, description="OpenAPI/Swagger spec URL if found")
    graphql_schema_url: str | None = Field(None, description="GraphQL schema or introspection URL")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_snippet: str = Field(default="", description="Key quote proving the API type")
    source_url: str = Field(default="")
    notes: str = Field(default="")


EXTRACTION_PROMPT = """You are an API architecture specialist analyzing developer documentation.

Classify this API's surface type(s) and extract technical metadata.

Valid API types: REST, GraphQL, gRPC, WebSocket, Webhook, SDK-only, None

Rules:
- REST: Has HTTP endpoints with JSON/XML responses, standard HTTP verbs
- GraphQL: Has a /graphql endpoint or mentions GraphQL queries/mutations
- gRPC: Uses Protocol Buffers, has .proto files
- WebSocket: Has persistent connections for real-time data
- Webhook: Can send POST callbacks to caller-provided URLs
- SDK-only: No direct HTTP API, only through official SDK libraries
- None: No public API of any kind

Extract:
1. All API types (there can be multiple, e.g., REST + Webhook)
2. Base API URL (the root URL for API calls)
3. API versioning scheme (URL path /v1, Header, Query param, or none)
4. Rate limits (exact numbers if documented)
5. OpenAPI/Swagger spec URL (look for links to spec files, /openapi.json, /swagger.json)
6. GraphQL schema URL (if GraphQL detected)

Assign confidence: 0.9+ if explicitly stated, 0.7 if inferred from examples, 0.5 if uncertain.

Documentation content:
---
{content}
---
""".strip()


class APIAnalyzerAgent(BaseAgent):
    name = "api_analyzer"

    def __init__(
        self,
        llm: ChatOpenAI,
        log_repo: AgentLogRepository,
        session_id: str,
        max_retries: int = 3,
    ) -> None:
        super().__init__(log_repo, session_id, max_retries)
        self.llm = llm.with_structured_output(APIAnalysisOutput)

    async def _execute(self, state: dict[str, Any]) -> dict[str, Any]:
        chunks: list[dict] = state.get("chunks", [])
        app_id: int | None = state.get("app_id")
        app_name: str = state.get("app_name", "unknown")

        if not chunks:
            await self._log("no_content", "No chunks for API analysis", app_id, level="WARNING")
            return {
                **state,
                "api_types": ["None"],
                "base_api_url": None,
                "api_versioning": None,
                "rate_limits": None,
                "openapi_url": None,
                "graphql_schema_url": None,
                "api_confidence": 0.0,
            }

        # Prioritize API reference chunks
        api_chunks = [
            c
            for c in chunks
            if any(
                kw in c.get("content", "").lower()
                for kw in [
                    "api",
                    "endpoint",
                    "rest",
                    "graphql",
                    "grpc",
                    "http",
                    "request",
                    "response",
                ]
            )
        ]
        target_chunks = (api_chunks or chunks)[:6]
        combined = "\n\n---\n\n".join(
            f"[Source: {c['source_url']}]\n{c['content']}" for c in target_chunks
        )

        result: APIAnalysisOutput = await self.llm.ainvoke(
            EXTRACTION_PROMPT.format(content=combined[:40_000])
        )

        # Validate api_types against allowed list
        valid_types = [t for t in result.api_types if t in VALID_API_TYPES]
        if not valid_types:
            valid_types = ["None"]

        await self._log(
            "api_analyzed",
            f"API types for {app_name}: {valid_types} (confidence={result.confidence:.2f})",
            app_id,
            metadata={"api_types": valid_types, "base_url": result.base_url},
        )

        return {
            **state,
            "api_types": valid_types,
            "base_api_url": result.base_url,
            "api_versioning": result.versioning_scheme,
            "rate_limits": result.rate_limits,
            "openapi_url": result.openapi_url,
            "graphql_schema_url": result.graphql_schema_url,
            "api_confidence": result.confidence,
            "api_evidence_snippet": result.evidence_snippet,
            "api_source_url": result.source_url,
        }
