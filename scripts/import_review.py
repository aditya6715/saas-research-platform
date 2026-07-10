#!/usr/bin/env python3
"""
scripts/import_review.py
------------------------
Apply human corrections from human_review.json to the database
and regenerate the HTML report.

Run: python scripts/import_review.py [path/to/human_review.json]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main(review_file: str) -> None:
    from dotenv import load_dotenv

    load_dotenv()

    from core.config import get_settings
    from core.exporter import DataExporter
    from core.pattern_engine import PatternDiscoveryEngine
    from core.reporter import ReportGenerator
    from core.session import SessionManager
    from database.connection import DatabaseManager

    settings = get_settings()
    async with DatabaseManager(settings.database_path) as conn:
        mgr = SessionManager(conn)
        session = await mgr.load_latest()
        if not session:
            print("No session found.")
            sys.exit(1)

        exporter = DataExporter(conn, session.id)
        count = await exporter.import_human_review(review_file)
        print(f"✓ Imported {count} corrections")

        # Re-run pattern engine and regenerate report
        engine = PatternDiscoveryEngine(conn, session.id)
        stats = await engine.run()
        reporter = ReportGenerator(conn, session.id)
        path = await reporter.generate(stats)
        print(f"✓ Report regenerated: {path}")


if __name__ == "__main__":
    file = sys.argv[1] if len(sys.argv) > 1 else "data/exports/human_review.json"
    asyncio.run(main(file))
