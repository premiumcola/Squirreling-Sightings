#!/usr/bin/env python3
"""Host-side CLI wrapper for the CSS build step.

Usage from repo root::

    python scripts/build_css.py

Real implementation lives in ``app/app/css_builder.py`` so the same code runs
both inside the container (called from server boot) and on the host."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "app"))

from app.css_builder import build_css  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    changed = build_css(log=logging.getLogger("css"))
    sys.exit(0 if changed else 0)
