"""
core/buildability.py
--------------------
Deterministic rule engine for computing Buildability_Verdict.
No LLM calls. Pure logic based on structured app record fields.
"""

from __future__ import annotations

from enum import StrEnum


class BuildabilityVerdict(StrEnum):
    FULLY_BUILDABLE = "Fully Buildable"
    BUILDABLE_WITH_WORKAROUNDS = "Buildable with Workarounds"
    BLOCKED = "Blocked"


class BiggestBlocker(StrEnum):
    NO_PUBLIC_API = "No Public API"
    AUTH_COMPLEXITY = "Auth Complexity"
    GATED_ACCESS = "Gated Access"
    RATE_LIMITS = "Rate Limits"
    MISSING_DOCUMENTATION = "Missing Documentation"
    SDK_ONLY = "SDK-Only"
    LEGAL_RESTRICTIONS = "Legal Restrictions"
    NONE = "None"


def compute_verdict(
    api_types: list[str],
    access_model: str | None,
    auth_confidence: float,
    documentation_url: str | None,
    has_sandbox: bool = False,
) -> tuple[BuildabilityVerdict, BiggestBlocker]:
    """
    Compute the buildability verdict and biggest blocker.

    Returns (verdict, blocker). blocker is BiggestBlocker.NONE for Fully Buildable.

    Rules (applied in priority order):
    1. No public API → Blocked / No Public API
    2. SDK-only → Blocked / SDK-Only (no REST/GraphQL)
    3. Gated with no sandbox → Blocked / Gated Access
    4. Missing documentation → Blocked / Missing Documentation
    5. REST or GraphQL + Self-Serve/Freemium + auth confidence > 0.8 → Fully Buildable
    6. Otherwise → Buildable with Workarounds + determine_biggest_blocker
    """
    normalized_api = [t.strip().lower() for t in (api_types or [])]

    # --- Blocked cases ---
    if not normalized_api or normalized_api == ["none"] or normalized_api == [""]:
        return BuildabilityVerdict.BLOCKED, BiggestBlocker.NO_PUBLIC_API

    if normalized_api == ["sdk-only"] or (
        "sdk-only" in normalized_api
        and "rest" not in normalized_api
        and "graphql" not in normalized_api
    ):
        return BuildabilityVerdict.BLOCKED, BiggestBlocker.SDK_ONLY

    if access_model == "Gated" and not has_sandbox:
        return BuildabilityVerdict.BLOCKED, BiggestBlocker.GATED_ACCESS

    if not documentation_url:
        return BuildabilityVerdict.BLOCKED, BiggestBlocker.MISSING_DOCUMENTATION

    # --- Fully Buildable ---
    has_standard_api = "rest" in normalized_api or "graphql" in normalized_api
    is_open_access = access_model in ("Self-Serve", "Freemium")
    has_good_auth = auth_confidence >= 0.8

    if has_standard_api and is_open_access and has_good_auth:
        return BuildabilityVerdict.FULLY_BUILDABLE, BiggestBlocker.NONE

    # --- Buildable with Workarounds — determine biggest blocker ---
    blocker = _determine_workaround_blocker(
        api_types=normalized_api,
        access_model=access_model,
        auth_confidence=auth_confidence,
        documentation_url=documentation_url,
    )
    return BuildabilityVerdict.BUILDABLE_WITH_WORKAROUNDS, blocker


def _determine_workaround_blocker(
    api_types: list[str],
    access_model: str | None,
    auth_confidence: float,
    documentation_url: str | None,
) -> BiggestBlocker:
    """Pick the single most impactful blocker for a 'Buildable with Workarounds' verdict."""
    if access_model == "Gated":
        return BiggestBlocker.GATED_ACCESS
    if auth_confidence < 0.6:
        return BiggestBlocker.AUTH_COMPLEXITY
    if not documentation_url:
        return BiggestBlocker.MISSING_DOCUMENTATION
    if "grpc" in api_types and "rest" not in api_types:
        return BiggestBlocker.AUTH_COMPLEXITY  # gRPC requires extra infra
    return BiggestBlocker.MISSING_DOCUMENTATION
