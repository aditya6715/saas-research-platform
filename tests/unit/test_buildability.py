"""Tests for core/buildability.py"""

from core.buildability import BiggestBlocker, BuildabilityVerdict, compute_verdict


class TestComputeVerdict:
    def test_no_api_types_is_blocked(self):
        v, b = compute_verdict([], "Self-Serve", 0.9, "https://docs.com")
        assert v == BuildabilityVerdict.BLOCKED
        assert b == BiggestBlocker.NO_PUBLIC_API

    def test_none_api_is_blocked(self):
        v, b = compute_verdict(["None"], "Self-Serve", 0.9, "https://docs.com")
        assert v == BuildabilityVerdict.BLOCKED

    def test_sdk_only_is_blocked(self):
        v, b = compute_verdict(["SDK-only"], "Self-Serve", 0.9, "https://docs.com")
        assert v == BuildabilityVerdict.BLOCKED
        assert b == BiggestBlocker.SDK_ONLY

    def test_gated_no_sandbox_is_blocked(self):
        v, b = compute_verdict(["REST"], "Gated", 0.9, "https://docs.com", has_sandbox=False)
        assert v == BuildabilityVerdict.BLOCKED
        assert b == BiggestBlocker.GATED_ACCESS

    def test_gated_with_sandbox_is_workaround(self):
        v, _ = compute_verdict(["REST"], "Gated", 0.9, "https://docs.com", has_sandbox=True)
        assert v in (
            BuildabilityVerdict.FULLY_BUILDABLE,
            BuildabilityVerdict.BUILDABLE_WITH_WORKAROUNDS,
        )

    def test_fully_buildable_rest_self_serve(self):
        v, b = compute_verdict(["REST"], "Self-Serve", 0.9, "https://docs.com")
        assert v == BuildabilityVerdict.FULLY_BUILDABLE
        assert b == BiggestBlocker.NONE

    def test_fully_buildable_graphql(self):
        v, b = compute_verdict(["GraphQL"], "Freemium", 0.85, "https://docs.com")
        assert v == BuildabilityVerdict.FULLY_BUILDABLE

    def test_low_auth_confidence_workaround(self):
        v, b = compute_verdict(["REST"], "Self-Serve", 0.5, "https://docs.com")
        assert v == BuildabilityVerdict.BUILDABLE_WITH_WORKAROUNDS

    def test_missing_docs_blocked(self):
        v, b = compute_verdict(["REST"], "Self-Serve", 0.9, None)
        assert v == BuildabilityVerdict.BLOCKED
        assert b == BiggestBlocker.MISSING_DOCUMENTATION

    def test_rest_and_webhook_fully_buildable(self):
        v, _ = compute_verdict(["REST", "Webhook"], "Self-Serve", 0.92, "https://docs.com")
        assert v == BuildabilityVerdict.FULLY_BUILDABLE
