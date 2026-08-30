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
from app.tracker_core._adopt import spawn_blocking_track
from app.tracker_core._consts import SPAWN_BLOCK_CONTAIN, SPAWN_BLOCK_IOU

BODY = (450, 80, 850, 980)
FACE = (500, 100, 620, 220)  # head only, fully inside BODY
TORSO = (470, 300, 830, 700)  # inside BODY
FAR = (1800, 100, 2000, 900)  # a different person entirely


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
