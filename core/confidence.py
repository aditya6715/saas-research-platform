"""
core/confidence.py
------------------
Pure functions for computing field-level and app-level confidence scores.
No LLM calls, no I/O. Deterministic given inputs.
"""

from __future__ import annotations

FIELD_WEIGHTS: dict[str, float] = {
    "auth_methods": 0.25,
    "api_types": 0.20,
    "access_model": 0.20,
    "buildability_verdict": 0.15,
    "mcp_support": 0.10,
    "description": 0.05,
    "documentation_url": 0.05,
}

_WEIGHT_SUM = sum(FIELD_WEIGHTS.values())


def compute_field_confidence(
    evidence_confidence: float,
    source_agreement: bool,
    tiebreaker_used: bool = False,
    browser_verified: bool = False,
    human_reviewed: bool = False,
) -> float:
    """
    Compute a single field's confidence score.

    Args:
        evidence_confidence: LLM-reported certainty for the extracted value [0,1].
        source_agreement: True if Pass A and Pass B produced the same value.
        tiebreaker_used: True if a tiebreaker agent was invoked (implies disagreement).
        browser_verified: True if Browser Use confirmed the value in the live portal.
        human_reviewed: True if a human manually verified or corrected the value.

    Returns:
        Confidence score in [0.0, 1.0].
    """
    if human_reviewed:
        return 1.0

    base = float(evidence_confidence)
    base = max(0.0, min(base, 1.0))  # clamp input

    # Source agreement modifier
    if source_agreement and not tiebreaker_used:
        base = min(base * 1.10, 1.0)
    elif tiebreaker_used:
        base = base * 0.90  # slight penalty for needing 3rd opinion

    # Browser verification bonus
    if browser_verified:
        base = min(base * 1.05, 1.0)

    return round(base, 4)


def compute_app_confidence(field_scores: dict[str, float]) -> float:
    """
    Compute the app-level weighted confidence score from per-field scores.

    Args:
        field_scores: Mapping of field_name → confidence score.

    Returns:
        Weighted average confidence in [0.0, 1.0].
    """
    total = sum(field_scores.get(field, 0.0) * weight for field, weight in FIELD_WEIGHTS.items())
    return round(total / _WEIGHT_SUM, 4)


def needs_human_review(app_confidence: float, threshold: float = 0.85) -> bool:
    """Return True if the app confidence is below the human review threshold."""
    return app_confidence < threshold


def accuracy_progression_report(
    initial_scores: list[float],
    post_verification_scores: list[float],
    post_browser_scores: list[float],
    post_human_scores: list[float],
) -> dict[str, float]:
    """
    Compute average accuracy at each verification stage.
    Used for the verification pipeline analytics section of the report.
    """

    def avg(lst: list[float]) -> float:
        return round(sum(lst) / len(lst), 4) if lst else 0.0

    return {
        "initial": avg(initial_scores),
        "post_cross_source": avg(post_verification_scores),
        "post_browser": avg(post_browser_scores),
        "post_human_review": avg(post_human_scores),
    }
