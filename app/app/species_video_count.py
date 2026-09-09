"""How many CONFIRMED video clips of one bird species already exist.

The number `camera_runtime/_recording_step.py::_start_clip` compares
against `storage.bird_species_video_cap` before deciding whether the
NEXT sighting of that species is worth another full recording, or only
a lightweight info-only sighting (see `retention_catalog.py`'s
"Vogel-Arten" row and the operator's own framing: "wenn man zwanzig
zwanzig von einem hat, dann nur noch eins").

Deliberately NOT derived from `detection_feedback`'s diagnostic ledger,
even though a Telegram "Ja" also writes a verdict there: that ledger is
explicitly bounded and prunes old records once it hits its size cap
(`_io._compact` / `_retention.select_retained`), which is correct for a
calibration corpus but wrong here — a species whose old confirmations
happened to age out of the ledger would silently uncap itself. This is
a small, never-pruned, monotonic counter instead, one file for every
species, the same pattern `species_unlock.py` already uses for the
first-sighting achievement (a DIFFERENT trigger — that one fires on the
live guess alone; this one only on an operator's confirmation).

Deliberately NOT a full storage scan either (unlike
`storage_stats.top_bird_species`, which is fine for a page load but far
too slow for a per-event check on the recording thread).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from .io_utils import atomic_write_json

log = logging.getLogger("app.sichtungen")

#: One lock per process, like species_unlock.py's — two cameras
#: confirming a species in the same second must not race a read-modify-
#: write and drop one increment.
_LOCK = threading.Lock()

_FILE_NAME = "species_video_counts.json"


def _path(storage_root) -> Path:
    return Path(storage_root) / _FILE_NAME


def _key(species: str | None) -> str:
    return (species or "").strip().lower()


def confirmed_video_count(storage_root, species: str | None) -> int:
    """How many confirmed video clips of ``species`` are already on
    record. ``0`` for an empty species, a missing file, or a corrupt one
    — the cap this feeds must fail open (keep recording) rather than
    closed (silently stop) when the count cannot be trusted."""
    key = _key(species)
    if not key or storage_root is None:
        return 0
    path = _path(storage_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    try:
        return max(0, int(data.get(key, 0)))
    except (TypeError, ValueError):
        return 0


def record_confirmed_video(storage_root, species: str | None) -> int:
    """One more confirmed video of ``species``. Returns the new count,
    ``0`` on any failure (an uncounted confirmation is a missed cap, not
    a lost one — never worth raising out of a Telegram callback for).

    Call this ONLY from an operator confirmation (a Telegram "Ja" on a
    bird event, a species correction, or the web confirm route) — never
    from the recording path itself, which reads this count to decide
    whether to record at all; counting there would be circular.
    """
    key = _key(species)
    if not key or storage_root is None:
        return 0
    path = _path(storage_root)
    with _LOCK:
        try:
            data: dict = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        try:
            current = max(0, int(data.get(key, 0)))
        except (TypeError, ValueError):
            current = 0
        data[key] = current + 1
        try:
            atomic_write_json(path, data)
        except Exception as e:
            log.warning("[sichtungen] Art-Zähler für %s nicht geschrieben: %s", species, e)
            return current
    log.info("[sichtungen] bestätigtes Video gezählt: %s → %d", species, data[key])
    return data[key]
