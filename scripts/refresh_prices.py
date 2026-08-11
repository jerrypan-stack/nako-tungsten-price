#!/usr/bin/env python3
"""One-click refresh: scrape same sources → data.json + embed into index.html."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Default: JSON + HTML only (no Excel / canvas)
os.environ.setdefault("SKIP_EXCEL", "1")
os.environ.setdefault("SKIP_CANVAS", "1")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import scrape_all  # noqa: E402


def main() -> None:
    scrape_all.main()
    print("Refresh complete. Push to main to update GitHub Pages.")


if __name__ == "__main__":
    main()
