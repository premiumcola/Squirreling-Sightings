"""K3 · offline tracklet stitching.

Re-joins the fragments a single physical subject leaves behind — the
back-and-forth walker that the live matcher splits into a handful of
short tracklets — into one identity, using only OBSERVED endpoints
(no extrapolated velocity). Two passes, both conservative: same label
only, and simultaneous but spatially separate tracks are never merged.
Gate constants live in :mod:`._consts`.
"""

from __future__ import annotations

import logging

from ..bbox_utils import bbox_centroid_dist, iou
from ._consts import (
    STITCH_DIST_FACTOR,
    STITCH_MAX_GAP_S,
    STITCH_OVERLAP_IOU,
    STITCH_SIZE_RATIO,
)
from ._samples import bb_dims, bb_tuple, observed_samples

log = logging.getLogger(__name__)


def _t_first_last_detect(track):
    """Return ``(t_first, t_last, bb_first, bb_last)`` for the first
    and LAST observed samples, or ``None`` when the track has no
    observed samples."""
    det = observed_samples(track)
    if not det:
        return None
    return (
        float(det[0].get("t", 0.0)),
        float(det[-1].get("t", 0.0)),
        det[0]["bbox"],
        det[-1]["bbox"],
    )


def can_stitch_sequential(a, b) -> tuple[bool, str]:
    """Return ``(yes, reason)``. ``b`` must start AFTER ``a`` ends.
    Same-label, time gap small, spatial endpoints consistent.
    """
    if a.label != b.label:
        return False, "label-mismatch"
    a_meta = _t_first_last_detect(a)
    b_meta = _t_first_last_detect(b)
    if not a_meta or not b_meta:
        return False, "no-detect-samples"
    _, t_a_end, _, bb_a_end = a_meta
    t_b_start, _, bb_b_start, _ = b_meta
    if t_b_start < t_a_end - 0.01:
        return False, "b-starts-before-a-ends"
    gap = t_b_start - t_a_end
    if gap > STITCH_MAX_GAP_S:
        return False, f"gap={gap:.1f}>{STITCH_MAX_GAP_S}"
    aw, ah = bb_dims(bb_a_end)
    bw, bh = bb_dims(bb_b_start)
    sz_w = max(aw, bw) / max(1.0, float(min(aw, bw)))
    sz_h = max(ah, bh) / max(1.0, float(min(ah, bh)))
    if sz_w > STITCH_SIZE_RATIO or sz_h > STITCH_SIZE_RATIO:
        return False, f"size-ratio={max(sz_w, sz_h):.2f}>{STITCH_SIZE_RATIO}"
    dist = bbox_centroid_dist(bb_a_end, bb_b_start)
    max_dim = max(aw, ah, bw, bh)
    max_dist = STITCH_DIST_FACTOR * max_dim
    if dist > max_dist:
        return False, f"dist={dist:.0f}>{max_dist:.0f}"
    return True, (
        f"gap={gap:.1f}s dist={dist:.0f}px max_dim={max_dim} " f"size_ratio={max(sz_w, sz_h):.2f}"
    )


def overlap_iou_sustained(a, b) -> float:
    """Return the MEAN IoU of observed samples that share frame indices
    between tracklets a and b. 0.0 if they don't share any frame."""
    a_by_f = {int(s["f"]): s["bbox"] for s in observed_samples(a)}
    b_by_f = {int(s["f"]): s["bbox"] for s in observed_samples(b)}
    shared = a_by_f.keys() & b_by_f.keys()
    if not shared:
        return 0.0
    total = 0.0
    for f in shared:
        total += iou(bb_tuple(a_by_f[f]), bb_tuple(b_by_f[f]))
    return total / float(len(shared))


def absorb(into, donor) -> None:
    """Merge donor's samples into ``into``. Frame-deduped; sample
    list re-sorted. Aggregate fields refreshed from the unified set.
    ``donor`` is left empty + marked inactive — caller drops it."""
    existing_frames = {int(s.get("f", -1)) for s in (into.samples or [])}
    for s in donor.samples or []:
        if int(s.get("f", -1)) in existing_frames:
            continue
        into.samples.append(s)
    into.samples.sort(key=lambda s: int(s.get("f", 0)))
    if into.samples:
        into.first_frame = min(into.first_frame, donor.first_frame)
        into.last_frame = max(into.last_frame, donor.last_frame)
    for s in into.samples or []:
        sc = s.get("score")
        if sc is not None and float(sc) > float(into.best_score or 0.0):
            into.best_score = float(sc)
            into.best_frame_idx = int(s.get("f", 0))
    donor.samples = []
    donor.active = False
    donor.end_reason = "stitched"


def _pass_sequential(closed) -> int:
    """Pass 1 · order tracklets by first observed t; for each later
    tracklet B link it to the closest earlier predecessor A that passes
    :func:`can_stitch_sequential`. Repeats until a round finds nothing,
    so chains of fragments collapse into one."""
    absorbed_total = 0
    while True:
        # Build start-time index over CURRENT (post-merge) survivors.
        live = [t for t in closed if t.samples]
        if len(live) < 2:
            return absorbed_total
        live.sort(key=lambda t: _t_first_last_detect(t)[0] if _t_first_last_detect(t) else 0.0)
        merged_this_round = 0
        absorbed_set: set = set()
        for j, b in enumerate(live):
            if id(b) in absorbed_set:
                continue
            best_a = None
            best_gap = STITCH_MAX_GAP_S + 1.0
            for i in range(j):
                a = live[i]
                if id(a) in absorbed_set:
                    continue
                ok, _why = can_stitch_sequential(a, b)
                if not ok:
                    continue
                a_meta = _t_first_last_detect(a)
                b_meta = _t_first_last_detect(b)
                if not a_meta or not b_meta:
                    continue
                gap = b_meta[0] - a_meta[1]
                if 0.0 <= gap < best_gap:
                    best_gap = gap
                    best_a = a
            if best_a is not None:
                log.info(
                    "[tracking] stitch tid=%s ← tid=%s · gap=%.1fs (sequential)",
                    best_a.track_id,
                    b.track_id,
                    best_gap,
                )
                absorb(best_a, b)
                absorbed_set.add(id(b))
                merged_this_round += 1
        absorbed_total += merged_this_round
        if merged_this_round == 0:
            return absorbed_total


def _pass_overlap(closed) -> int:
    """Pass 2 · any same-label pair that shares observed frames whose
    mean IoU is ≥ STITCH_OVERLAP_IOU describes one object → merge.
    The tracklet with more observed samples wins the identity (ties
    broken toward the higher best_score) so the canonical track keeps
    going."""
    absorbed_total = 0
    while True:
        live = [t for t in closed if t.samples]
        if len(live) < 2:
            return absorbed_total
        merged = 0
        for i in range(len(live)):
            a = live[i]
            if not a.samples:
                continue
            for k in range(i + 1, len(live)):
                b = live[k]
                if not b.samples or a.label != b.label:
                    continue
                if overlap_iou_sustained(a, b) < STITCH_OVERLAP_IOU:
                    continue
                a_n = len(observed_samples(a))
                b_n = len(observed_samples(b))
                if (b_n, b.best_score or 0.0) > (a_n, a.best_score or 0.0):
                    into, donor = b, a
                else:
                    into, donor = a, b
                log.info(
                    "[tracking] stitch tid=%s ← tid=%s · overlap-iou (parallel)",
                    into.track_id,
                    donor.track_id,
                )
                absorb(into, donor)
                merged += 1
                break  # restart outer loop
            if merged:
                break
        absorbed_total += merged
        if merged == 0:
            return absorbed_total


def stitch_tracklets_offline(state) -> int:
    """Run both stitching passes over ``state.closed`` before payload
    serialisation, prune the emptied donors, and return the number of
    tracklets absorbed."""
    closed = state.closed
    if len(closed) < 2:
        return 0
    absorbed_total = _pass_sequential(closed) + _pass_overlap(closed)
    # Prune absorbed (empty + inactive) tracklets from the closed list.
    state.closed = [t for t in closed if t.samples]
    return absorbed_total
