"""T1 · motion model for track association.

Production evidence (garden cam, evening light, ~350 ms cadence): ONE
distant person walking across a field produced ten person tracks in a
single clip, most of them one sample long. At that cadence a walking
subject moves further than its own bbox width between samples, so the
IoU of the new detection against the track's last known box is 0 — the
track never earns a second sample, never earns a velocity, ages out,
and the next frame spawns a fresh id.

These tests pin the two properties that break the loop: a track must
survive its FIRST frame without a velocity estimate, and once it has
one the prediction must actually reach the subject instead of stopping
a fraction of a bbox short.

Style follows test_tracker_core.py — same FakeDet stand-in, no fixtures
beyond the tracker state.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tracker_core import (  # noqa: E402
    Track,
    TrackerState,
    associate_detections,
    predicted_bbox,
)

# A distant person on a 2560 × 1440 main stream: narrow, tall, and
# covering more than its own width between two samples.
FRAME_W = 2560
FRAME_H = 1440
BOX_W = 40
BOX_H = 110
STEP_PX = 45  # > BOX_W — consecutive detections do not overlap at all


@dataclass
class FakeDet:
    """Minimal stand-in for Detection — associate_detections only reads
    .label, .score, .bbox."""

    label: str
    score: float
    bbox: tuple[int, int, int, int]


def _box(x: int, y: int, w: int = BOX_W, h: int = BOX_H):
    return (x, y, x + w, y + h)


def _step(state, dets, frame_idx):
    """One tracker frame at the live cadence (~350 ms per sample)."""
    return associate_detections(
        state,
        dets,
        frame_idx=frame_idx,
        t_s=frame_idx * 0.35,
        frame_w=FRAME_W,
        frame_h=FRAME_H,
        miss_grace_samples=8,
    )


def _all_tracks(state):
    return list(state.active) + list(state.closed)


def _seeded_track(positions, *, label="person"):
    """Build a Track carrying one detect sample per (frame, x, y)."""
    tr = Track("seed01", label, positions[0][0])
    for f, x, y in positions:
        bb = _box(x, y)
        tr.add_sample(
            f,
            f * 0.35,
            {"x1": bb[0], "y1": bb[1], "x2": bb[2], "y2": bb[3]},
            0.8,
            "detect",
            label,
        )
    return tr


# ── The reported symptom ───────────────────────────────────────────────────
def test_steady_walker_keeps_one_track():
    """A person walking at a constant speed across the field must stay
    ONE track id. Purely positional matching spawns a fresh id on every
    frame here (each detection clears the previous bbox entirely), which
    is the #1 … #10 fragmentation from the production screenshot."""
    state = TrackerState()
    y = 600
    for f in range(10):
        _step(state, [FakeDet("person", 0.80, _box(200 + f * STEP_PX, y))], f)

    tracks = _all_tracks(state)
    assert len(tracks) == 1, f"steady walker fragmented into {len(tracks)} tracks"
    tr = tracks[0]
    assert tr.active
    detects = [s for s in tr.samples if s["source"] == "detect"]
    assert len(detects) == 10, "every frame should have landed on the same track"
    assert detects[-1]["bbox"]["x1"] == 200 + 9 * STEP_PX


def test_fast_walker_prediction_reaches_the_subject():
    """The prediction must land ON the subject, not a fraction of a
    bbox short of it. With a step wider than the box, a displacement
    capped at 0.4 × bbox leaves the predicted box short of the real
    one and IoU never recovers."""
    tr = _seeded_track([(0, 200, 600), (1, 200 + STEP_PX, 600)])
    px1, _py1, px2, _py2 = predicted_bbox(tr, 2, frame_w=FRAME_W, frame_h=FRAME_H)
    truth_x1 = 200 + 2 * STEP_PX
    assert abs(px1 - truth_x1) <= 2, f"predicted x1={px1}, subject is at {truth_x1}"
    assert px2 - px1 == BOX_W, "prediction must keep the bbox size"


def test_walker_survives_a_short_occlusion():
    """Two frames without a detection (a shrub, a dark patch, a
    dropped inference) must not cost the walker its id — dead
    reckoning across a short gap is the whole point of predicting
    forward rather than holding the last box."""
    state = TrackerState()
    y = 600
    for f in range(14):
        dets = [] if f in (5, 6) else [FakeDet("person", 0.80, _box(300 + f * STEP_PX, y))]
        _step(state, dets, f)

    tracks = _all_tracks(state)
    assert len(tracks) == 1, f"occluded walker fragmented into {len(tracks)} tracks"
    assert len([s for s in tracks[0].samples if s["source"] == "detect"]) == 12


# ── No regression on the easy cases ────────────────────────────────────────
def test_stationary_subject_keeps_one_track():
    """A subject standing still (detector jitter only) must keep its
    single track — the motion model may never fling a static box away
    from where the next detection will be."""
    state = TrackerState()
    jitter = [0, 2, -1, 1, -2, 0, 1, -1, 2, 0]
    for f, dx in enumerate(jitter):
        _step(state, [FakeDet("person", 0.80, _box(900 + dx, 500 + dx))], f)

    tracks = _all_tracks(state)
    assert len(tracks) == 1, f"stationary subject fragmented into {len(tracks)} tracks"
    assert len([s for s in tracks[0].samples if s["source"] == "detect"]) == len(jitter)


def test_crossing_subjects_do_not_swap_identity():
    """Two people walking towards each other keep their own ids through
    the crossing — the prediction is what tells them apart while their
    boxes are adjacent."""
    state = TrackerState()
    y = 500
    left_x, right_x = 200, 700
    for f in range(10):
        dets = [
            FakeDet("person", 0.80, _box(left_x + f * STEP_PX, y)),
            FakeDet("person", 0.80, _box(right_x - f * STEP_PX, y)),
        ]
        _step(state, dets, f)

    tracks = _all_tracks(state)
    assert len(tracks) == 2, f"two walkers produced {len(tracks)} tracks"
    for tr in tracks:
        detects = [s for s in tr.samples if s["source"] == "detect"]
        xs = [s["bbox"]["x1"] for s in detects]
        # Each track must describe ONE consistent direction of travel —
        # a swapped identity shows up as a reversal mid-track.
        deltas = [b - a for a, b in zip(xs, xs[1:], strict=False)]
        assert all(d > 0 for d in deltas) or all(
            d < 0 for d in deltas
        ), f"track {tr.track_id} reverses direction: {xs}"
        assert len(detects) == 10


# ── Robustness ─────────────────────────────────────────────────────────────
def test_predictor_survives_degenerate_tracks():
    """No velocity signal must never raise: an empty track, a
    single-sample track, and two samples sharing a frame index (a zero
    time delta) all have to return a usable box."""
    empty = Track("empty1", "person", 0)
    assert predicted_bbox(empty, 5) == (0, 0, 0, 0)

    single = _seeded_track([(0, 300, 600)])
    assert predicted_bbox(single, 50) == _box(300, 600)
    assert predicted_bbox(single, 50, frame_w=FRAME_W, frame_h=FRAME_H) == _box(300, 600)

    # Two samples, SAME frame index — the per-frame divisor must not
    # divide by zero.
    same_frame = _seeded_track([(7, 300, 600), (7, 300 + STEP_PX, 600)])
    box = predicted_bbox(same_frame, 8, frame_w=FRAME_W, frame_h=FRAME_H)
    assert box[2] > box[0] and box[3] > box[1]


def test_prediction_never_leaves_the_frame():
    """A subject walking out of the right edge must not be predicted
    outside the image: an off-frame box is nonsense for IoU (the
    detector never emits one) and paints a stale box on the overlay."""
    x0 = FRAME_W - BOX_W - 10
    tr = _seeded_track([(0, x0 - STEP_PX, 1300), (1, x0, 1300)])
    for frame_idx in (2, 3, 6, 20):
        x1, y1, x2, y2 = predicted_bbox(tr, frame_idx, frame_w=FRAME_W, frame_h=FRAME_H)
        assert 0 <= x1 <= x2 <= FRAME_W, f"frame {frame_idx}: x span {x1}..{x2}"
        assert 0 <= y1 <= y2 <= FRAME_H, f"frame {frame_idx}: y span {y1}..{y2}"


def test_far_apart_detection_still_spawns_its_own_track():
    """The bootstrap gate is a one-frame bridge, not a free-for-all: a
    detection on the other side of the image may not be absorbed by a
    newborn track."""
    state = TrackerState()
    _step(state, [FakeDet("person", 0.80, _box(100, 200))], 0)
    _step(state, [FakeDet("person", 0.80, _box(1800, 900))], 1)
    assert len(_all_tracks(state)) == 2


# ── frame dimensions must reach the live path ─────────────────────────


def test_live_step_forwards_frame_dimensions():
    """Without these, the prediction clamp and the edge-grace rule both
    short-circuit on `0 == unknown`. They worked in the post-clip worker
    and were silently inert live, which is the worst kind of bug: the
    feature exists, its tests pass, and it never runs where it matters.
    """
    import inspect

    from app.tracker_core import LiveTracker

    sig = inspect.signature(LiveTracker.step)
    assert "frame_w" in sig.parameters
    assert "frame_h" in sig.parameters

    src = inspect.getsource(LiveTracker.step)
    assert "frame_w=frame_w" in src, "step must pass the width on to associate_detections"
    assert "frame_h=frame_h" in src


def test_camera_loop_supplies_the_frame_size():
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "app" / "camera_runtime" / "_main_loop.py"
    ).read_text(encoding="utf-8")
    call = src[src.index("self._tracker.step(") : src.index("self._tracker.step(") + 400]
    assert "frame_w=" in call and "frame_h=" in call


def test_prediction_is_clamped_when_dimensions_are_known():
    """End-to-end through LiveTracker rather than associate_detections,
    since that is the path the camera loop actually uses."""
    from app.tracker_core import LiveTracker

    tracker = LiveTracker(camera_id="c", spawn_default=0.5, iou_threshold=0.3)
    # Walk a subject rightwards towards the frame edge.
    x = 2300
    for _ in range(4):
        tracker.step(
            [FakeDet("person", 0.9, (x, 600, x + 60, 780))],
            t_s=0.0,
            fps=3.0,
            frame_w=2560,
            frame_h=1440,
        )
        x += 60

    for tr in tracker.state.active:
        bb = predicted_bbox(tr, tracker._frame_idx + 2, frame_w=2560, frame_h=1440)
        assert bb[2] <= 2560, f"prediction left the frame: {bb}"
        assert bb[0] >= 0
