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
    """Containment >= IoU for any pair of boxes.

    True, and worth pinning — but it does NOT imply the gate fires less
    often, which an earlier version of this docstring claimed. That
    conclusion only holds at an unchanged threshold, and the threshold
    moved with the measure (IoU >= 0.30 became containment >= 0.50). See
    the counterexample below.
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


def test_the_new_gate_can_fire_where_the_old_one_did_not():
    """The counterexample to "this change cannot cost CPU".

    That claim was shipped in a code comment and enshrined by the
    docstring above. It rests on containment >= IoU, which is true — but
    the threshold moved with the measure, so the two gates are not
    comparable term by term. Two 50 px^2 boxes overlapping by 24 px^2:
    IoU = 24/76 = 0.32 cleared the old bar of 0.30, containment =
    24/50 = 0.48 misses the new bar of 0.50. The rescue fires here now
    and did not before.

    The band is narrow. It is not empty, and the cost of the change is
    bounded by the per-camera cooldown, not by an inequality that does
    not say what it was read to say.
    """
    from app.bbox_utils import iou
    from app.camera_runtime._main_loop import (
        _RESCUE_BLOB_CONTAINMENT,
        _blob_containment,
    )

    # Two equal-area boxes (50 px^2) offset so the overlap is 6 x 4 = 24.
    det = (0, 0, 10, 5)
    blob = (4, 1, 14, 6)
    inter_cont = _blob_containment(det, blob)
    inter_iou = iou(det, blob)

    assert abs(inter_cont - 0.48) < 0.01, f"containment was {inter_cont}"
    assert abs(inter_iou - 0.32) < 0.02, f"iou was {inter_iou}"
    # Old gate said "explained" (no rescue); the new one does not.
    assert inter_iou >= 0.30
    assert inter_cont < _RESCUE_BLOB_CONTAINMENT
