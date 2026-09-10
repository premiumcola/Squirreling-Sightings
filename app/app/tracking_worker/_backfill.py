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

SCOPE, AND WHY IT DIFFERS BY CALLER. The full archive is walked ONCE,
at boot, which is when a fresh install or a new rule has a backlog to
clear. After that there is nothing to find in last year's clips: every
finished recording enqueues its own fine track, so anything still
missing one went missing in the last day or two — „jede nacht brauchen
wir danach nicht mehr auf alle videos weil die ja korrekt aufgenommen
werden!". `since_days` is what makes the nightly pass a short look back
instead of a full sweep; the route and the boot run pass nothing and
still see everything.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from ._consts import TRACKS_SCHEMA
from ._job import TrackingJob, tracks_path_for

log = logging.getLogger("app.tracking")


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


def recent_day_dirs(cam_dir: Path, since_days: int | None) -> list[Path]:
    """Day folders in `cam_dir` worth looking at.

    Events live under `<cam>/<YYYY-MM-DD>/`, so a window is a name
    comparison rather than a stat of every file — the whole point of
    scoping the nightly pass. An unparseable folder name is always
    included: it is cheaper to look than to be clever about it.
    """
    if not since_days or since_days < 0:
        return [d for d in cam_dir.iterdir() if d.is_dir()]
    cutoff = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%d")
    out = []
    for d in cam_dir.iterdir():
        if not d.is_dir():
            continue
        if len(d.name) == 10 and d.name[4] == "-" and d.name < cutoff:
            continue
        out.append(d)
    return out


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
    since_days: int | None = None,
) -> dict:
    """Queue every clip in scope whose fine track is missing or stale.

    `since_days` limits the walk to day folders that recent — see the
    module docstring for why the nightly caller wants that and the boot
    caller does not.

    Returns ``{queued, up_to_date, missing_video, remaining}`` —
    ``remaining`` is non-zero only when ``budget`` cut the pass short, so
    a caller can say "more tomorrow" instead of implying it is done.
    """
    if worker is None:
        return {"queued": 0, "up_to_date": 0, "missing_video": 0, "remaining": 0}
    root = Path(storage_root)
    queued = up_to_date = missing_video = remaining = 0
    for cam_dir in _camera_dirs(store, cam_filter):
        for day_dir in recent_day_dirs(cam_dir, since_days):
            for jf in day_dir.rglob("*.json"):
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
