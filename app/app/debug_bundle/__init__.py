"""Debug-Bundle — one ZIP that answers "what was this box doing?".

A bug report about detection needs the tuning, the models, the recent
events, the live state and the log — five places, four of which the
operator cannot reach from the phone they noticed the problem on. This
packs all five into ``storage/debug/bundle-<YYYYMMDD-HHMMSS>.zip`` and
hands back a URL.

The archive is built to be forwarded, so redaction is not a courtesy
here: every section goes through :mod:`app.simu_log._scrub`, and the raw
``settings.json`` is never a section at all — see :mod:`._sections`.

Bounded like the SIMU log it borrows its shape from: retention runs on
every write, not on a schedule.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from . import _sections
from ._consts import ARC_CONFIG, ARC_LOG, ARC_STATUS, ARC_TELEMETRY, EVENT_COUNT, MAX_BUNDLES
from ._entries import build_entries
from ._writer import bundle_url, describe, list_bundles, prune, write_bundle

log = logging.getLogger(__name__)

__all__ = [
    "ARC_CONFIG",
    "ARC_LOG",
    "ARC_STATUS",
    "ARC_TELEMETRY",
    "EVENT_COUNT",
    "MAX_BUNDLES",
    "build_entries",
    "bundle_url",
    "create_bundle",
    "list_bundles",
    "prune",
    "redact_settings",
]

redact_settings = _sections.redact_settings


def create_bundle(storage_root, now: datetime | None = None) -> dict:
    """Collect, write, prune. Returns ``{ok, name, path, url, size}``."""
    root = Path(storage_root)
    stamp = now or datetime.now()
    entries = build_entries(root, stamp)
    path = write_bundle(root, entries, stamp)
    dropped = prune(root)
    out = describe(path)
    out["ok"] = True
    out["dropped"] = dropped
    log.info("[storage] debug bundle %s geschrieben (%d Byte)", out["name"], out["size"])
    return out
