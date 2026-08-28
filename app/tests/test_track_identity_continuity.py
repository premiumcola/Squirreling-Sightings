"""J6 · one subject keeps one track id across a direction reversal.

Measured on the live system (640 x 360 sub-stream, ~369 ms cadence, one
person alone in frame, pacing back and forth): **five person tracks and
five grace-expiry deaths inside 60 seconds**, each new id spawning while
the previous one was still alive:

    -8.8s   SPAWN #6 person      -3.5s   DEATH #5  grace expired
    -30.8s  SPAWN #5 person      -27.3s  DEATH #4  grace expired
    -44.8s  SPAWN #4 person      -39.5s  DEATH #3  grace expired

The arithmetic behind it, for a 44 x 140 px person box and a 38 px
walking step (~0.9 bbox WIDTHS per sample):

* IoU against the last observed box is ~0 on every single frame, so the
  velocity prediction is the only thing holding the track together.
* On a reversal the prediction points one step the WRONG way: predicted
  and actual sit ~2 steps (~1.7 box widths) apart, IoU 0.
* Matching needs IoU >= 0.20, which for equal boxes offset by d means
  d <= 0.67 w ~ 29 px — less than one step. The J2 spawn block needs
  IoU > 0.45, i.e. d <= 0.38 w ~ 17 px — STRICTER than the match it is
  supposed to backstop.

So the detection neither continues the track nor is blocked from
starting a new one, and the old track runs out its 16-sample grace
alone. These tests pin the fix (J6 proximity adoption) AND the two
properties it must not trade away: two subjects crossing keep separate
identities, and a genuinely new subject still gets its own id.

Style follows test_tracker_motion.py — same FakeDet stand-in, no
fixtures beyond the tracker state.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tracker_core import LiveTracker, Track, TrackerState  # noqa: E402
from app.tracker_core import associate_detections  # noqa: E402

# The measured scene: 640 x 360 sub-stream, ~369 ms between inferences.
FRAME_W = 640
FRAME_H = 360
CADENCE_S = 0.369
FPS = 1.0 / CADENCE_S
# Effective per-camera values at the time of the measurement.
SPAWN = 0.50
IOU_T = 0.20
GRACE_S = 6.0

# A person at that scale: tall, narrow, and covering ~0.9 of its own
# width between two samples.
BOX_H = 140
BOX_Y1 = 120
NARROW = 44  # walking, side-on
WIDE = 80  # mid-turn: both shoulders plus the swinging arm (1.8x)
STEP = 38


@dataclass
class FakeDet:
    """Minimal stand-in for Detection — the tracker only reads .label,
    .score and .bbox."""

    label: str
    score: float
    bbox: tuple[int, int, int, int]


def _person(x_centre: float, width: int = NARROW, *, y1: int = BOX_Y1, h: int = BOX_H):
    """Person bbox centred on ``x_centre``, clipped to the frame the way
    a real detector's output is."""
    half = width / 2.0
    x1 = max(0, min(FRAME_W, int(round(x_centre - half))))
    x2 = max(0, min(FRAME_W, int(round(x_centre + half))))
    return (x1, max(0, y1), x2, min(FRAME_H, y1 + h))


def _tracker() -> LiveTracker:
    return LiveTracker(
        camera_id="cam",
        spawn_default=SPAWN,
        floor=0.20,
        grace_seconds=GRACE_S,
        iou_threshold=IOU_T,
    )


def _step(tracker: LiveTracker, dets, frame_idx: int):
    return tracker.step(
        dets,
        t_s=frame_idx * CADENCE_S,
        fps=FPS,
        frame_w=FRAME_W,
        frame_h=FRAME_H,
    )


def _all_tracks(tracker: LiveTracker):
    return list(tracker.state.active) + list(tracker.state.closed)


def _detect_centres(track):
    return [
        (s["bbox"]["x1"] + s["bbox"]["x2"]) / 2.0 for s in track.samples if s["source"] == "detect"
    ]


def _turning_walk():
    """``[(x_centre, width), …]`` for a person pacing back and forth.

    Ten samples per leg at 38 px, and at each reversal a one-sample
    pivot in place where the box widens 44 -> 80 px (1.8x) as the body
    comes round. That factor is deliberately ABOVE the 1.7 size ratio
    the re-id and velocity-bootstrap gates allow, which is why neither
    of them can rescue the turn.
    """
    frames: list[tuple[float, int]] = []
    x, direction = 150.0, 1
    for leg in range(3):
        if leg:
            frames.append((x, WIDE))  # pivot in place
            direction = -direction
        for i in range(10):
            x += direction * STEP
            frames.append((x, WIDE if i == 0 else NARROW))
    return frames


# ── The reported symptom ───────────────────────────────────────────────────
def test_turning_walker_stays_one_track():
    """The actual bug: one person, two direction reversals, one id.

    Against the pre-J6 tracker this produced one extra track per turn —
    each spawning while the previous was still alive and dying of grace
    expiry ~6 s later, exactly the production pattern."""
    tracker = _tracker()
    walk = _turning_walk()
    for f, (x, w) in enumerate(walk):
        _step(tracker, [FakeDet("person", 0.70, _person(x, w))], f)

    tracks = _all_tracks(tracker)
    assert len(tracks) == 1, (
        f"one pacing person fragmented into {len(tracks)} tracks: "
        f"{[t.track_id for t in tracks]}"
    )
    tr = tracks[0]
    assert tr.active, "the surviving track must still be alive at the end of the walk"
    assert len(_detect_centres(tr)) == len(walk), "every frame should have landed on the same track"


def test_reversal_detection_extends_instead_of_spawning():
    """The arithmetic in isolation: a detection one step BEHIND the
    track (the subject turned around) overlaps neither the prediction
    (which moved one step ahead) nor the last observed box, yet it is
    unmistakably the same subject — 0.9 bbox widths away, same height."""
    state = TrackerState()
    for f in range(4):
        associate_detections(
            state,
            [FakeDet("person", 0.70, _person(200 + f * STEP))],
            frame_idx=f,
            t_s=f * CADENCE_S,
            frame_w=FRAME_W,
            frame_h=FRAME_H,
            spawn_score=SPAWN,
            iou_threshold=IOU_T,
            miss_grace_samples=16,
        )
    assert len(state.active) == 1
    track_id = state.active[0].track_id

    # Frame 4: the subject reversed. Prediction sits at 200+4*STEP,
    # the subject at 200+2*STEP — no overlap either way.
    associate_detections(
        state,
        [FakeDet("person", 0.70, _person(200 + 2 * STEP, WIDE))],
        frame_idx=4,
        t_s=4 * CADENCE_S,
        frame_w=FRAME_W,
        frame_h=FRAME_H,
        spawn_score=SPAWN,
        iou_threshold=IOU_T,
        miss_grace_samples=16,
    )
    assert len(state.active) == 1, "the reversal spawned a parallel track"
    assert state.active[0].track_id == track_id
    assert state.active[0].missed_windows == 0, "the adopted detection must clear the miss counter"


# ── The regression this must not cause ─────────────────────────────────────
def test_two_people_crossing_keep_separate_identities():
    """Two subjects walking towards each other on adjacent paths must
    keep two ids all the way through the crossing.

    Deliberately adversarial: the boxes reach IoU ~0.43 at closest
    approach — close enough that a careless distance-based matcher
    swaps them, just under the 0.5 per-label NMS gate so BOTH
    detections survive into the association pass."""
    tracker = _tracker()
    near_y1, near_h, near_w = 140, 150, 48  # closer to the camera
    far_y1, far_h, far_w = 110, 120, 40
    left_x, right_x = 120.0, 520.0
    step = 34
    for f in range(14):
        dets = [
            FakeDet("person", 0.72, _person(left_x + f * step, near_w, y1=near_y1, h=near_h)),
            FakeDet("person", 0.68, _person(right_x - f * step, far_w, y1=far_y1, h=far_h)),
        ]
        _step(tracker, dets, f)

    tracks = _all_tracks(tracker)
    assert len(tracks) == 2, f"two walkers produced {len(tracks)} tracks"
    for tr in tracks:
        centres = _detect_centres(tr)
        deltas = [b - a for a, b in zip(centres, centres[1:])]
        assert all(d > 0 for d in deltas) or all(
            d < 0 for d in deltas
        ), f"track {tr.track_id} reverses direction — identities were swapped: {centres}"
        assert len(centres) == 14, "each subject should keep every one of its own frames"


def test_two_people_pacing_side_by_side_stay_two_tracks():
    """Both halves of the bargain at once, over a minute of footage:
    two subjects, each reversing direction on its own rhythm, in
    adjacent lanes. Every turn is a chance to fragment (the bug) and
    every turn is a chance to be adopted by the neighbour's track (the
    regression). The answer has to be exactly two ids, one per lane."""
    tracker = _tracker()
    a_x, a_dir = 160.0, 1
    b_x, b_dir = 420.0, -1
    for f in range(60):
        if f and f % 11 == 0:
            a_dir = -a_dir
        if f and f % 13 == 0:
            b_dir = -b_dir
        a_x = max(60.0, min(300.0, a_x + a_dir * STEP))
        b_x = max(360.0, min(600.0, b_x + b_dir * STEP))
        _step(
            tracker,
            [
                FakeDet("person", 0.70, _person(a_x)),
                FakeDet("person", 0.70, _person(b_x, y1=130, h=150)),
            ],
            f,
        )

    tracks = _all_tracks(tracker)
    assert len(tracks) == 2, f"two pacing people produced {len(tracks)} tracks"
    lanes = sorted((min(c), max(c), len(c)) for c in (_detect_centres(t) for t in tracks))
    assert lanes[0][1] < lanes[1][0], f"the two lanes bled into each other: {lanes}"
    assert all(n == 60 for _lo, _hi, n in lanes), "each subject should keep every one of its frames"


def test_orphan_does_not_steal_a_track_that_already_matched():
    """A detection that found no track of its own may only be adopted
    by a track that is UNMATCHED on this frame. Without that guard two
    subjects standing close would collapse onto one id — and the second
    subject would never get a track at all."""
    state = TrackerState()
    kwargs = dict(
        frame_w=FRAME_W,
        frame_h=FRAME_H,
        spawn_score=SPAWN,
        iou_threshold=IOU_T,
        miss_grace_samples=16,
    )
    # Two people standing still, one bbox width apart.
    for f in range(4):
        associate_detections(
            state,
            [
                FakeDet("person", 0.70, _person(200)),
                FakeDet("person", 0.70, _person(200 + 2 * NARROW)),
            ],
            frame_idx=f,
            t_s=f * CADENCE_S,
            **kwargs,
        )
    assert len(state.active) == 2
    left = min(state.active, key=lambda t: t.samples[-1]["bbox"]["x1"])
    left_id = left.track_id
    n_before = len([s for s in left.samples if s["source"] == "detect"])

    # Frame 4: the left subject is detected where it stands (matches its
    # own track by IoU), and the right subject's detection lands close to
    # the LEFT track but nowhere near its own.
    associate_detections(
        state,
        [
            FakeDet("person", 0.70, _person(200)),
            FakeDet("person", 0.70, _person(200 + NARROW)),
        ],
        frame_idx=4,
        t_s=4 * CADENCE_S,
        **kwargs,
    )
    left_now = next(t for t in state.active + state.closed if t.track_id == left_id)
    n_after = len([s for s in left_now.samples if s["source"] == "detect"])
    assert n_after == n_before + 1, "the left track absorbed two detections in one frame"


def test_new_subject_entering_the_frame_spawns_its_own_track():
    """Proximity adoption is a bbox-scaled neighbourhood, not a
    free-for-all: a second person entering at the frame edge, and one
    standing three box widths away, both get their own id."""
    tracker = _tracker()
    for f in range(4):
        _step(tracker, [FakeDet("person", 0.70, _person(300 + f * STEP))], f)
    assert len(_all_tracks(tracker)) == 1

    walker_x = 300 + 4 * STEP
    _step(
        tracker,
        [
            FakeDet("person", 0.70, _person(walker_x)),
            FakeDet("person", 0.70, _person(24)),  # entering at the left edge
        ],
        4,
    )
    assert len(_all_tracks(tracker)) == 2, "a newcomer at the edge must get its own id"

    # Three box widths from the walker, on the side it came from — far
    # enough that it is a second subject, close enough that a sloppy
    # radius would swallow it.
    _step(
        tracker,
        [
            FakeDet("person", 0.70, _person(walker_x + STEP)),
            FakeDet("person", 0.70, _person(24 + STEP)),
            FakeDet("person", 0.70, _person(walker_x - 3 * NARROW)),
        ],
        5,
    )
    assert len(_all_tracks(tracker)) == 3, "a subject three box widths away is a second subject"


def test_subject_returning_after_the_reid_window_gets_a_new_track():
    """Someone who walks out of frame and comes back a quarter of a
    minute later is a fresh sighting — past TRACK_REID_MAX_SECONDS the
    closed track must not be revived, and no live track may adopt the
    detection either."""
    tracker = _tracker()
    # Walk out through the right edge — the last box the detector still
    # sees is a sliver against the frame boundary.
    x = 400.0
    f = 0
    while x - NARROW / 2 < FRAME_W - 4:
        _step(tracker, [FakeDet("person", 0.70, _person(x))], f)
        x += STEP
        f += 1
    # Empty frames until well past the 12 s re-id window.
    while f * CADENCE_S < 20.0:
        _step(tracker, [], f)
        f += 1
    assert not tracker.state.active, "the subject left the frame — its track should have closed"

    _step(tracker, [FakeDet("person", 0.70, _person(60))], f)
    tracks = _all_tracks(tracker)
    assert len(tracks) == 2, f"the return should be a fresh track, got {len(tracks)}"
    assert len(tracker.state.active) == 1


# ── The gate itself ────────────────────────────────────────────────────────
def test_adoption_reference_is_the_last_observation_not_the_prediction():
    """During the miss-grace window ``samples[-1]`` is a ``predicted``
    sample — the tracker's own extrapolation. The adoption gates have to
    read the last OBSERVED bbox, otherwise their only reference that is
    independent of the motion model disappears exactly when the motion
    model is what went wrong."""
    from app.tracker_core._adopt import last_observed_bbox

    tr = Track("t00001", "person", 0)
    obs = _person(200)
    tr.add_sample(
        0, 0.0, {"x1": obs[0], "y1": obs[1], "x2": obs[2], "y2": obs[3]}, 0.7, "detect", "person"
    )
    pred = _person(400)
    tr.add_sample(
        1, 0.4, {"x1": pred[0], "y1": pred[1], "x2": pred[2], "y2": pred[3]}, 0.5, "predicted"
    )
    assert last_observed_bbox(tr) == obs
