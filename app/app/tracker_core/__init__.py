"""Pure two-tier object-tracking algorithm shared by the post-clip
worker AND the live camera-runtime path.

Carved out of ``tracking_worker.py`` so both callers reach the same
ByteTrack-style logic — confirmed detections spawn / extend tracks,
tentative (sub-spawn, above-floor) detections may only extend an
existing IoU-matched track. The motion model in :mod:`._motion`
predicts each track forward before the overlap test, so a subject
that moves further than its own bbox between samples still matches
itself; a miss-grace window keeps a track alive across short
occlusions.

Module scope is intentionally tight: NO file I/O, NO queue, NO event
store, NO Flask app state. Both callers wrap this module with their
own orchestration — see ``tracking_worker.TrackingWorker`` (post-clip)
and ``camera_runtime._main_loop`` (live).

Layout — this file is re-exports only, one module per concern:

* :mod:`._consts`    — every tuned threshold, with its rationale
* :mod:`._helpers`   — id / colour minting, tier + miss-grace maths
* :mod:`._state`     — ``TrackerState``, the per-run container
* :mod:`._track`     — ``Track``, one subject's mutable state
* :mod:`._motion`    — velocity, prediction, newborn bootstrap gate
* :mod:`._nms`       — per-label non-max suppression
* :mod:`._adopt`     — spawn-block, proximity adopt, re-identification
* :mod:`._merge`     — J3 duplicate fold
* :mod:`._associate` — the per-frame association step
* :mod:`._live`      — ``LiveTracker``, the per-camera wrapper
* :mod:`._resolve`   — settings → effective thresholds
"""

from __future__ import annotations

from ._adopt import nearby_track, spawn_blocking_track, try_reidentify
from ._associate import associate_detections, update_best_top
from ._consts import (
    BOOTSTRAP_DIST_FACTOR,
    BOOTSTRAP_MAX_ELAPSED,
    EDGE_GRACE_SAMPLES,
    EDGE_MARGIN_PX,
    IOU_MATCH_THRESHOLD,
    LIVE_CLOSED_CAP,
    MERGE_IOU,
    MERGE_SUSTAIN,
    MISS_GRACE_DEFAULT_SECONDS,
    NMS_IOU,
    PRED_DECAY_CAP_SAMPLES,
    PRED_DECAY_FULL_SAMPLES,
    PRED_MAX_STEP_FRAC,
    PRED_MAX_TOTAL_FRAC,
    PRED_VELOCITY_WINDOW,
    REID_OCCUPIED_IOU,
    SAMPLE_BBOX_DELTA_PX,
    SPAWN_BLOCK_CONTAIN,
    SPAWN_BLOCK_IOU,
    STATIONARY_SPEED_FRAC,
    TRACK_FLOOR_SCORE,
    TRACK_MISS_WINDOWS,
    TRACK_REID_DIST_FACTOR,
    TRACK_REID_MAX_SECONDS,
    TRACK_REID_SIZE_RATIO,
    TRACK_SPAWN_SCORE,
)
from ._helpers import (
    classify_tier,
    color_for_track,
    compute_miss_grace_samples,
    short_id,
)
from ._live import LiveTracker
from ._merge import merge_active_duplicates
from ._motion import (
    bootstrap_gate,
    bootstrap_match_score,
    predicted_bbox,
    recent_observed_samples,
    velocity_estimate,
)
from ._nms import nms_per_label
from ._resolve import TrackThresholds, resolve_track_thresholds
from ._state import TrackerState
from ._track import Track

__all__ = [
    "BOOTSTRAP_DIST_FACTOR",
    "BOOTSTRAP_MAX_ELAPSED",
    "EDGE_GRACE_SAMPLES",
    "EDGE_MARGIN_PX",
    "IOU_MATCH_THRESHOLD",
    "LIVE_CLOSED_CAP",
    "MERGE_IOU",
    "MERGE_SUSTAIN",
    "MISS_GRACE_DEFAULT_SECONDS",
    "NMS_IOU",
    "PRED_DECAY_CAP_SAMPLES",
    "PRED_DECAY_FULL_SAMPLES",
    "PRED_MAX_STEP_FRAC",
    "PRED_MAX_TOTAL_FRAC",
    "PRED_VELOCITY_WINDOW",
    "REID_OCCUPIED_IOU",
    "SAMPLE_BBOX_DELTA_PX",
    "SPAWN_BLOCK_CONTAIN",
    "SPAWN_BLOCK_IOU",
    "STATIONARY_SPEED_FRAC",
    "TRACK_FLOOR_SCORE",
    "TRACK_MISS_WINDOWS",
    "TRACK_REID_DIST_FACTOR",
    "TRACK_REID_MAX_SECONDS",
    "TRACK_REID_SIZE_RATIO",
    "TRACK_SPAWN_SCORE",
    "LiveTracker",
    "Track",
    "TrackThresholds",
    "TrackerState",
    "associate_detections",
    "bootstrap_gate",
    "bootstrap_match_score",
    "classify_tier",
    "color_for_track",
    "compute_miss_grace_samples",
    "merge_active_duplicates",
    "nearby_track",
    "nms_per_label",
    "predicted_bbox",
    "recent_observed_samples",
    "resolve_track_thresholds",
    "short_id",
    "spawn_blocking_track",
    "try_reidentify",
    "update_best_top",
    "velocity_estimate",
]
