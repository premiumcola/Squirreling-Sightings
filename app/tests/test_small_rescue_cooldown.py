"""SMALL-2 follow-up · the rescue gate's preconditions are a STATE, not an event.

The gate fires when a coherent motion blob exists and nothing confirmable
explains it. Both halves stay true for as long as a subject is crossing the
scene — the second one ESPECIALLY so, because the case this whole path
exists for is "COCO has no squirrel and never will name it". So the gate
did not describe a moment, it described a condition lasting seconds, and
the rescue paid a magnified re-detect on every frame of it.

At the 150 ms frame interval that is ~400 extra region inferences per
minute of continuous coherent motion, on a CPU that is already the
bottleneck because the TPU does not compute. A per-camera cooldown bounds
it to ~40.

Note the counters are deliberately NOT changed: `roi_rescue_attempts`
increments inside `_roi_rescue`, so a frame the cooldown skips never
reaches it and the counter keeps meaning "inferences actually paid for",
which is how an operator reads it.
"""

from __future__ import annotations

import collections

import numpy as np
import pytest

from app.camera_runtime._main_loop import _RESCUE_MIN_INTERVAL_S, MainLoopMixin


class _Blob:
    def __init__(self, bbox=(1200, 700, 200, 160)):
        self.last_bbox = bbox
        self.net_displacement = 140.0
        self.straightness = 0.9


class _FakeDetector:
    def __init__(self):
        self.calls = 0

    def detect_frame_raw(self, frame, threshold=0.0):
        self.calls += 1
        return []


class _Tracker:
    floor = 0.20
    spawn_default = 0.55


class _Cam(MainLoopMixin):
    def __init__(self):
        self.camera_id = "cam_test"
        self.cfg = {"roi_mode": "roi"}
        self.global_cfg = {"storage": {"root": None}}
        self.detector = _FakeDetector()
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


@pytest.fixture
def cam():
    return _Cam()


@pytest.fixture
def frame():
    return np.zeros((720, 1280, 3), dtype=np.uint8)


def test_the_cooldown_leaves_room_for_the_confirmer_to_confirm():
    """The cooldown is bounded from ABOVE by the confirmation contract.

    `_loop` confirms a label at n=3 hits inside seconds=5.0. Whatever the
    cooldown is, it must let at least 3 rescue attempts land inside any 5 s
    window or a rescue-only subject can never be confirmed and the entire
    path becomes decorative. This pins the reasoning so a later "let's make
    it 3 seconds" cannot silently break confirmation.
    """
    attempts_in_window = int(5.0 // _RESCUE_MIN_INTERVAL_S) + 1

    assert attempts_in_window > 3, "cooldown starves the 3-of-5s confirmer"


def test_a_fresh_camera_may_rescue_immediately(cam):
    """No cooldown state yet must not mean "blocked" — the first coherent
    blob after a restart is exactly the one worth magnifying."""
    assert cam._rescue_cooldown_ready(1000.0) is True


def test_the_cooldown_blocks_the_very_next_frame(cam):
    """THE fire-rate regression test.

    At a 150 ms frame interval the frame right after a rescue satisfies
    both preconditions again, so the old code paid a second full re-detect
    — and another ~400 of them per minute after that.
    """
    cam._roi_rescue_last_ts = 1000.0

    assert cam._rescue_cooldown_ready(1000.15) is False


def test_the_cooldown_releases_once_the_interval_has_passed(cam):
    """The brake is a rate limit, not an off switch — a subject still in
    the scene has to get another look."""
    cam._roi_rescue_last_ts = 1000.0

    assert cam._rescue_cooldown_ready(1000.0 + _RESCUE_MIN_INTERVAL_S) is True


def test_the_cooldown_bounds_the_inference_rate(cam):
    """Turn the brake into the number the cost argument actually rests on.

    Replaying a minute of continuous coherent motion at the 150 ms frame
    interval: 400 attempts without the brake, ~40 with it. Asserted as a
    rate bound rather than an exact count because accumulating 0.15 s in
    binary floating point drifts the grant boundary by a frame or two —
    the guarantee is the ceiling, not a particular integer.
    """
    now, granted = 0.0, 0
    for _ in range(400):
        if cam._rescue_cooldown_ready(now):
            granted += 1
            cam._roi_rescue_last_ts = now
        now += 0.15

    ceiling = int(60.0 / _RESCUE_MIN_INTERVAL_S) + 1
    assert granted <= ceiling
    assert granted * 10 <= 400, "brake must be worth at least a 10x cut"


def test_the_rescue_still_pays_one_inference_per_attempt(cam, frame):
    """Baseline for the cost claim: an attempt is not free."""
    cam._roi_rescue(frame, [], _Blob(), "roi", allowed=set())

    assert cam.detector.calls == 1
    assert cam._roi_rescue_attempts == 1


def test_attempts_counts_inferences_not_frames(cam, frame):
    """`roi_rescue_attempts` must stay the number of re-detects actually
    paid for, so that a cooldown-skipped frame does not inflate it."""
    for _ in range(3):
        cam._roi_rescue(frame, [], _Blob(), "roi", allowed=set())

    assert cam._roi_rescue_attempts == cam.detector.calls == 3
    assert cam._roi_rescue_hits == 0
