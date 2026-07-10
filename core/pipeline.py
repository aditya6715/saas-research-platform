"""
core/pipeline.py
----------------
LangGraph workflow definition.
Connects all agents into a stateful directed graph.
Each node is an async function; edges are conditional based on confidence/flags.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.api_analyzer import APIAnalyzerAgent
from agents.auth_extractor import AuthExtractorAgent
from agents.dev_portal import DevPortalAgent
from agents.doc_finder import DocFinderAgent
from agents.doc_parser import DocParserAgent
from agents.evidence_collector import EvidenceCollectorAgent
from agents.mcp_detector import MCPDetectorAgent
from agents.tiebreaker import TiebreakerAgent
from agents.verifier import VerifierAgent
from core.buildability import compute_verdict
from core.confidence import compute_app_confidence, needs_human_review
from database.repository import AppRepository

logger = logging.getLogger(__name__)


class ResearchState(TypedDict, total=False):
    # Input
    app_id: int
    app_name: str
    seed_url: str | None
    session_id: str

    # Doc finder
    documentation_url: str | None
    doc_url_confidence: float
    doc_candidates: list[dict]

    # Doc parser
    chunks: list[dict]
    pages_parsed: int
    parse_method: str
    raw_markdown: str | None

    # Auth extractor
    auth_result: list[dict] | None
    auth_methods: list[str]
    primary_auth: str | None
    oauth_flows: list[str]
    auth_confidence: float

    # API analyzer
    api_types: list[str]
    base_api_url: str | None
    api_versioning: str | None
    rate_limits: str | None
    openapi_url: str | None
    graphql_schema_url: str | None
    api_confidence: float
    api_evidence_snippet: str
    api_source_url: str

    # Dev portal
    access_model: str | None
    pricing_tier_for_api: str | None
    portal_signup_url: str | None
    portal_screenshot: str | None
    access_model_confidence: float
    has_sandbox: bool
    portal_evidence_text: str

    # MCP detector
    mcp_support: str | None
    mcp_repo_url: str | None
    mcp_last_commit: str | None
    mcp_confidence: float

    # Evidence
    evidence_count: int

    # Verification
    verification_complete: bool
    pass_b_result: dict | None

    # Flags
    human_review_required: bool

    # Final computed fields
    buildability_verdict: str | None
    biggest_blocker: str | None
    confidence_score: float

    # Pipeline metadata
    error: str | None


class ResearchPipeline:
    """
    LangGraph-based research pipeline.
    Call build() to get a compiled graph, then invoke() per app.
    """

    def __init__(
        self,
        doc_finder: DocFinderAgent,
        doc_parser: DocParserAgent,
        auth_extractor: AuthExtractorAgent,
        api_analyzer: APIAnalyzerAgent,
        dev_portal: DevPortalAgent,
        mcp_detector: MCPDetectorAgent,
        evidence_collector: EvidenceCollectorAgent,
        verifier: VerifierAgent,
        tiebreaker: TiebreakerAgent,
        app_repo: AppRepository,
        confidence_threshold: float = 0.85,
    ) -> None:
        self.doc_finder = doc_finder
        self.doc_parser = doc_parser
        self.auth_extractor = auth_extractor
        self.api_analyzer = api_analyzer
        self.dev_portal = dev_portal
        self.mcp_detector = mcp_detector
        self.evidence_collector = evidence_collector
        self.verifier = verifier
        self.tiebreaker = tiebreaker
        self.app_repo = app_repo
        self.confidence_threshold = confidence_threshold

    def build(self) -> Any:
        """Build and compile the LangGraph StateGraph."""
        graph = StateGraph(ResearchState)

        # ── Nodes ─────────────────────────────────────────────────────────
        graph.add_node("find_docs", self._node_find_docs)
        graph.add_node("parse_docs", self._node_parse_docs)
        graph.add_node("parallel_extraction", self._node_parallel_extraction)
        graph.add_node("collect_evidence", self._node_collect_evidence)
        graph.add_node("verify", self._node_verify)
        graph.add_node("tiebreak", self._node_tiebreak)
        graph.add_node("score_and_build", self._node_score_and_build)
        graph.add_node("persist", self._node_persist)

        # ── Edges ─────────────────────────────────────────────────────────
        graph.add_edge(START, "find_docs")
        graph.add_edge("find_docs", "parse_docs")
        graph.add_edge("parse_docs", "parallel_extraction")
        graph.add_edge("parallel_extraction", "collect_evidence")
        graph.add_edge("collect_evidence", "verify")
        graph.add_conditional_edges(
            "verify",
            self._route_after_verify,
            {"tiebreak": "tiebreak", "score": "score_and_build"},
        )
        graph.add_edge("tiebreak", "score_and_build")
        graph.add_edge("score_and_build", "persist")
        graph.add_edge("persist", END)

        return graph.compile()

    # ── Node implementations ───────────────────────────────────────────────

    async def _node_find_docs(self, state: ResearchState) -> ResearchState:
        return await self.doc_finder.run(state)

    async def _node_parse_docs(self, state: ResearchState) -> ResearchState:
        return await self.doc_parser.run(state)

    async def _node_parallel_extraction(self, state: ResearchState) -> ResearchState:
        """Run all 4 extraction agents concurrently."""
        results = await asyncio.gather(
            self.auth_extractor.run(state),
            self.api_analyzer.run(state),
            self.dev_portal.run(state),
            self.mcp_detector.run(state),
            return_exceptions=True,
        )

        merged = dict(state)
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Extraction agent failed: %s", result)
                continue
            merged.update(result)

        return merged  # type: ignore[return-value]

    async def _node_collect_evidence(self, state: ResearchState) -> ResearchState:
        return await self.evidence_collector.run(state)

    async def _node_verify(self, state: ResearchState) -> ResearchState:
        return await self.verifier.run(state)

    async def _node_tiebreak(self, state: ResearchState) -> ResearchState:
        return await self.tiebreaker.run(state)

    async def _node_score_and_build(self, state: ResearchState) -> ResearchState:
        """Compute final confidence scores and buildability verdict."""
        field_scores = {
            "auth_methods": state.get(
                "auth_methods_verified_confidence", state.get("auth_confidence", 0.0)
            ),
            "api_types": state.get(
                "api_types_verified_confidence", state.get("api_confidence", 0.0)
            ),
            "access_model": state.get(
                "access_model_verified_confidence", state.get("access_model_confidence", 0.0)
            ),
            "mcp_support": state.get(
                "mcp_support_verified_confidence", state.get("mcp_confidence", 0.0)
            ),
            "buildability_verdict": 0.9,  # deterministic rule — always high confidence
            "description": 0.8,
            "documentation_url": state.get("doc_url_confidence", 0.0),
        }

        app_confidence = compute_app_confidence(field_scores)
        human_review = needs_human_review(app_confidence, self.confidence_threshold)
        if state.get("human_review_required"):
            human_review = True

        # Compute buildability verdict
        verdict, blocker = compute_verdict(
            api_types=state.get("api_types", []),
            access_model=state.get("access_model"),
            auth_confidence=state.get("auth_confidence", 0.0),
            documentation_url=state.get("documentation_url"),
            has_sandbox=state.get("has_sandbox", False),
        )

        return {
            **state,
            "confidence_score": app_confidence,
            "human_review_required": human_review,
            "buildability_verdict": verdict.value,
            "biggest_blocker": blocker.value if blocker.value != "None" else None,
        }  # type: ignore[return-value]

    async def _node_persist(self, state: ResearchState) -> ResearchState:
        """Write final app record fields to SQLite."""
        app_id = state.get("app_id")
        if not app_id:
            return state

        updates = {
            "category": state.get("category"),
            "description": state.get("description"),
            "auth_methods_json": __import__("json").dumps(state.get("auth_methods", [])),
            "primary_auth": state.get("primary_auth"),
            "oauth_flows_json": __import__("json").dumps(state.get("oauth_flows", [])),
            "access_model": state.get("access_model"),
            "pricing_tier_for_api": state.get("pricing_tier_for_api"),
            "api_types_json": __import__("json").dumps(state.get("api_types", [])),
            "base_api_url": state.get("base_api_url"),
            "api_versioning": state.get("api_versioning"),
            "rate_limits": state.get("rate_limits"),
            "openapi_url": state.get("openapi_url"),
            "graphql_schema_url": state.get("graphql_schema_url"),
            "mcp_support": state.get("mcp_support"),
            "mcp_repo_url": state.get("mcp_repo_url"),
            "mcp_last_commit": state.get("mcp_last_commit"),
            "buildability_verdict": state.get("buildability_verdict"),
            "biggest_blocker": state.get("biggest_blocker"),
            "documentation_url": state.get("documentation_url"),
            "raw_markdown": (state.get("raw_markdown") or "")[:200_000],
            "confidence_score": state.get("confidence_score", 0.0),
            "human_review_required": int(state.get("human_review_required", False)),
            "status": "completed",
        }

        await self.app_repo.update_fields(app_id, updates)
        return state

    @staticmethod
    def _route_after_verify(state: ResearchState) -> str:
        """Route to tiebreaker if any fields need it, otherwise go straight to scoring."""
        needs_tiebreak = any(
            state.get(f"{field}_needs_tiebreaker")
            for field in ["auth_methods", "api_types", "access_model", "mcp_support"]
        )
        return "tiebreak" if needs_tiebreak else "score"
