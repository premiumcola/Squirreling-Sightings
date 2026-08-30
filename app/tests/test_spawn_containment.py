"""One person must stay one track when the detector boxes a part of them.

Reported from a walk-in test on the workshop camera: "it detected a
person just in my face, and me completely, in parallel — and when I
turned it got confused." The tracker events show it plainly: ids #3, #4,
#5 and #6, all `person`, all the same human.

The cause is a blind spot in the J2 spawn block, which compares by IoU.
A 120x120 face box inside a 400x900 body box is 100 % contained but
scores IoU 0.04 — nowhere near the 0.45 gate — so it spawned its own
track on a subject that already had one.

J2b adds a containment gate (intersection over the SMALLER box). The
separation is wide: a part-of-a-person box is ~1.0 contained, while two
people standing shoulder to shoulder reach ~0.05, so the new gate cannot
merge two genuine subjects.
"""

from __future__ import annotations

import pytest

from app.bbox_utils import containment, iou
from app.detect_setup import build_detection_setup
from app.tracker_core import LiveTracker, resolve_track_thresholds
from app.tracker_core._adopt import spawn_blocking_track
from app.tracker_core._consts import SPAWN_BLOCK_CONTAIN, SPAWN_BLOCK_IOU

BODY = (450, 80, 850, 980)
FACE = (500, 100, 620, 220)  # head only, fully inside BODY
TORSO = (470, 300, 830, 700)  # inside BODY
FAR = (1800, 100, 2000, 900)  # a different person entirely
# Half in, half out — 0.50 contained, IoU ~0.05. Sits BETWEEN a loosened
# and a tightened gate, which is what makes the knob observable.
HALF_IN = (750, 400, 950, 600)


class _Track:
    def __init__(self, bbox, label="person"):
        x1, y1, x2, y2 = bbox
        self.label = label
        self.active = True
        self.samples = [
            {"f": 1, "source": "detect", "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2}}
        ]


class _Det:
    def __init__(self, bbox, label="person"):
        self.bbox = bbox
        self.label = label


# ── the primitive ─────────────────────────────────────────────────────────


def test_containment_sees_what_iou_cannot():
    assert iou(FACE, BODY) < 0.10, "IoU is blind here — that is the whole point"
    assert containment(FACE, BODY) == pytest.approx(1.0)


def test_containment_is_symmetric_about_which_box_is_smaller():
    assert containment(FACE, BODY) == pytest.approx(containment(BODY, FACE))


def test_two_neighbours_are_not_contained():
    a, b = (0, 0, 200, 600), (190, 0, 390, 600)
    assert containment(a, b) < 0.10


def test_disjoint_boxes_are_zero():
    assert containment(BODY, FAR) == 0.0


def test_a_zero_area_box_does_not_divide_by_zero():
    assert containment((10, 10, 10, 10), BODY) == 0.0


# ── the gate ──────────────────────────────────────────────────────────────


def test_a_face_box_does_not_spawn_a_second_track():
    """THE regression test — this is what made one person into four."""
    tracks = [_Track(BODY)]
    assert spawn_blocking_track(tracks, [], _Det(FACE)) is tracks[0]


def test_a_torso_box_does_not_spawn_a_second_track():
    tracks = [_Track(BODY)]
    assert spawn_blocking_track(tracks, [], _Det(TORSO)) is tracks[0]


def test_a_genuinely_separate_person_still_spawns():
    """The gate must not merge two real subjects — otherwise a second
    intruder disappears into the first one's track."""
    tracks = [_Track(BODY)]
    assert spawn_blocking_track(tracks, [], _Det(FAR)) is None


def test_two_people_standing_shoulder_to_shoulder_stay_separate():
    tracks = [_Track((0, 0, 200, 600))]
    assert spawn_blocking_track(tracks, [], _Det((190, 0, 390, 600))) is None


def test_the_pre_existing_iou_gate_still_blocks_a_duplicate():
    """J2's original job — a near-identical duplicate box — is unchanged."""
    tracks = [_Track(BODY)]
    almost = (455, 85, 845, 975)
    assert iou(almost, BODY) > SPAWN_BLOCK_IOU
    assert spawn_blocking_track(tracks, [], _Det(almost)) is tracks[0]


def test_a_cross_label_box_inside_a_track_is_still_blocked():
    """A misclassification of an already-tracked subject — the SSD's
    occasional 'bird' on a person — must not raise a parallel track."""
    tracks = [_Track(BODY, label="person")]
    assert spawn_blocking_track(tracks, [], _Det(FACE, label="bird")) is tracks[0]


def test_the_predicted_box_is_considered_too():
    """A track mid-grace has only a prediction; containment against it
    must count, or the block fails exactly when the subject is hardest
    to follow."""
    tracks = [_Track(FAR)]
    assert spawn_blocking_track(tracks, [BODY], _Det(FACE)) is tracks[0]


def test_the_threshold_is_the_documented_one():
    assert SPAWN_BLOCK_CONTAIN == 0.70
    just_under = containment((450, 80, 850, 980), (450, 80, 850, 980))
    assert just_under > SPAWN_BLOCK_CONTAIN


# ── the knob (track_block_contain / "Doppel-Sperre") ──────────────────────
#
# The axis shipped wired through the UI, the PATCH route and the net_state
# payload — and read by nobody. resolve_track_thresholds returned a
# four-tuple that skipped it, no LiveTracker call site passed it, and
# LiveTracker.__slots__ did not even have room for it, so the one method
# that accepted the kwarg (configure) raised AttributeError. The operator
# moved a slider, the panel echoed the new value back as "effective", and
# the tracker kept using the module constant.


class _FakeDet:
    """associate_detections reads .label, .score and .bbox only."""

    def __init__(self, bbox, score=0.90, label="person"):
        self.bbox = bbox
        self.score = float(score)
        self.label = label


def _two_frames(block_contain: float) -> int:
    """Body alone, then body + a half-contained box. Returns the number
    of live tracks after the second frame."""
    tracker = LiveTracker("cam_contain", spawn_default=0.50, block_contain=block_contain)
    tracker.step([_FakeDet(BODY)], t_s=0.0, fps=1.0)
    tracker.step([_FakeDet(BODY), _FakeDet(HALF_IN)], t_s=1.0, fps=1.0)
    return tracker.active_count()


def test_the_half_contained_box_sits_between_the_two_gates():
    """Guards the fixture itself: if this geometry drifted, the two
    behaviour tests below would agree for the wrong reason."""
    assert containment(HALF_IN, BODY) == pytest.approx(0.50)
    assert iou(HALF_IN, BODY) < SPAWN_BLOCK_IOU


def test_the_camera_can_tighten_the_containment_gate():
    """The German hint promises "innen = streng zusammenfassen (Gesicht +
    Körper = eine Person)". At the shipped 0.70 a half-contained box is
    its own subject; tightened to 0.40 it folds into the track that
    already covers it. Both readings must be reachable from config."""
    assert _two_frames(SPAWN_BLOCK_CONTAIN) == 2
    assert _two_frames(0.40) == 1


def test_configure_accepts_the_containment_gate():
    """Raised AttributeError: 'LiveTracker' object has no attribute
    'block_contain' — __slots__ had no room for what configure() assigns.
    A latent crash on the live-apply path of the detection-tuning route."""
    tracker = LiveTracker("cam_contain")
    assert tracker.block_contain == SPAWN_BLOCK_CONTAIN
    tracker.configure(spawn_default=0.5, floor=0.3, grace_seconds=4.0, block_contain=0.42)
    assert tracker.block_contain == pytest.approx(0.42)


def test_configure_leaves_the_gate_alone_when_omitted():
    tracker = LiveTracker("cam_contain", block_contain=0.42)
    tracker.configure(spawn_default=0.5, floor=0.3, grace_seconds=4.0)
    assert tracker.block_contain == pytest.approx(0.42)


def test_the_resolver_reads_the_cameras_override():
    assert resolve_track_thresholds(lambda _c: {}, "cam").block_contain == SPAWN_BLOCK_CONTAIN
    cfg = {"track_block_contain": 0.42}
    assert resolve_track_thresholds(lambda _c: cfg, "cam").block_contain == pytest.approx(0.42)


def test_the_resolver_treats_zero_as_use_the_default():
    """schema.py's sentinel — a camera that never touched the slider
    stores 0.0 and must behave exactly as it did before the axis existed."""
    cfg = {"track_block_contain": 0.0}
    assert resolve_track_thresholds(lambda _c: cfg, "cam").block_contain == SPAWN_BLOCK_CONTAIN


def test_the_resolver_clamps_an_absurd_override():
    cfg = {"track_block_contain": 7.5}
    assert resolve_track_thresholds(lambda _c: cfg, "cam").block_contain == pytest.approx(1.0)


def test_both_detection_paths_carry_the_gate():
    """DetectionSetup is what the live loop AND the Simulieren panel build
    their tracker from — a value that stopped at the resolver would reach
    neither."""
    setup = build_detection_setup("cam", {"track_block_contain": 0.42})
    assert setup.block_contain == pytest.approx(0.42)
