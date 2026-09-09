"""Find clips whose fine track (`tracks.json`) is missing or stale, and
queue them.

WHY IT IS NOT ONLY A BUTTON ANY MORE. This scan existed as
``POST /api/tracking/reindex-all`` and, per clip, as the player's own
"Feinspur nachbauen" — both operator-initiated. So a clip that missed its
sidecar (the worker was busy, the container restarted mid-encode, the
clip predates the sidecar entirely) stayed without one until somebody
noticed the note in the player and pressed the button. That is exactly
the chore the operator refused: „Ich will wenn ichs anschau dass alles
bereit und fertig ist!" — opening a clip is not the moment to start a
job, it is the moment to have one finished.

The scan therefore lives here, called by BOTH the route and
``maintenance.py``'s daily tick (which also runs once at every boot). One
implementation, per CLAUDE.md's no-parallel-implementations rule; the
route keeps its own reply shape and simply reports what this returns.

BOUNDED ON THE UNATTENDED PATH. Each job decodes a clip, so an archive
that has never been indexed must not turn one nightly tick into hours of
CPU. ``budget`` caps how many are queued per call and the next tick picks
up where this one stopped — the same shape ``bird_dossiers.sweep_prebuild``
already uses for its own catch-up pass. The route passes no budget: an
operator who presses the button asked for all of it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ._consts import TRACKS_SCHEMA
from ._job import TrackingJob, tracks_path_for

log = logging.getLogger("app.tracking")

#: Clips queued per unattended sweep. Sized so a full nightly tick stays
#: minutes rather than hours on this hardware; the backlog drains over a
#: few nights and steady state is zero (every finalised clip enqueues
#: itself, see camera_runtime/_recording/__init__.py).
DEFAULT_BACKFILL_BUDGET = 40


def _needs_tracks(tracks_file: Path) -> bool:
    """True when the sidecar is absent, unreadable, or written against an
    older schema. A corrupt file is treated as missing — re-walking the
    clip is cheaper than reasoning about half a sidecar."""
    if not tracks_file.exists():
        return True
    try:
        return json.loads(tracks_file.read_text(encoding="utf-8")).get("schema") != TRACKS_SCHEMA
    except Exception:
        return True


def _camera_dirs(store, cam_filter: str | None) -> list[Path]:
    events_dir = getattr(store, "events_dir", None)
    if events_dir is None or not Path(events_dir).exists():
        return []
    if cam_filter:
        one = Path(events_dir) / cam_filter
        return [one] if one.exists() else []
    return [d for d in Path(events_dir).iterdir() if d.is_dir()]


def sweep_missing_tracks(
    store,
    storage_root,
    worker,
    *,
    cam_filter: str | None = None,
    budget: int | None = None,
) -> dict:
    """Queue every clip in scope whose fine track is missing or stale.

    Returns ``{queued, up_to_date, missing_video, remaining}`` —
    ``remaining`` is non-zero only when ``budget`` cut the pass short, so
    a caller can say "more tomorrow" instead of implying it is done.
    """
    if worker is None:
        return {"queued": 0, "up_to_date": 0, "missing_video": 0, "remaining": 0}
    root = Path(storage_root)
    queued = up_to_date = missing_video = remaining = 0
    for cam_dir in _camera_dirs(store, cam_filter):
        for jf in cam_dir.rglob("*.json"):
            if jf.name.endswith(".tracks.json"):  # our own sidecar, not an event
                continue
            try:
                event = json.loads(jf.read_text(encoding="utf-8"))
            except Exception:
                continue
            video_rel = event.get("video_relpath")
            if not video_rel:
                continue
            video = root / video_rel
            if not video.exists():
                missing_video += 1
                continue
            if not _needs_tracks(tracks_path_for(video)):
                up_to_date += 1
                continue
            if budget is not None and queued >= budget:
                remaining += 1
                continue
            worker.enqueue(
                TrackingJob(
                    event_id=event.get("event_id", jf.stem),
                    video_path=video,
                    snapshot_path=None,
                    camera_id=cam_dir.name,
                )
            )
            queued += 1
    return {
        "queued": queued,
        "up_to_date": up_to_date,
        "missing_video": missing_video,
        "remaining": remaining,
    }
