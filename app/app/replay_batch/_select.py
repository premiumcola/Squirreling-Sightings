"""Which archived events the batch replays.

The walk mirrors `bird_species_backfill.py::find_backfill_candidates`
exactly — same tree (`store.events_dir/<cam>/<date>/<event>.json`), same
`.tracks.json` skip, same "a malformed document is skipped, never
fatal" stance. It is a separate predicate rather than a parameter on
that function because the two select for opposite things: the backfill
wants birds that are still UNNAMED, this wants every bird clip whether
named or not.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

from ._consts import BIRD_LABELS

log = logging.getLogger(__name__)


def is_bird_event(event: dict) -> bool:
    """True when this event is about a bird.

    Three independent tells, because the three were written at
    different times and old documents carry only some of them:
      * `labels` contains a bird label (the confirmed label set),
      * `top_label` is a bird (set even when labels stayed ["motion"] —
        see camera_runtime/_motion.py::_upgrade_event_meta),
      * any detection carries a bird label (the raw per-box truth,
        present even when neither aggregate mentions it).
    """
    labels = event.get("labels") or []
    if any(lbl in BIRD_LABELS for lbl in labels):
        return True
    if (event.get("top_label") or "") in BIRD_LABELS:
        return True
    return any((d.get("label") or "") in BIRD_LABELS for d in event.get("detections") or [])


def event_day(event: dict, fallback_stem: str = "") -> str:
    """The `YYYYMMDD` this event belongs to.

    Read from the event_id, whose format is fixed at
    `_motion.py::_build_event_meta` as ``%Y%m%d-%H%M%S-%f``. Falls back
    to the filename stem, which carries the same id. Returns "" when
    neither parses, and a "" day never matches a range bound — an event
    we cannot date is left out of a dated run rather than guessed into
    it.
    """
    raw = (event.get("event_id") or fallback_stem or "").strip()
    head = raw.split("-", 1)[0]
    return head if len(head) == 8 and head.isdigit() else ""


def in_range(day: str, since: str | None, until: str | None) -> bool:
    """Inclusive `YYYYMMDD` string comparison. Zero-padded fixed-width
    dates order lexicographically the same way they order
    chronologically, so no date parsing is needed here."""
    if not day:
        return not (since or until)
    if since and day < since:
        return False
    return not (until and day > until)


def find_bird_events(
    store,
    cam_ids: list[str] | None = None,
    *,
    since: str | None = None,
    until: str | None = None,
) -> Iterator[tuple[str, str, dict]]:
    """Yield ``(camera_id, event_id, event)`` for every archived bird
    event, optionally narrowed to `cam_ids` and to a `YYYYMMDD` range.

    A generator, so the caller can count progress against a cheap first
    pass and stream the second without holding the whole archive in
    memory.
    """
    events_dir = getattr(store, "events_dir", None)
    if events_dir is None:
        return
    events_dir = Path(events_dir)
    if not events_dir.exists():
        return
    if cam_ids:
        cam_dirs = [events_dir / cid for cid in cam_ids if (events_dir / cid).exists()]
    else:
        cam_dirs = sorted(d for d in events_dir.iterdir() if d.is_dir())
    for cam_dir in cam_dirs:
        camera_id = cam_dir.name
        for jf in sorted(cam_dir.rglob("*.json")):
            if jf.name.endswith(".tracks.json"):
                continue
            try:
                event = json.loads(jf.read_text(encoding="utf-8"))
            except Exception as e:
                log.debug("[tracking] batch replay: skip malformed %s: %s", jf, e)
                continue
            if not isinstance(event, dict) or not is_bird_event(event):
                continue
            if not in_range(event_day(event, jf.stem), since, until):
                continue
            yield camera_id, event.get("event_id") or jf.stem, event
