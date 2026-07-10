"""
database/models.py
------------------
Pydantic dataclasses mirroring the SQLite schema.
Used for type-safe access throughout the application.
JSON array fields are stored as strings in SQLite and parsed here.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class AppRecord(BaseModel):
    id: int | None = None
    session_id: str
    app_name: str
    seed_url: str | None = None
    category: str | None = None
    description: str | None = None
    auth_methods: list[str] = Field(default_factory=list)
    primary_auth: str | None = None
    oauth_flows: list[str] = Field(default_factory=list)
    access_model: str | None = None
    pricing_tier_for_api: str | None = None
    api_types: list[str] = Field(default_factory=list)
    base_api_url: str | None = None
    api_versioning: str | None = None
    rate_limits: str | None = None
    openapi_url: str | None = None
    graphql_schema_url: str | None = None
    mcp_support: str | None = None
    mcp_repo_url: str | None = None
    mcp_last_commit: str | None = None
    buildability_verdict: str | None = None
    biggest_blocker: str | None = None
    documentation_url: str | None = None
    raw_markdown: str | None = None
    confidence_score: float = 0.0
    human_review_required: bool = False
    human_reviewed_by: str | None = None
    human_reviewed_at: str | None = None
    status: str = "pending"
    retry_count: int = 0
    last_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_db_row(self) -> dict[str, Any]:
        """Serialize to SQLite-compatible dict (JSON arrays as strings)."""
        return {
            "session_id": self.session_id,
            "app_name": self.app_name,
            "seed_url": self.seed_url,
            "category": self.category,
            "description": self.description,
            "auth_methods_json": json.dumps(self.auth_methods),
            "primary_auth": self.primary_auth,
            "oauth_flows_json": json.dumps(self.oauth_flows),
            "access_model": self.access_model,
            "pricing_tier_for_api": self.pricing_tier_for_api,
            "api_types_json": json.dumps(self.api_types),
            "base_api_url": self.base_api_url,
            "api_versioning": self.api_versioning,
            "rate_limits": self.rate_limits,
            "openapi_url": self.openapi_url,
            "graphql_schema_url": self.graphql_schema_url,
            "mcp_support": self.mcp_support,
            "mcp_repo_url": self.mcp_repo_url,
            "mcp_last_commit": self.mcp_last_commit,
            "buildability_verdict": self.buildability_verdict,
            "biggest_blocker": self.biggest_blocker,
            "documentation_url": self.documentation_url,
            "raw_markdown": self.raw_markdown,
            "confidence_score": self.confidence_score,
            "human_review_required": int(self.human_review_required),
            "human_reviewed_by": self.human_reviewed_by,
            "human_reviewed_at": self.human_reviewed_at,
            "status": self.status,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> AppRecord:
        """Deserialize from SQLite row (parse JSON array strings)."""
        d = dict(row)
        d["auth_methods"] = json.loads(d.pop("auth_methods_json", "[]") or "[]")
        d["oauth_flows"] = json.loads(d.pop("oauth_flows_json", "[]") or "[]")
        d["api_types"] = json.loads(d.pop("api_types_json", "[]") or "[]")
        d["human_review_required"] = bool(d.get("human_review_required", 0))
        return cls(**{k: v for k, v in d.items() if k in cls.model_fields})


class EvidenceRecord(BaseModel):
    id: int | None = None
    app_id: int
    field_name: str
    field_value: str | None = None
    source_url: str
    extracted_text: str | None = None
    extraction_method: str | None = None
    confidence: float = 0.0
    verified: bool = False
    created_at: str | None = None

    def to_db_row(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id,
            "field_name": self.field_name,
            "field_value": self.field_value,
            "source_url": self.source_url,
            "extracted_text": self.extracted_text[:500] if self.extracted_text else None,
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "verified": int(self.verified),
        }


class VerificationRecord(BaseModel):
    id: int | None = None
    app_id: int
    field_name: str
    pass_a_value: str | None = None
    pass_b_value: str | None = None
    final_value: str | None = None
    agreement: bool = False
    tiebreaker_used: bool = False
    tiebreaker_reasoning: str | None = None
    browser_verified: bool = False
    browser_screenshot_path: str | None = None
    confidence_before: float | None = None
    confidence_after: float | None = None
    verified_at: str | None = None

    def to_db_row(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id,
            "field_name": self.field_name,
            "pass_a_value": self.pass_a_value,
            "pass_b_value": self.pass_b_value,
            "final_value": self.final_value,
            "agreement": int(self.agreement),
            "tiebreaker_used": int(self.tiebreaker_used),
            "tiebreaker_reasoning": self.tiebreaker_reasoning,
            "browser_verified": int(self.browser_verified),
            "browser_screenshot_path": self.browser_screenshot_path,
            "confidence_before": self.confidence_before,
            "confidence_after": self.confidence_after,
        }


class ResearchSession(BaseModel):
    id: str
    started_at: str | None = None
    completed_at: str | None = None
    total_apps: int = 0
    completed_apps: int = 0
    failed_apps: int = 0
    avg_confidence: float | None = None
    human_review_count: int = 0
    total_api_calls: int = 0
    cache_hit_ratio: float | None = None
    estimated_cost_usd: float | None = None
    config_snapshot: dict[str, Any] = Field(default_factory=dict)

    def to_db_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "total_apps": self.total_apps,
            "completed_apps": self.completed_apps,
            "failed_apps": self.failed_apps,
            "avg_confidence": self.avg_confidence,
            "human_review_count": self.human_review_count,
            "total_api_calls": self.total_api_calls,
            "cache_hit_ratio": self.cache_hit_ratio,
            "estimated_cost_usd": self.estimated_cost_usd,
            "config_snapshot": json.dumps(self.config_snapshot),
        }
