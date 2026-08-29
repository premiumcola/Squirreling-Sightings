"""Adoption · what happens to a confirmed detection that found no track.

``associate_detections`` runs three positional passes (predicted-IoU for
both tiers, then the velocity bootstrap). A confirmed detection that
survives all three is an ORPHAN: nothing overlapped it. Spawning a fresh
id for every orphan is what fragments one subject into a column of
short-lived tracks, so an orphan is offered to the adoption paths here
before it is allowed an id of its own:

* :func:`spawn_blocking_track` (J2) — strong overlap with ANY active
  track. Either a same-label duplicate the NMS gate let through, or a
  cross-label misclassification of an already-tracked subject.
* :func:`nearby_track` (J6) — a same-label active track whose position
  estimate sits within a bbox dimension of the detection. Scale-aware
  where a raw IoU is not, and the gate that keeps a turning person on
  one id; see the arithmetic at ``SPAWN_NEAR_DIST_FACTOR``.
* :func:`try_reidentify` — a recently CLOSED same-label track, for the
  "walked back in after the grace expired" case.

Ordering is the caller's business, but extending a LIVE track always
beats resurrecting a dead one and both beat a fresh id. The gates here
are pure predicates over tracker state and hold no state of their own.
"""

from __future__ import annotations

from ..bbox_utils import iou
from ._consts import (
    REID_OCCUPIED_IOU,
    SPAWN_BLOCK_IOU,
    SPAWN_NEAR_DIST_FACTOR,
    SPAWN_NEAR_H_RATIO,
    TRACK_REID_DIST_FACTOR,
    TRACK_REID_MAX_SECONDS,
    TRACK_REID_SCAN_DEPTH,
    TRACK_REID_SIZE_RATIO,
)
from ._motion import recent_observed_samples


def _bbox_tuple(bb: dict) -> tuple[int, int, int, int]:
    """A tracks.json sample bbox dict as an ``(x1, y1, x2, y2)`` tuple."""
    return (int(bb["x1"]), int(bb["y1"]), int(bb["x2"]), int(bb["y2"]))


def last_observed_bbox(track):
    """The track's last DETECT-source bbox as a tuple, or None.

    Deliberately NOT ``samples[-1]``: during the miss-grace window that
    is a ``predicted`` sample, i.e. the tracker's own extrapolation. A
    gate that reads it believes it is checking an observation while it
    is really checking the motion model against itself — and loses its
    one reference that is independent of the model exactly when the
    model is the thing that went wrong."""
    obs = recent_observed_samples(track, 1)
    return _bbox_tuple(obs[0]["bbox"]) if obs else None


def _axis_normalised_offset(det_bbox, ref) -> float:
    """Centroid offset between a detection and a reference box, with dx
    normalised by width and dy by height (the larger of the two boxes on
    each axis). 1.0 means "one box away" on whichever axis it moved.

    Normalising per axis rather than by one radius is what makes the
    gate survive an aspect change: a person's box widens as they turn,
    but the offset that matters is still measured in widths."""
    dw = max(1.0, float(det_bbox[2] - det_bbox[0]))
    dh = max(1.0, float(det_bbox[3] - det_bbox[1]))
    rw = max(1.0, float(ref[2] - ref[0]))
    rh = max(1.0, float(ref[3] - ref[1]))
    ox = ((det_bbox[0] + det_bbox[2]) - (ref[0] + ref[2])) / 2.0 / max(dw, rw)
    oy = ((det_bbox[1] + det_bbox[3]) - (ref[1] + ref[3])) / 2.0 / max(dh, rh)
    return (ox * ox + oy * oy) ** 0.5


def nearby_track(active, predicted, det, taken):
    """J6 · return the ACTIVE same-label track whose position estimate
    is within ``SPAWN_NEAR_DIST_FACTOR`` bbox dimensions of ``det``, or
    None. The closest candidate wins.

    Three gates hold it to the one case it is for — a track that lost
    its subject to a bad prediction:

    * ``taken`` carries the indices of tracks that already got a
      detection on this frame. They are NOT candidates: an orphan may
      only join a track that has nothing of its own, so two subjects
      standing close can never collapse onto one id.
    * same label, unlike the J2 block. Distance alone is too weak a
      signal to absorb a cross-label detection.
    * comparable HEIGHT (``SPAWN_NEAR_H_RATIO``) — the stable dimension
      of an upright subject. Width is not gated: widening is what the
      turn does.

    ``active`` and ``predicted`` must be index-aligned, so callers pass
    the tracks that existed at frame entry. A track spawned earlier in
    the same frame is not a candidate — it has no prediction, and
    adopting into it would merge two subjects that arrived together.
    """
    best_track = None
    best_dist = float(SPAWN_NEAR_DIST_FACTOR)
    for ti, tr in enumerate(active):
        if ti in taken or tr.label != det.label:
            continue
        last_tuple = last_observed_bbox(tr)
        if last_tuple is None:
            continue
        det_h = max(1.0, float(det.bbox[3] - det.bbox[1]))
        ref_h = max(1.0, float(last_tuple[3] - last_tuple[1]))
        if max(det_h, ref_h) / min(det_h, ref_h) > SPAWN_NEAR_H_RATIO:
            continue
        # Both the last observation and the prediction are plausible
        # positions for the subject; the detection only has to be near
        # ONE of them. On a reversal the last observation is the closer
        # of the two, which is precisely the case the prediction missed.
        refs = [last_tuple]
        if ti < len(predicted):
            refs.append(predicted[ti])
        dist = min(_axis_normalised_offset(det.bbox, ref) for ref in refs)
        if dist < best_dist:
            best_dist = dist
            best_track = tr
    return best_track


def spawn_blocking_track(active, predicted, det):
    """Return the ACTIVE track that overlaps ``det.bbox`` above
    ``SPAWN_BLOCK_IOU``, or None.

    Considers ALL labels — a cross-label hit indicates a
    misclassification of an already-tracked subject. Tests the
    detection against both the track's predicted bbox (already computed
    by the caller at frame entry, so index-aligned with ``active``) and
    its last OBSERVED bbox, and picks the highest IoU when several
    qualify.
    """
    best_track = None
    best_iou = SPAWN_BLOCK_IOU
    for ti, tr in enumerate(active):
        if not tr.samples:
            continue
        pred = predicted[ti] if ti < len(predicted) else None
        last_tuple = last_observed_bbox(tr) or _bbox_tuple(tr.samples[-1]["bbox"])
        iou_pred = iou(det.bbox, pred) if pred is not None else 0.0
        iou_last = iou(det.bbox, last_tuple)
        best_for_track = max(iou_pred, iou_last)
        if best_for_track > best_iou:
            best_iou = best_for_track
            best_track = tr
    return best_track


def try_reidentify(state, det, t_s: float):
    """Find the most recent CLOSED track that plausibly matches ``det``
    so an unmatched confirmed detection can RESUME the track instead of
    spawning a fresh id. Returns the candidate Track (still in
    ``state.closed`` — the caller moves it back to ``state.active``) or
    None.

    Match gates:
      * same label
      * closed within ``TRACK_REID_MAX_SECONDS`` of ``t_s``
      * centroid distance ≤ ``TRACK_REID_DIST_FACTOR × max(bw,bh)``
      * size ratio ≤ ``TRACK_REID_SIZE_RATIO``
      * (J4) the det's bbox does NOT overlap any ACTIVE track above
        REID_OCCUPIED_IOU — re-id only ever resumes into truly free
        space, never on top of a live track (which would create a
        parallel duplicate).

    Among candidates passing all gates, the closest in centroid
    distance wins.
    """
    closed = state.closed
    if not closed:
        return None
    bb = det.bbox
    # J4 · refuse re-id if ANY active track already occupies this
    # spot — the det should extend that live track via the spawn-
    # block path instead of resurrecting a parallel ghost.
    for tr in state.active:
        if not tr.samples:
            continue
        if iou(bb, _bbox_tuple(tr.samples[-1]["bbox"])) > REID_OCCUPIED_IOU:
            return None
    cx = (bb[0] + bb[2]) / 2.0
    cy = (bb[1] + bb[3]) / 2.0
    bw = max(1.0, float(bb[2] - bb[0]))
    bh = max(1.0, float(bb[3] - bb[1]))
    best = None
    best_dist = float("inf")
    # Scan the recently-closed window. Iterate over a bounded tail of
    # the closed list (newest closes first), then per-track filter on
    # last-sample t proximity. `continue` rather than `break` because
    # closed-order ≠ last_sample.t order — a track that closed late
    # after a long active span can have an older tail than one that
    # closed earlier with a fresher final sample.
    for tr in reversed(closed[-TRACK_REID_SCAN_DEPTH:]):
        if tr.label != det.label:
            continue
        if not tr.samples:
            continue
        last_t = float(tr.samples[-1].get("t", 0) or 0)
        if t_s - last_t > TRACK_REID_MAX_SECONDS:
            continue
        last_bb = tr.samples[-1]["bbox"]
        last_bw = max(1.0, float(last_bb["x2"] - last_bb["x1"]))
        last_bh = max(1.0, float(last_bb["y2"] - last_bb["y1"]))
        sz_ratio = max(bw, last_bw) / min(bw, last_bw)
        if sz_ratio > TRACK_REID_SIZE_RATIO:
            continue
        sz_ratio_h = max(bh, last_bh) / min(bh, last_bh)
        if sz_ratio_h > TRACK_REID_SIZE_RATIO:
            continue
        last_cx = (last_bb["x1"] + last_bb["x2"]) / 2.0
        last_cy = (last_bb["y1"] + last_bb["y2"]) / 2.0
        d = ((cx - last_cx) ** 2 + (cy - last_cy) ** 2) ** 0.5
        max_d = max(last_bw, last_bh) * TRACK_REID_DIST_FACTOR
        if d > max_d:
            continue
        if d < best_dist:
            best_dist = d
            best = tr
    return best
