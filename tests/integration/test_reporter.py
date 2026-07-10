"""
Integration tests for HTML report generation.
Verifies that the report renders correctly with test data.
"""

from __future__ import annotations

from pathlib import Path

from database.models import AppRecord


class TestReportGenerator:
    async def test_report_generates_html_file(self, db_conn, sample_session, tmp_path, app_repo):
        from core.reporter import ReportGenerator

        # Insert some test apps
        apps_data = [
            AppRecord(
                session_id=sample_session.id,
                app_name="Stripe",
                category="Payments",
                description="Payment processing API",
                auth_methods=["API Key", "OAuth 2.0"],
                primary_auth="API Key",
                api_types=["REST", "Webhook"],
                access_model="Self-Serve",
                mcp_support="Community",
                buildability_verdict="Fully Buildable",
                documentation_url="https://stripe.com/docs/api",
                confidence_score=0.96,
                status="completed",
            ),
            AppRecord(
                session_id=sample_session.id,
                app_name="Salesforce",
                category="CRM",
                description="CRM platform",
                auth_methods=["OAuth 2.0"],
                primary_auth="OAuth 2.0",
                api_types=["REST", "GraphQL"],
                access_model="Gated",
                mcp_support="None",
                buildability_verdict="Blocked",
                biggest_blocker="Gated Access",
                documentation_url="https://developer.salesforce.com",
                confidence_score=0.78,
                human_review_required=True,
                status="completed",
            ),
        ]
        for app in apps_data:
            await app_repo.create(app)

        statistics = {
            "session_id": sample_session.id,
            "total_apps": 2,
            "avg_confidence": 0.87,
            "human_review_count": 1,
            "verified_count": 2,
            "auth_distribution": {"API Key": 1, "OAuth 2.0": 2},
            "api_surface_distribution": {"REST": 2, "GraphQL": 1, "Webhook": 1},
            "access_model_distribution": {"Self-Serve": 1, "Gated": 1},
            "buildability_distribution": {"Fully Buildable": 1, "Blocked": 1},
            "mcp_support_distribution": {"Community": 1, "None": 1},
            "mcp_gap_percentage": 50.0,
            "top_blockers": [{"blocker": "Gated Access", "count": 1}],
            "easy_wins": ["Stripe"],
            "hard_integrations": ["Salesforce"],
            "category_distribution": {"Payments": 1, "CRM": 1},
            "category_breakdown": {},
            "multi_auth_count": 1,
            "insights": {
                "headline": "Test headline insight",
                "key_findings": ["Finding 1", "Finding 2"],
                "recommendations": ["Recommendation 1"],
                "easy_wins_preview": ["Stripe"],
            },
        }

        reporter = ReportGenerator(
            conn=db_conn,
            session_id=sample_session.id,
            templates_dir=Path("templates"),
            reports_dir=tmp_path / "reports",
        )
        output_path = await reporter.generate(statistics)

        # Verify file was created
        assert Path(output_path).exists()
        html = Path(output_path).read_text()

        # Verify key content is present
        assert "Stripe" in html
        assert "Salesforce" in html
        assert "SaaS Integration Research" in html
        assert "chart" in html.lower() or "Chart" in html
        assert "APP_DATA" in html

    async def test_report_contains_dark_mode_toggle(
        self, db_conn, sample_session, tmp_path, app_repo
    ):
        from core.reporter import ReportGenerator

        reporter = ReportGenerator(
            conn=db_conn,
            session_id=sample_session.id,
            templates_dir=Path("templates"),
            reports_dir=tmp_path / "reports",
        )
        statistics = {
            "session_id": sample_session.id,
            "total_apps": 0,
            "avg_confidence": 0.0,
            "human_review_count": 0,
            "verified_count": 0,
            "auth_distribution": {},
            "api_surface_distribution": {},
            "access_model_distribution": {},
            "buildability_distribution": {},
            "mcp_support_distribution": {},
            "mcp_gap_percentage": 0.0,
            "top_blockers": [],
            "easy_wins": [],
            "hard_integrations": [],
            "category_distribution": {},
            "category_breakdown": {},
            "multi_auth_count": 0,
            "insights": {
                "headline": "",
                "key_findings": [],
                "recommendations": [],
                "easy_wins_preview": [],
            },
        }
        output = await reporter.generate(statistics)
        html = Path(output).read_text()
        assert "toggleTheme" in html
        assert "localStorage" in html
        assert "dark" in html
