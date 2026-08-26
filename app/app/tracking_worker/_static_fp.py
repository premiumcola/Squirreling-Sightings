"""K1 · the static-false-positive sweep.

Catches the chair / pole / lamp / shadow-as-person cluster that the
model reports with low-but-nonzero confidence for the whole clip and
that would otherwise flood the timeline with full-length lanes for
objects which never moved. Gate rationale lives with the constants in
:mod:`._consts`.
"""

from __future__ import annotations

import logging

from ..bbox_utils import bbox_centroid_dist
from ._consts import STATIC_FP_DISP_FRAC, STATIC_FP_MIN_DETECTS
from ._samples import bb_dims, observed_samples

log = logging.getLogger(__name__)


def _median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def is_static_false_positive(track, spawn_score: float):
    """Return ``(drop: bool, reason: str)`` per the static-FP gates."""
    det = observed_samples(track)
    if len(det) < STATIC_FP_MIN_DETECTS:
        return False, ""
    median_score = _median(float(s.get("score") or 0.0) for s in det)
    if median_score >= spawn_score:
        return False, ""  # genuinely confident → keep regardless of motion
    net_px = bbox_centroid_dist(det[0]["bbox"], det[-1]["bbox"])
    med_bw = _median(bb_dims(s["bbox"])[0] for s in det)
    med_bh = _median(bb_dims(s["bbox"])[1] for s in det)
    med_dim = min(med_bw, med_bh)
    if med_dim <= 0:
        return False, ""
    motion_floor = STATIC_FP_DISP_FRAC * med_dim
    if net_px >= motion_floor:
        return False, ""  # walked enough to be a real subject
    # Maximum single-step displacement — if even ONE pair of
    # consecutive samples shifted significantly, treat as moving
    # (could be a partly-visible person who paused briefly).
    max_step = 0.0
    for i in range(1, len(det)):
        step = bbox_centroid_dist(det[i - 1]["bbox"], det[i]["bbox"])
        if step > max_step:
            max_step = step
    if max_step >= motion_floor:
        return False, ""
    reason = (
        f"static-fp · median_score={median_score:.2f}<spawn={spawn_score:.2f}, "
        f"net={net_px:.0f}px<{motion_floor:.0f}, max_step={max_step:.0f}px"
    )
    return True, reason


def filter_static_false_positives(state, spawn_score: float) -> None:
    """In-place purge of static-FP tracklets from ``state.closed``.
    Each drop logs one INFO line so the operator can audit which
    tracks were silenced and why.
    """
    survivors = []
    for tr in state.closed:
        drop, reason = is_static_false_positive(tr, spawn_score)
        if drop:
            log.info(
                "[tracking] drop tid=%s n=%d best=%.2f label=%s · %s",
                tr.track_id,
                len(observed_samples(tr)),
                float(tr.best_score or 0.0),
                tr.label,
                reason,
            )
            continue
        survivors.append(tr)
    state.closed = survivors
