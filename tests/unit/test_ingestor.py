"""Tests for core/ingestor.py"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.ingestor import CSVIngestor


@pytest.fixture
def mock_queue():
    q = MagicMock()
    q.enqueue = AsyncMock(return_value=1)
    return q


class TestCSVIngestor:
    async def test_valid_csv_enqueues_all_rows(self, tmp_path, mock_queue):
        csv = tmp_path / "apps.csv"
        csv.write_text("app_name,seed_url\nStripe,https://stripe.com\nTwilio,https://twilio.com\n")
        result = await CSVIngestor(mock_queue).ingest(csv)
        assert result.enqueued == 2
        assert result.skipped_malformed == 0

    async def test_missing_file_raises(self, tmp_path, mock_queue):
        with pytest.raises(FileNotFoundError):
            await CSVIngestor(mock_queue).ingest(tmp_path / "missing.csv")

    async def test_empty_app_name_skipped(self, tmp_path, mock_queue):
        csv = tmp_path / "apps.csv"
        csv.write_text("app_name,seed_url\n,https://nobody.com\nValidApp,\n")
        result = await CSVIngestor(mock_queue).ingest(csv)
        assert result.skipped_malformed == 1
        assert result.enqueued == 1

    async def test_missing_app_name_column_raises(self, tmp_path, mock_queue):
        csv = tmp_path / "apps.csv"
        csv.write_text("name,url\nStripe,https://stripe.com\n")
        with pytest.raises(ValueError, match="app_name"):
            await CSVIngestor(mock_queue).ingest(csv)

    async def test_duplicate_returns_none_and_skips(self, tmp_path, mock_queue):
        mock_queue.enqueue = AsyncMock(side_effect=[1, None])
        csv = tmp_path / "apps.csv"
        csv.write_text("app_name\nStripe\nStripe\n")
        result = await CSVIngestor(mock_queue).ingest(csv)
        assert result.enqueued == 1
        assert result.skipped_duplicate == 1

    async def test_optional_seed_url_passed_through(self, tmp_path, mock_queue):
        csv = tmp_path / "apps.csv"
        csv.write_text("app_name,seed_url\nGitHub,https://github.com\n")
        await CSVIngestor(mock_queue).ingest(csv)
        mock_queue.enqueue.assert_called_once_with(app_name="GitHub", seed_url="https://github.com")

    async def test_whitespace_trimmed_from_names(self, tmp_path, mock_queue):
        csv = tmp_path / "apps.csv"
        csv.write_text("app_name\n  Stripe  \n")
        await CSVIngestor(mock_queue).ingest(csv)
        mock_queue.enqueue.assert_called_once_with(app_name="Stripe", seed_url=None)

    async def test_ingest_result_report_string(self, tmp_path, mock_queue):
        csv = tmp_path / "apps.csv"
        csv.write_text("app_name\nApp1\nApp2\n")
        result = await CSVIngestor(mock_queue).ingest(csv)
        report = result.report()
        assert "2 enqueued" in report
