"""Serialisation of a finished run into the tracks.json sidecar.

The mp4 is never touched — the sidecar is subtitle-style data the
lightbox overlays on playback. Writes go through a tmp file + rename
so a reader never sees a half-written document.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..tracker_core import MISS_GRACE_DEFAULT_SECONDS, TRACK_FLOOR_SCORE, TRACK_SPAWN_SCORE
from ._consts import TRACKS_SCHEMA
from ._job import safe_relpath


def build_payload(
    state,
    fps: float,
    frame_count: int,
    duration_s: float,
    allowed,
    video_path: Path,
    storage_root: Path,
    *,
    spawn_score: float = TRACK_SPAWN_SCORE,
    floor_score: float = TRACK_FLOOR_SCORE,
    grace_s: float = MISS_GRACE_DEFAULT_SECONDS,
) -> dict:
    """Assemble the tracks.json payload. The track-serialisation block
    iterates state.closed; the caller is responsible for flushing any
    still-active tracks into closed before this runs.

    K3 · the ``gates`` block surfaces the thresholds the worker
    actually applied for this clip. The Mediathek timeline panel
    renders these inline when an indexed clip ends up with tracks=[]
    so the user sees the WHY (e.g. "kurze Sichtungen unter 50 %
    werden gefiltert") rather than the ambiguous "Keine Track-
    Daten — erscheinen sobald die Indexierung fertig ist". Per-
    camera overrides are honoured via the same resolve_track
    _thresholds() helper the live association loop uses."""
    return {
        "schema": TRACKS_SCHEMA,
        "video_path": safe_relpath(video_path, storage_root),
        "fps": round(float(fps), 3),
        "frame_count": frame_count,
        "duration_s": round(duration_s, 3),
        "best_frame": state.best_top,
        # `filter_applied` records the allowed object_filter at
        # write time. None = no filter (all classes accepted),
        # list = exactly these classes were considered.
        "filter_applied": sorted(allowed) if allowed is not None else None,
        # K3 (schema=4) · gate values the worker actually applied.
        # min_confidence is the spawn floor — detections below this
        # can only EXTEND an existing track via IoU, never spawn a
        # new one. raw_floor is the detector's per-frame threshold
        # (anything below isn't even returned for association).
        # miss_grace_s is the wall-clock window for a missed track
        # to recover before being closed.
        "gates": {
            "min_confidence": round(float(spawn_score), 3),
            "raw_floor": round(float(floor_score), 3),
            "miss_grace_s": round(float(grace_s), 2),
        },
        "tracks": [t.to_dict() for t in state.closed],
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def write_payload_atomic(tracks_path: Path, payload: dict) -> None:
    """Atomic write: tmp file + rename. Pattern matches B08."""
    tmp_path = tracks_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(tracks_path)
