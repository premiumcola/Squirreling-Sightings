"""SMALL-2 follow-up · the rescue gate measured overlap with the wrong metric.

`_confirmable_on_blob` asked "does a confirmable detection have IoU >= 0.3
with the coherent motion blob". A motion blob comes out of frame
differencing, so it covers only the part of the subject that MOVED — a
subset of the mover, routinely small and off-centre. IoU divides by the
UNION, which is dominated by the detection box, so a perfectly good
detection sitting right on top of the blob scored near zero and the gate
concluded "nothing explains this motion".

The gate's other defect — that it describes a STATE and so fired on every
frame of a crossing — is `test_small_rescue_cooldown.py`.

`_blob_containment` is imported inside the two tests that need it rather
than at module scope, so this file still COLLECTS against the pre-fix
source and the behavioural tests below report a real failed assertion
instead of everything dying at import.
"""

from __future__ import annotations

import pytest

from app.camera_runtime._main_loop import _confirmable_on_blob


class _Det:
    def __init__(self, label, score, bbox):
        self.label = label
        self.score = score
        self.bbox = bbox


class _Blob:
    """Stand-in for a MotionBlobTracker track — bbox is (x, y, w, h)."""

    def __init__(self, bbox=(1200, 700, 200, 160)):
        self.last_bbox = bbox
        self.net_displacement = 140.0
        self.straightness = 0.9


def _spawn(label):
    return {"person": 0.85, "cat": 0.80}.get(label, 0.55)


# ── the measure ───────────────────────────────────────────────────────


def test_a_blob_fully_inside_a_detection_is_fully_explained():
    """Containment is a subset test, so the answer here is exactly 1.0.

    The IoU of the same pair is 32 000 / 350 000 = 0.091 — well under the
    old 0.3 threshold, which is the bug in one line.
    """
    from app.bbox_utils import iou
    from app.camera_runtime._main_loop import _blob_containment

    person = (1000, 400, 1500, 1100)
    blob = (1200, 700, 1400, 860)

    assert _blob_containment(person, blob) == pytest.approx(1.0)
    assert iou(person, blob) == pytest.approx(0.0914, abs=1e-3)


def test_the_arm_case_the_old_iou_gate_got_backwards():
    """THE regression test. A person standing still and moving one arm.

    The blob covers the arm; the detection covers the whole person. The
    person IS the thing that moved, and a 0.90 person box is as confirmable
    as detections get — the rescue has nothing to add and must not fire.

    Against the old IoU-based gate this returns False (IoU = 0.076 < 0.3),
    the rescue fires, and the camera pays a magnified re-detect on CPU for
    a subject it had already identified.
    """
    arm_blob = _Blob((1180, 620, 80, 200))
    person = [_Det("person", 0.90, (1000, 400, 1300, 1100))]

    assert _confirmable_on_blob(person, arm_blob, _spawn) is True


def test_containment_never_undercuts_iou():
    """The property that makes this change safe to ship.

    Containment divides by the blob alone, IoU by the union, and the union
    is never smaller — so swapping the measure can only make the gate more
    willing to say "explained", i.e. can only REDUCE how often the rescue
    fires. The fix cannot cost CPU.
    """
    from app.bbox_utils import iou
    from app.camera_runtime._main_loop import _blob_containment

    blob = (1200, 700, 1400, 860)
    for det in [
        (1000, 400, 1300, 1100),
        (1200, 700, 1400, 860),
        (1380, 840, 1600, 1000),
        (1250, 720, 1350, 800),
        (0, 0, 2560, 1440),
    ]:
        assert _blob_containment(det, blob) >= iou(det, blob) - 1e-9


def test_a_detection_that_misses_the_blob_still_does_not_explain_it():
    """The counter-test — containment must not become a rubber stamp."""
    elsewhere = [_Det("person", 0.90, (100, 100, 400, 900))]

    assert _confirmable_on_blob(elsewhere, _Blob(), _spawn) is False


def test_a_weak_box_covering_the_blob_still_does_not_confirm_it():
    """Geometry is the second half of the test, never the whole of it.

    A 0.30 "cat" laid exactly over the blob is the squirrel-misread case;
    it must not be allowed to suppress the rescue on placement alone.
    """
    weak = [_Det("cat", 0.30, (1000, 400, 1600, 1100))]

    assert _confirmable_on_blob(weak, _Blob(), _spawn) is False
