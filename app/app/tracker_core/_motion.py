"""T1 · the tracker's motion model.

Association is otherwise purely positional: a detection matches a track
when its bbox overlaps the track's *predicted* bbox. Everything that
turns "last known position" into "where the subject should be NOW"
lives here, so the matcher in ``__init__`` stays a pairing algorithm.

Two pieces:

* :func:`predicted_bbox` — constant-velocity extrapolation of an
  established track (≥ 2 observed samples), clamped so a noisy
  velocity estimate cannot fling the box across the image and decayed
  as consecutive misses pile up.
* :func:`bootstrap_gate` / :func:`bootstrap_match_score` — the
  velocity BOOTSTRAP. A freshly spawned track has exactly one observed
  sample, so there is no velocity to extrapolate from; at a ~350 ms
  cadence a walking person moves further than its own bbox width
  between samples and IoU against the last known box is 0. Without a
  second sample the track never earns a velocity, ages out, and the
  next frame spawns a fresh id — the "#1 … #10 tracks on one walking
  person" fragmentation. For that ONE frame the gate matches on
  centroid distance instead, bounded by bbox size + a same-size check.

Cheap by construction: everything scans at most
``PRED_VELOCITY_WINDOW`` observed samples from the tail of the sample
list, so cost is O(active tracks) per frame regardless of how long a
track has been alive.
"""

from __future__ import annotations

from ..bbox_utils import bbox_centroid_dist
from ._consts import (
    BOOTSTRAP_DIST_FACTOR,
    BOOTSTRAP_MAX_ELAPSED,
    PRED_DECAY_CAP_SAMPLES,
    PRED_DECAY_FULL_SAMPLES,
    PRED_MAX_STEP_FRAC,
    PRED_MAX_TOTAL_FRAC,
    PRED_VELOCITY_WINDOW,
    STATIONARY_SPEED_FRAC,
    TRACK_REID_SIZE_RATIO,
)

# Sample sources that count as an OBSERVATION. "predicted" samples are
# the tracker's own extrapolation — feeding them back into the velocity
# estimate would let the prediction accelerate itself.
OBSERVED_SOURCES = ("detect", "track")


def recent_observed_samples(track, n: int) -> list[dict]:
    """Up to the last ``n`` observed samples, oldest → newest.

    Walks the sample list backwards and stops as soon as ``n`` are
    found, so an hours-old live track costs the same as a fresh one."""
    out: list[dict] = []
    for s in reversed(track.samples or []):
        if s.get("source") not in OBSERVED_SOURCES:
            continue
        out.append(s)
        if len(out) >= n:
            break
    out.reverse()
    return out


def velocity_estimate(track):
    """``(dx, dy, mean_speed, last_sample)`` in pixels per frame, or
    ``None`` when the track has fewer than two observed samples.

    ``dx``/``dy`` are the MEDIAN of the pairwise per-frame centroid
    deltas over the recent window — a median drowns the single reversal
    frame that a mean would follow. ``mean_speed`` is the mean
    magnitude of those deltas and feeds the stationary check.

    Frame gaps divide the delta so a sample pair straddling a miss
    still yields a per-frame velocity; the divisor is floored at 1 so
    two samples carrying the same frame index cannot divide by zero."""
    window = recent_observed_samples(track, PRED_VELOCITY_WINDOW)
    if len(window) < 2:
        return None
    dxs: list[float] = []
    dys: list[float] = []
    speed_sum = 0.0
    for i in range(1, len(window)):
        s_a, s_b = window[i - 1], window[i]
        bb_a, bb_b = s_a["bbox"], s_b["bbox"]
        df = max(1, int(s_b["f"]) - int(s_a["f"]))
        dx = ((bb_b["x1"] + bb_b["x2"]) - (bb_a["x1"] + bb_a["x2"])) / 2.0 / df
        dy = ((bb_b["y1"] + bb_b["y2"]) - (bb_a["y1"] + bb_a["y2"])) / 2.0 / df
        dxs.append(dx)
        dys.append(dy)
        speed_sum += (dx * dx + dy * dy) ** 0.5
    dxs.sort()
    dys.sort()
    return (dxs[len(dxs) // 2], dys[len(dys) // 2], speed_sum / len(dxs), window[-1])


def _miss_decay(elapsed: int) -> float:
    """Confidence in the velocity estimate ``elapsed`` frames after the
    last observation: 1.0 while the gap is short enough that the
    subject is almost certainly still walking (a dropped detection or
    a brief occlusion), then a linear ramp to 0.0 at
    ``PRED_DECAY_CAP_SAMPLES`` — past that
    the prediction stops extrapolating and holds the last observed
    position, which is the better guess for a subject that stopped or
    turned around behind cover."""
    if elapsed <= PRED_DECAY_FULL_SAMPLES:
        return 1.0
    span = float(max(1, PRED_DECAY_CAP_SAMPLES - PRED_DECAY_FULL_SAMPLES))
    return max(0.0, 1.0 - (elapsed - PRED_DECAY_FULL_SAMPLES) / span)


def _clip(box, frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
    """Clamp a box to the frame. The detector only ever emits boxes
    inside the frame, so an unclamped prediction at ``x2 = frame_w +
    200`` is not just visually wrong on the overlay — it inflates the
    union and drags IoU down against the very detection it should
    match. ``frame_w``/``frame_h`` of 0 means "dimensions unknown",
    and the box passes through untouched."""
    x1, y1, x2, y2 = (int(v) for v in box)
    if frame_w > 0:
        x1 = max(0, min(frame_w, x1))
        x2 = max(0, min(frame_w, x2))
    if frame_h > 0:
        y1 = max(0, min(frame_h, y1))
        y2 = max(0, min(frame_h, y2))
    return (x1, y1, x2, y2)


def predicted_bbox(
    track, frame_idx: int, *, frame_w: int = 0, frame_h: int = 0
) -> tuple[int, int, int, int]:
    """Where ``track``'s bbox should be at ``frame_idx``.

    Falls back to the last observed bbox when there is no usable motion
    signal — fewer than two observed samples, or a subject whose recent
    mean speed is below ``STATIONARY_SPEED_FRAC`` of its own bbox (a
    standing subject must be matched by position, never flung away by
    detector jitter).

    Otherwise the box travels ``velocity × elapsed × decay``, bounded
    three ways so a bad estimate stays harmless: the per-frame velocity
    is capped at ``PRED_MAX_STEP_FRAC`` bbox dimensions, the total
    displacement at ``PRED_MAX_TOTAL_FRAC``, and the result is clipped
    to the frame."""
    if not track.samples:
        return (0, 0, 0, 0)
    est = velocity_estimate(track)
    if est is None:
        bb = track.samples[-1]["bbox"]
        return _clip((bb["x1"], bb["y1"], bb["x2"], bb["y2"]), frame_w, frame_h)
    dx, dy, mean_speed, s_last = est
    bb = s_last["bbox"]
    last = (bb["x1"], bb["y1"], bb["x2"], bb["y2"])
    bw = max(1.0, float(bb["x2"] - bb["x1"]))
    bh = max(1.0, float(bb["y2"] - bb["y1"]))
    elapsed = max(0, frame_idx - int(s_last["f"]))
    if elapsed == 0 or mean_speed < STATIONARY_SPEED_FRAC * min(bw, bh):
        return _clip(last, frame_w, frame_h)
    decay = _miss_decay(elapsed)
    step_x = max(-PRED_MAX_STEP_FRAC * bw, min(PRED_MAX_STEP_FRAC * bw, dx))
    step_y = max(-PRED_MAX_STEP_FRAC * bh, min(PRED_MAX_STEP_FRAC * bh, dy))
    max_x = PRED_MAX_TOTAL_FRAC * bw
    max_y = PRED_MAX_TOTAL_FRAC * bh
    total_x = max(-max_x, min(max_x, step_x * elapsed * decay))
    total_y = max(-max_y, min(max_y, step_y * elapsed * decay))
    moved = (last[0] + total_x, last[1] + total_y, last[2] + total_x, last[3] + total_y)
    return _clip(moved, frame_w, frame_h)


def bootstrap_gate(track, frame_idx: int):
    """``(max_centroid_dist_px, last_observed_bbox)`` for a track that
    has exactly ONE observation and therefore no velocity yet, or
    ``None`` when the track doesn't qualify.

    Only open for ``BOOTSTRAP_MAX_ELAPSED`` frames after that single
    observation: this exists to get a second sample onto a newborn
    track, not to re-acquire a subject after a long gap (re-id and the
    miss-grace window own that case)."""
    window = recent_observed_samples(track, 2)
    if len(window) != 1:
        return None
    s = window[0]
    elapsed = frame_idx - int(s["f"])
    if elapsed < 1 or elapsed > BOOTSTRAP_MAX_ELAPSED:
        return None
    bb = s["bbox"]
    bw = max(1.0, float(bb["x2"] - bb["x1"]))
    bh = max(1.0, float(bb["y2"] - bb["y1"]))
    return (BOOTSTRAP_DIST_FACTOR * max(bw, bh) * elapsed, bb)


def bootstrap_match_score(gate, det_bbox) -> float | None:
    """Match strength in ``(0, 1]`` for a detection against a
    :func:`bootstrap_gate`, or ``None`` when it fails the gate.

    Distance-based, so it can bridge a step that carries the subject
    clear of its own last box — the exact case IoU cannot see. Two
    gates keep that from stealing a neighbour's detection: the same
    size class (``TRACK_REID_SIZE_RATIO``, as re-id uses) and a hard
    distance limit. Same-label is enforced by the caller."""
    limit, bb = gate
    dw = max(1.0, float(det_bbox[2] - det_bbox[0]))
    dh = max(1.0, float(det_bbox[3] - det_bbox[1]))
    bw = max(1.0, float(bb["x2"] - bb["x1"]))
    bh = max(1.0, float(bb["y2"] - bb["y1"]))
    if max(dw, bw) / min(dw, bw) > TRACK_REID_SIZE_RATIO:
        return None
    if max(dh, bh) / min(dh, bh) > TRACK_REID_SIZE_RATIO:
        return None
    dist = bbox_centroid_dist(
        bb,
        {"x1": det_bbox[0], "y1": det_bbox[1], "x2": det_bbox[2], "y2": det_bbox[3]},
    )
    if dist > limit:
        return None
    return 1.0 - dist / limit
