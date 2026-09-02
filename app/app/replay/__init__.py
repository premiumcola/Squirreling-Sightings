"""Replay a stored clip through the detection pipeline.

Every event since the provenance snapshot shipped records the exact
constellation it was captured with. This package is the other half of
that: it takes a stored clip and runs it back through the SAME post-clip
machinery the tracking worker uses, with a settings set of the
operator's choosing — the one on record, the camera's current profile,
or an explicit set of overrides — and reports what changed.

The overrides case is what makes an optimisation sweep possible: run one
clip N times with N candidate tunings, diff each against the baseline,
and keep the tuning whose diff reads best. `diff_detections` is pure and
independently tested for exactly that use.

Public re-exports only.
"""

from __future__ import annotations

from ._alarm import alert_preview
from ._consts import REPLAY_HISTORY_CAP, REPLAY_MAX_SAMPLES, REPLAY_SCHEMA
from ._diff import bbox_tuple, diff_detections, iou, normalise_detection, track_to_detection
from ._persist import append_replay, build_entry
from ._report import build_comparison, original_side
from ._run import replay_clip
from ._settings import project_settings, resolve_replay_settings, settings_hash

__all__ = [
    "REPLAY_HISTORY_CAP",
    "REPLAY_MAX_SAMPLES",
    "REPLAY_SCHEMA",
    "alert_preview",
    "append_replay",
    "bbox_tuple",
    "build_comparison",
    "build_entry",
    "diff_detections",
    "iou",
    "normalise_detection",
    "original_side",
    "project_settings",
    "replay_clip",
    "resolve_replay_settings",
    "settings_hash",
    "track_to_detection",
]
