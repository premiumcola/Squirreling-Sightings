"""SMALL-2 · the D2 rescue gate was too narrow to help the case it exists for.

The gate read, literally: fire the magnified re-detect when the full-frame
pass produced NO kept detections at all. `detections` at that point is past
the object filter, masks and zones but before the tracker — so a single
weak, wrong box was enough to make it non-empty and suppress the rescue
completely.

That is precisely what a small, distant subject produces. COCO has no
"squirrel"; a squirrel at a feeder comes back as "cat" at 0.30 — far under
any spawn threshold, useless to the tracker, and yet sufficient to cancel
the one mechanism that could have identified it. "Nothing at all" is the
wrong question; "nothing confirmable, on the thing that moved" is the right
one.
"""

from __future__ import annotations

import collections

import numpy as np
import pytest

from app.camera_runtime._rescue import RescueMixin as MainLoopMixin, _confirmable_on_blob


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


class _FakeDetector:
    def __init__(self, per_call=None):
        self.calls = []
        self._per_call = per_call or []

    def detect_frame_raw(self, frame, threshold=0.0):
        self.calls.append(frame.shape[:2])
        idx = len(self.calls) - 1
        if idx < len(self._per_call):
            return list(self._per_call[idx])
        return []


class _Tracker:
    floor = 0.20
    spawn_default = 0.55


class _Cam(MainLoopMixin):
    """Minimal MainLoopMixin host for the rescue path only."""

    camera_id = "cam_test"

    def __init__(self, detector, **cfg):
        self.cfg = {"roi_mode": "roi"}
        self.cfg.update(cfg)
        self.global_cfg = {"storage": {"root": None}}
        self.detector = detector
        self._tracker = _Tracker()
        self._roi_rescue_attempts = 0
        # Timestamp ring the real runtime carries (runtime.py) — the rescue
        # rate the telemetry projection reads is derived from it.
        self._roi_rescue_log = collections.deque(maxlen=64)
        self._roi_rescue_hits = 0

    def _filter_masked_detections(self, frame, dets):
        return dets

    def _filter_zoned_detections(self, frame, dets):
        return dets


def _spawn(label):
    return {"person": 0.80, "cat": 0.55}.get(label, 0.55)


@pytest.fixture
def frame():
    return np.zeros((1440, 2560, 3), dtype=np.uint8)


# ── the gate itself ───────────────────────────────────────────────────


def test_a_weak_wrong_box_no_longer_suppresses_the_rescue():
    """The acceptance case: one 0.30 "cat" nowhere near the blob.

    Under the old gate `detections` was non-empty, so the rescue was
    skipped and the squirrel was never magnified.
    """
    weak = [_Det("cat", 0.30, (100, 100, 260, 240))]

    assert _confirmable_on_blob(weak, _Blob(), _spawn) is False


def test_a_weak_box_ON_the_blob_still_does_not_confirm_it():
    """Being in the right place does not make 0.30 believable."""
    on_blob = [_Det("cat", 0.30, (1200, 700, 1400, 860))]

    assert _confirmable_on_blob(on_blob, _Blob(), _spawn) is False


def test_a_strong_detection_on_the_blob_suppresses_the_rescue():
    """The counter-test — the cost brake must still hold. A confirmable
    person standing on the blob explains the motion; magnifying it again
    buys nothing."""
    strong = [_Det("person", 0.90, (1200, 700, 1400, 860))]

    assert _confirmable_on_blob(strong, _Blob(), _spawn) is True


def test_a_strong_detection_ELSEWHERE_does_not_explain_the_blob():
    """A person on the terrace does not account for something moving at the
    feeder — the historic gate treated it as if it did."""
    elsewhere = [_Det("person", 0.90, (100, 100, 400, 900))]

    assert _confirmable_on_blob(elsewhere, _Blob(), _spawn) is False


def test_no_blob_means_no_rescue():
    """The coherent blob stays the precondition — that is the cost brake
    that keeps this off the per-frame path."""
    assert _confirmable_on_blob([], None, _spawn) is False


def test_partial_overlap_below_the_threshold_does_not_count():
    """A box clipping a corner of the blob is not an explanation of it."""
    grazing = [_Det("person", 0.90, (1380, 840, 1600, 1000))]

    assert _confirmable_on_blob(grazing, _Blob(), _spawn) is False


# ── the rescue body ───────────────────────────────────────────────────


def test_the_rescue_reuses_the_full_frame_pass_it_was_handed(frame):
    """One region inference, not one region plus a repeated full frame."""
    already = [_Det("cat", 0.30, (100, 100, 260, 240))]
    det = _FakeDetector()
    cam = _Cam(det)

    cam._roi_rescue(frame, already, _Blob(), "roi", allowed=set())

    assert len(det.calls) == 1, "the crop only"
    assert cam._roi_rescue_attempts == 1


def test_a_rescue_that_finds_nothing_new_is_not_counted_as_a_hit(frame):
    """With the wider gate the merged result can be non-empty simply
    because the weak box the loop already had survived the merge. Counting
    that as a hit would make roi_rescue_hits/attempts meaningless exactly
    when the widening starts to matter."""
    already = [_Det("cat", 0.30, (100, 100, 260, 240))]
    cam = _Cam(_FakeDetector())

    out = cam._roi_rescue(frame, already, _Blob(), "roi", allowed=set())

    assert cam._roi_rescue_attempts == 1
    assert cam._roi_rescue_hits == 0
    assert out == already, "and the weak box must survive, not be discarded"
    assert not hasattr(already[0], "via_roi"), "it did not come via the ROI"


def test_a_real_rescue_counts_and_is_marked_via_roi(frame):
    already = [_Det("cat", 0.30, (100, 100, 260, 240))]
    det = _FakeDetector(per_call=[[_Det("squirrel", 0.76, (20, 20, 120, 110))]])
    cam = _Cam(det)

    out = cam._roi_rescue(frame, already, _Blob(), "roi", allowed=set())

    gained = [d for d in out if getattr(d, "via_roi", False)]
    assert cam._roi_rescue_hits == 1
    assert [d.label for d in gained] == ["squirrel"]
    assert already[0] in out, "the merge keeps what the full frame had"


def test_the_object_filter_still_applies_to_rescued_boxes(frame):
    det = _FakeDetector(per_call=[[_Det("squirrel", 0.76, (20, 20, 120, 110))]])
    cam = _Cam(det)

    out = cam._roi_rescue(frame, [], _Blob(), "roi", allowed={"bird"})

    assert out == []
    assert cam._roi_rescue_hits == 0


# ── mode reading ──────────────────────────────────────────────────────


def test_an_unknown_roi_mode_falls_back_instead_of_disabling_silently(caplog):
    cam = _Cam(_FakeDetector(), roi_mode="ROI-only")

    with caplog.at_level("WARNING"):
        assert cam._effective_roi_mode() == "roi"

    assert "unknown roi_mode" in caplog.text


def test_the_fallback_warning_is_not_emitted_once_per_frame(caplog):
    cam = _Cam(_FakeDetector(), roi_mode="ROI-only")

    with caplog.at_level("WARNING"):
        for _ in range(50):
            cam._effective_roi_mode()

    assert caplog.text.count("unknown roi_mode") == 1


def test_off_stays_off():
    assert _Cam(_FakeDetector(), roi_mode="off")._effective_roi_mode() == "off"
    assert _Cam(_FakeDetector(), roi_mode=None)._effective_roi_mode() == "off"
