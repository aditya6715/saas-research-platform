"""
core/ingestor.py
----------------
CSV ingestion and validation.
Parses apps.csv and enqueues apps for research.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

from core.queue import TaskQueue

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    enqueued: int = 0
    skipped_duplicate: int = 0
    skipped_malformed: int = 0
    warnings: list[str] = field(default_factory=list)

    def report(self) -> str:
        return (
            f"Ingestion complete: {self.enqueued} enqueued, "
            f"{self.skipped_duplicate} skipped (duplicate), "
            f"{self.skipped_malformed} skipped (malformed)"
        )


class CSVIngestor:
    """Validates and enqueues apps from a CSV file."""

    REQUIRED_FIELDS = {"app_name"}
    OPTIONAL_FIELDS = {"seed_url", "category"}

    def __init__(self, queue: TaskQueue) -> None:
        self.queue = queue

    async def ingest(self, filepath: str | Path) -> IngestResult:
        """
        Parse and validate a CSV file, enqueuing valid apps.
        CSV must have at minimum an 'app_name' column.
        Optional columns: 'seed_url', 'category'.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"Input CSV not found: {filepath}")

        result = IngestResult()

        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            if reader.fieldnames is None:
                raise ValueError("CSV file is empty or has no header row")

            # Normalize header names
            normalized_headers = {h.strip().lower(): h for h in reader.fieldnames}
            if "app_name" not in normalized_headers:
                raise ValueError(
                    f"CSV must contain 'app_name' column. Found: {list(reader.fieldnames)}"
                )

            for row_num, raw_row in enumerate(reader, start=2):
                # Normalize keys
                row: dict[str, str] = {k.strip().lower(): v.strip() for k, v in raw_row.items()}

                app_name = row.get("app_name", "").strip()
                if not app_name:
                    msg = f"Row {row_num}: empty 'app_name' — skipping"
                    logger.warning(msg)
                    result.warnings.append(msg)
                    result.skipped_malformed += 1
                    continue

                seed_url = row.get("seed_url") or None

                app_id = await self.queue.enqueue(app_name=app_name, seed_url=seed_url)
                if app_id is None:
                    result.skipped_duplicate += 1
                    logger.debug("Skipping duplicate: %s", app_name)
                else:
                    result.enqueued += 1
                    logger.debug("Enqueued: %s (id=%s)", app_name, app_id)

        logger.info(result.report())
        return result
