#!/usr/bin/env python3
"""
scripts/export_data.py
----------------------
CLI wrapper to export the latest session's data to JSON.
Run: python scripts/export_data.py [--session <uuid>]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))


async def main(session_id: str | None = None) -> None:
    from dotenv import load_dotenv

    load_dotenv()

    from core.config import get_settings
    from core.exporter import DataExporter
    from core.session import SessionManager
    from database.connection import DatabaseManager

    settings = get_settings()
    async with DatabaseManager(settings.database_path) as conn:
        mgr = SessionManager(conn)
        session = await (mgr.load(session_id) if session_id else mgr.load_latest())
        if not session:
            print("No session found. Run the pipeline first.")
            sys.exit(1)

        exporter = DataExporter(conn, session.id)
        paths = await exporter.export_all()
        for kind, path in paths.items():
            print(f"  {kind}: {path}")


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(sid))
