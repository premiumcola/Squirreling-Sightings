"""Per-stage inference timing.

`inference_avg_ms` wrapped four different costs in one number: frame
preparation, waiting on the interpreter lock, the inference itself, and
reading the output tensors back. A rising value could therefore mean the
TPU is loaded, or that another camera thread holds the lock, or merely
that letterboxing a 4-MP frame is expensive — three causes that want
opposite fixes. Splitting them is what makes any later TPU or hybrid
decision measurable rather than guessed.
"""

from __future__ import annotations

from app.detectors.coral_object import CoralObjectDetector


def _detector() -> CoralObjectDetector:
    # mode absent -> disabled, so __init__ returns before touching any
    # model file. The timing helpers are independent of that.
    return CoralObjectDetector({})


def test_breakdown_is_empty_before_any_inference():
    assert _detector().timing_breakdown() == {}


def test_breakdown_splits_the_four_stages():
    det = _detector()
    # t_pre .. t_wait = 10ms, wait = 20ms, invoke = 40ms, post = 5ms
    det._record_timing(0.000, 0.010, 0.030, 0.070)

    bd = det.timing_breakdown()
    assert bd["pre"] == 10.0
    assert bd["wait"] == 20.0
    assert bd["invoke"] == 40.0
    assert bd["samples"] == 1
    assert bd["post"] >= 0.0


def test_breakdown_averages_over_samples():
    det = _detector()
    det._record_timing(0.0, 0.010, 0.020, 0.030)  # pre 10, wait 10, invoke 10
    det._record_timing(0.0, 0.030, 0.060, 0.090)  # pre 30, wait 30, invoke 30

    bd = det.timing_breakdown()
    assert bd["pre"] == 20.0
    assert bd["wait"] == 20.0
    assert bd["invoke"] == 20.0
    assert bd["samples"] == 2


def test_total_is_the_sum_of_the_parts():
    det = _detector()
    det._record_timing(0.0, 0.005, 0.015, 0.045)

    bd = det.timing_breakdown()
    parts = bd["pre"] + bd["wait"] + bd["invoke"] + bd["post"]
    assert abs(bd["total"] - parts) < 0.2


def test_window_is_bounded():
    """Must not grow without limit in a process that runs for weeks."""
    det = _detector()
    for _ in range(500):
        det._record_timing(0.0, 0.001, 0.002, 0.003)

    assert det.timing_breakdown()["samples"] <= 60


def test_lock_contention_is_visible_separately():
    """The case the split exists for: slow because of waiting, not compute."""
    det = _detector()
    det._record_timing(0.0, 0.002, 0.200, 0.210)  # 198ms spent waiting

    bd = det.timing_breakdown()
    assert bd["wait"] > bd["invoke"], "contention must be attributable, not hidden in a total"
