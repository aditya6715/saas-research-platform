"""Tests for core/confidence.py"""

from core.confidence import (
    FIELD_WEIGHTS,
    accuracy_progression_report,
    compute_app_confidence,
    compute_field_confidence,
    needs_human_review,
)


class TestComputeFieldConfidence:
    def test_human_reviewed_always_returns_1(self):
        score = compute_field_confidence(0.3, False, human_reviewed=True)
        assert score == 1.0

    def test_agreement_boosts_score(self):
        without = compute_field_confidence(0.8, source_agreement=False)
        with_agree = compute_field_confidence(0.8, source_agreement=True)
        assert with_agree > without

    def test_tiebreaker_penalizes(self):
        base = compute_field_confidence(0.8, source_agreement=False, tiebreaker_used=False)
        penalized = compute_field_confidence(0.8, source_agreement=False, tiebreaker_used=True)
        assert penalized < base

    def test_browser_verified_bonus(self):
        without = compute_field_confidence(0.85, source_agreement=True, browser_verified=False)
        with_browser = compute_field_confidence(0.85, source_agreement=True, browser_verified=True)
        assert with_browser > without

    def test_score_clamped_to_1(self):
        score = compute_field_confidence(0.99, source_agreement=True, browser_verified=True)
        assert score <= 1.0

    def test_score_not_negative(self):
        score = compute_field_confidence(0.0, source_agreement=False, tiebreaker_used=True)
        assert score >= 0.0

    def test_input_clamped(self):
        score = compute_field_confidence(1.5, source_agreement=False)
        assert 0.0 <= score <= 1.0


class TestComputeAppConfidence:
    def test_perfect_scores_give_1(self):
        scores = dict.fromkeys(FIELD_WEIGHTS, 1.0)
        assert compute_app_confidence(scores) == 1.0

    def test_zero_scores_give_0(self):
        scores = dict.fromkeys(FIELD_WEIGHTS, 0.0)
        assert compute_app_confidence(scores) == 0.0

    def test_partial_scores_weighted(self):
        # Auth has highest weight (0.25); set only auth to 1.0
        scores = {"auth_methods": 1.0}
        result = compute_app_confidence(scores)
        # Should be 0.25 / 1.0 = 0.25
        assert abs(result - 0.25) < 0.01

    def test_missing_fields_treated_as_zero(self):
        scores = {}
        result = compute_app_confidence(scores)
        assert result == 0.0

    def test_result_in_range(self):
        scores = dict.fromkeys(FIELD_WEIGHTS, 0.7)
        result = compute_app_confidence(scores)
        assert 0.0 <= result <= 1.0


class TestNeedsHumanReview:
    def test_below_threshold_needs_review(self):
        assert needs_human_review(0.84, threshold=0.85) is True

    def test_at_threshold_does_not_need_review(self):
        assert needs_human_review(0.85, threshold=0.85) is False

    def test_above_threshold_does_not_need_review(self):
        assert needs_human_review(0.95, threshold=0.85) is False

    def test_zero_always_needs_review(self):
        assert needs_human_review(0.0) is True


class TestAccuracyProgressionReport:
    def test_returns_four_stages(self):
        result = accuracy_progression_report([0.7], [0.85], [0.9], [0.99])
        assert set(result.keys()) == {
            "initial",
            "post_cross_source",
            "post_browser",
            "post_human_review",
        }

    def test_empty_lists_return_zero(self):
        result = accuracy_progression_report([], [], [], [])
        assert all(v == 0.0 for v in result.values())

    def test_averages_correct(self):
        result = accuracy_progression_report([0.8, 0.9], [0.9, 1.0], [0.95, 0.95], [1.0, 1.0])
        assert abs(result["initial"] - 0.85) < 0.01
