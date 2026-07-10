#!/usr/bin/env python3
"""
scripts/inline_assets.py
-------------------------
Post-processes the generated HTML report to inline Chart.js from disk,
eliminating CDN dependency that gets blocked by Brave/Firefox shields.
Run automatically by generate_sample_report.py after report generation.
"""
from __future__ import annotations

import sys
from pathlib import Path

CHARTJS_PATH = Path(__file__).parent.parent / "static" / "chart.min.js"
CDN_TAG = (
    '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>'
)


def inline_chartjs(html_path: str | Path) -> bool:
    html_path = Path(html_path)
    if not CHARTJS_PATH.exists():
        print(f"  ⚠ Chart.js not found at {CHARTJS_PATH} — skipping inline")
        return False

    html = html_path.read_text(encoding="utf-8")
    if CDN_TAG not in html:
        print("  ℹ Chart.js CDN tag not found — already inlined or different version")
        return False

    chartjs_code = CHARTJS_PATH.read_text(encoding="utf-8")
    inlined = html.replace(CDN_TAG, f"<script>{chartjs_code}</script>")
    html_path.write_text(inlined, encoding="utf-8")

    original_kb = len(html) / 1024
    new_kb = len(inlined) / 1024
    print(f"  ✓ Inlined Chart.js ({new_kb - original_kb:.0f} KB added, total {new_kb:.0f} KB)")
    return True


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "reports/report_composio.html"
    inline_chartjs(path)
    if Path("docs/index.html").exists():
        inline_chartjs("docs/index.html")
