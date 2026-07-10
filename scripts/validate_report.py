#!/usr/bin/env python3
"""
scripts/validate_report.py
--------------------------
Smoke-tests the most recently generated HTML report.
Checks that all required elements are present.
Run: python scripts/validate_report.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_STRINGS = [
    # Structure
    "SaaS Integration Research",
    "APP_DATA",
    "CHART_DATA",
    "STATS",
    # Charts
    "chartAuth",
    "chartAPI",
    "chartBuild",
    # Table
    "appTableBody",
    "searchInput",
    "filterVerdict",
    # Features
    "toggleTheme",
    "localStorage",
    "dark",
    "mermaid",
    # Architecture section
    "architecture",
    "Research Pipeline",
    "Verification Pipeline",
]


def find_latest_report() -> Path | None:
    reports = sorted(Path("reports").glob("report_*.html"), key=lambda p: p.stat().st_mtime)
    return reports[-1] if reports else None


def validate(path: Path) -> list[str]:
    html = path.read_text(encoding="utf-8")
    failures = []
    for needle in REQUIRED_STRINGS:
        if needle not in html:
            failures.append(f"MISSING: '{needle}'")
    return failures


def main() -> None:
    report = find_latest_report()
    if not report:
        print("✗ No report found in reports/. Run the pipeline first.")
        sys.exit(1)

    print(f"Validating: {report}")
    failures = validate(report)

    if failures:
        print(f"\n✗ {len(failures)} check(s) failed:")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    else:
        size_kb = report.stat().st_size / 1024
        print(f"✓ All {len(REQUIRED_STRINGS)} checks passed ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
