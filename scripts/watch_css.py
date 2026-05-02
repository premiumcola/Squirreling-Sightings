#!/usr/bin/env python3
"""Dev watch mode for the CSS build step.

Polls ``app/web/static/css/`` for mtime changes and rebuilds ``app.css`` on
change. Plain stdlib polling — no inotify dependency, works on every host.
Interval is 0.5 s which is responsive enough for live editing."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "app"))

from app.css_builder import build_css  # noqa: E402

PARTIALS = REPO_ROOT / "app" / "web" / "static" / "css"


def _snapshot() -> tuple:
    if not PARTIALS.is_dir():
        return ()
    return tuple(sorted((p.name, p.stat().st_mtime_ns) for p in PARTIALS.glob("*.css")))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("css")
    last = None
    log.info("[css] watching %s", PARTIALS)
    try:
        while True:
            cur = _snapshot()
            if cur != last:
                build_css(log=log)
                last = cur
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
