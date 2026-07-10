"""
Integration tests for the research pipeline.
All external calls (LLM, search, firecrawl, browser) are mocked.
Tests the full LangGraph workflow end-to-end with in-memory SQLite.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.api_analyzer import APIAnalysisOutput
from agents.auth_extractor import AuthExtractionOutput, AuthMethodResult
from agents.dev_portal import DevPortalOutput
from agents.mcp_detector import MCPDetectionOutput
from agents.verifier import VerificationPassOutput
from agents.tiebreaker import TiebreakerOutput
from core.buildability import BiggestBlocker, BuildabilityVerdict


def make_auth_result() -> AuthExtractionOutput:
    return AuthExtractionOutput(
        auth_methods=[
            AuthMethodResult(
                method="API Key",
                confidence=0.97,
                evidence_snippet="Use your API key in the Authorization header",
                source_url="https://stripe.com/docs/api/authentication",
            )
        ],
        primary_method="API Key",
    )


def make_api_result() -> APIAnalysisOutput:
    return APIAnalysisOutput(
        api_types=["REST", "Webhook"],
        base_url="https://api.stripe.com/v1",
        versioning_scheme="URL path (/v1)",
        rate_limits="100 req/sec",
        confidence=0.95,
        evidence_snippet="Stripe's API is organized around REST",
        source_url="https://stripe.com/docs/api",
    )


def make_portal_result() -> DevPortalOutput:
    return DevPortalOutput(
        access_model="Self-Serve",
        pricing_tier_for_api="Free tier available",
        signup_url="https://dashboard.stripe.com/register",
        evidence_text="Create an account to get your API keys instantly",
        confidence=0.93,
    )


def make_mcp_result() -> MCPDetectionOutput:
    return MCPDetectionOutput(
        mcp_support="Community",
        mcp_repo_url="https://github.com/user/stripe-mcp",
        confidence=0.85,
    )


def make_verifier_result() -> VerificationPassOutput:
    return VerificationPassOutput(
        auth_methods=["API Key"],
        primary_auth="API Key",
        api_types=["REST", "Webhook"],
        access_model="Self-Serve",
        mcp_support="Community",
        confidence=0.91,
    )


class TestFullPipeline:
    """End-to-end pipeline test with all external calls mocked."""

    async def test_pipeline_produces_completed_app(
        self, db_conn, sample_session, log_repo, ev_repo, verif_repo, app_repo
    ):
        from core.pipeline import ResearchPipeline
        from agents.doc_finder import DocFinderAgent
        from agents.doc_parser import DocParserAgent
        from agents.auth_extractor import AuthExtractorAgent
        from agents.api_analyzer import APIAnalyzerAgent
        from agents.dev_portal import DevPortalAgent
        from agents.mcp_detector import MCPDetectorAgent
        from agents.evidence_collector import EvidenceCollectorAgent
        from agents.verifier import VerifierAgent
        from agents.tiebreaker import TiebreakerAgent

        sid = sample_session.id

        # ── Mock all agents ───────────────────────────────────────────────
        doc_finder = MagicMock(spec=DocFinderAgent)
        doc_finder.run = AsyncMock(return_value={
            "app_id": 1, "app_name": "Stripe", "seed_url": None,
            "session_id": sid,
            "documentation_url": "https://stripe.com/docs/api",
            "doc_url_confidence": 0.97,
            "doc_candidates": [],
            "human_review_required": False,
        })

        doc_parser = MagicMock(spec=DocParserAgent)
        doc_parser.run = AsyncMock(side_effect=lambda s: {
            **s,
            "chunks": [{"content": "API Key auth. REST API.", "source_url": "https://stripe.com/docs", "chunk_index": 0, "token_count": 10}],
            "pages_parsed": 1,
            "parse_method": "firecrawl",
        })

        auth_ex = MagicMock(spec=AuthExtractorAgent)
        auth_ex.run = AsyncMock(side_effect=lambda s: {
            **s,
            "auth_result": [{"method": "API Key", "confidence": 0.97, "evidence_snippet": "API key required", "source_url": "https://stripe.com/docs", "oauth_flows": []}],
            "auth_methods": ["API Key"],
            "primary_auth": "API Key",
            "oauth_flows": [],
            "auth_confidence": 0.97,
        })

        api_an = MagicMock(spec=APIAnalyzerAgent)
        api_an.run = AsyncMock(side_effect=lambda s: {
            **s,
            "api_types": ["REST", "Webhook"],
            "base_api_url": "https://api.stripe.com/v1",
            "api_versioning": "URL path",
            "rate_limits": "100/sec",
            "openapi_url": None,
            "graphql_schema_url": None,
            "api_confidence": 0.95,
            "api_evidence_snippet": "REST API",
            "api_source_url": "https://stripe.com/docs",
        })

        dev_p = MagicMock(spec=DevPortalAgent)
        dev_p.run = AsyncMock(side_effect=lambda s: {
            **s,
            "access_model": "Self-Serve",
            "pricing_tier_for_api": "Free",
            "portal_signup_url": "https://dashboard.stripe.com",
            "portal_screenshot": None,
            "access_model_confidence": 0.93,
            "has_sandbox": True,
            "portal_evidence_text": "Instant API key on signup",
        })

        mcp_d = MagicMock(spec=MCPDetectorAgent)
        mcp_d.run = AsyncMock(side_effect=lambda s: {
            **s,
            "mcp_support": "Community",
            "mcp_repo_url": "https://github.com/user/stripe-mcp",
            "mcp_last_commit": "2025-06-01",
            "mcp_confidence": 0.85,
        })

        ev_col = MagicMock(spec=EvidenceCollectorAgent)
        ev_col.run = AsyncMock(side_effect=lambda s: {**s, "evidence_count": 5})

        verifier = MagicMock(spec=VerifierAgent)
        verifier.run = AsyncMock(side_effect=lambda s: {
            **s,
            "verification_complete": True,
            "pass_b_result": {},
            "auth_methods_needs_tiebreaker": False,
            "api_types_needs_tiebreaker": False,
            "access_model_needs_tiebreaker": False,
            "mcp_support_needs_tiebreaker": False,
            "auth_methods_verified_confidence": 0.95,
            "api_types_verified_confidence": 0.93,
            "access_model_verified_confidence": 0.91,
            "mcp_support_verified_confidence": 0.87,
        })

        tiebreaker = MagicMock(spec=TiebreakerAgent)
        tiebreaker.run = AsyncMock(side_effect=lambda s: s)

        # ── Create and run pipeline ───────────────────────────────────────
        pipeline = ResearchPipeline(
            doc_finder=doc_finder,
            doc_parser=doc_parser,
            auth_extractor=auth_ex,
            api_analyzer=api_an,
            dev_portal=dev_p,
            mcp_detector=mcp_d,
            evidence_collector=ev_col,
            verifier=verifier,
            tiebreaker=tiebreaker,
            app_repo=app_repo,
            confidence_threshold=0.85,
        )

        # Create the app in DB first
        from database.models import AppRecord
        app = AppRecord(session_id=sid, app_name="Stripe", seed_url=None)
        app_id = await app_repo.create(app)

        graph = pipeline.build()
        result = await graph.ainvoke({
            "app_id": app_id,
            "app_name": "Stripe",
            "seed_url": None,
            "session_id": sid,
            "human_review_required": False,
        })

        # ── Assertions ───────────────────────────────────────────────────
        assert result.get("buildability_verdict") == "Fully Buildable"
        assert result.get("primary_auth") == "API Key"
        assert "REST" in result.get("api_types", [])
        assert result.get("access_model") == "Self-Serve"
        assert result.get("confidence_score", 0) > 0.85

        # Verify DB was updated
        updated = await app_repo.get_by_id(app_id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.buildability_verdict == "Fully Buildable"
