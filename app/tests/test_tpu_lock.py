"""One physical Edge TPU must be guarded by ONE lock, process-wide.

Regression context: `_infer_lock` was created in
`CoralObjectDetector.__init__`, so it was a per-INSTANCE lock — and
`camera_runtime/runtime.py` builds one detector per camera. Three
cameras meant three detectors, three separate locks, and therefore no
mechanism at all serialising access to the single USB stick. The
libedgetpu driver serialises anyway, invisibly, which is exactly the
problem: the cost showed up as inflated `invoke` time instead of as
`wait`, so the per-stage timing split introduced for tuning measured
the wrong thing and contention was undiagnosable.

The inverse matters just as much. The second-stage classifiers were
deliberately moved to the CPU so they run CONCURRENTLY with the TPU
detector. A lock coarse enough to catch them too would hand that
throughput straight back, so the CPU tier must keep a per-instance
lock — it only needs to protect one interpreter against its own
re-entry (runtime loop vs. the simulate-now endpoint).
"""

from __future__ import annotations

import sys
import threading
import time
import types

import numpy as np
import pytest

from app.detectors.coral_object import CoralObjectDetector

EDGETPU_MODEL = "/app/models/coco_ssd_mobilenet_v2_coco_quant_postprocess_edgetpu.tflite"
CPU_MODEL = "/app/models/efficientdet_lite0.tflite"


class _ConcurrencyTracker:
    """Records the maximum number of threads inside invoke() at once."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self.current = 0
        self.peak = 0

    def enter(self) -> None:
        with self._guard:
            self.current += 1
            self.peak = max(self.peak, self.current)

    def leave(self) -> None:
        with self._guard:
            self.current -= 1


class _FakeInterpreter:
    """Enough of the tflite Interpreter API for `_detect_cpu` to run."""

    def __init__(self, tracker: _ConcurrencyTracker | None = None, hold: float = 0.0):
        self._tracker = tracker
        self._hold = hold
        self.invokes = 0

    def allocate_tensors(self):
        return None

    def get_input_details(self):
        return [{"shape": np.array([1, 300, 300, 3]), "index": 0, "dtype": np.uint8}]

    def get_output_details(self):
        return [{"index": i, "dtype": np.float32} for i in range(1, 5)]

    def set_tensor(self, index, value):
        return None

    def invoke(self):
        self.invokes += 1
        if self._tracker is not None:
            self._tracker.enter()
        if self._hold:
            time.sleep(self._hold)
        if self._tracker is not None:
            self._tracker.leave()

    def get_tensor(self, index):
        if index == 1:  # boxes
            return np.zeros((1, 5, 4), dtype=np.float32)
        return np.zeros((1, 5), dtype=np.float32)


@pytest.fixture
def fake_tflite(monkeypatch):
    """tflite_runtime stub whose EdgeTPU delegate SUCCEEDS.

    `test_detector_prefer_cpu` stubs the opposite case (no stick
    present). Here the delegate has to load, because the whole point is
    which lock a detector picks once it is genuinely on the TPU.
    """
    made: list[_FakeInterpreter] = []
    state: dict = {"tracker": None, "hold": 0.0}

    interp_mod = types.ModuleType("tflite_runtime.interpreter")

    def _load_delegate(lib, options=None):
        if lib != "libedgetpu.so.1":
            raise OSError(f"no such delegate library: {lib}")
        return object()

    def _interpreter(**kwargs):
        interp = _FakeInterpreter(state["tracker"], state["hold"])
        made.append(interp)
        return interp

    interp_mod.load_delegate = _load_delegate
    interp_mod.Interpreter = _interpreter

    pkg = types.ModuleType("tflite_runtime")
    pkg.interpreter = interp_mod
    monkeypatch.setitem(sys.modules, "tflite_runtime", pkg)
    monkeypatch.setitem(sys.modules, "tflite_runtime.interpreter", interp_mod)
    monkeypatch.setitem(sys.modules, "pycoral", None)
    state["made"] = made
    return state


def _cfg(**over):
    base = {
        "mode": "coral",
        "model_path": EDGETPU_MODEL,
        "cpu_model_path": CPU_MODEL,
        "labels_path": None,
    }
    base.update(over)
    return base


def _tpu_detector(fake_tflite, device="usb:0"):
    det = CoralObjectDetector(_cfg(device=device))
    assert det.mode == "coral", f"fixture did not reach the TPU tier: {det.reason}"
    return det


# ── identity of the lock ───────────────────────────────────────────────


def test_two_tpu_detectors_share_one_lock(fake_tflite):
    """Two cameras, one stick — the same lock object."""
    a = _tpu_detector(fake_tflite)
    b = _tpu_detector(fake_tflite)
    assert a._infer_lock is b._infer_lock


def test_two_cpu_detectors_keep_separate_locks(fake_tflite):
    """CPU interpreters must NOT be serialised against each other."""
    a = CoralObjectDetector(_cfg(prefer_cpu=True))
    b = CoralObjectDetector(_cfg(prefer_cpu=True))
    assert a.mode == "cpu" and b.mode == "cpu"
    assert a._infer_lock is not b._infer_lock


def test_cpu_stage_is_not_serialised_against_the_tpu(fake_tflite):
    """The reason the classifiers were moved off the TPU at all: a CPU
    stage has to keep running while the detector holds the device."""
    tpu = _tpu_detector(fake_tflite)
    cpu = CoralObjectDetector(_cfg(prefer_cpu=True))
    assert cpu.mode == "cpu"
    assert tpu._infer_lock is not cpu._infer_lock


def test_distinct_devices_get_distinct_locks(fake_tflite):
    """Two sticks are two devices — over-serialising them would throw
    away half the throughput they were bought for."""
    a = _tpu_detector(fake_tflite, device="usb:0")
    b = _tpu_detector(fake_tflite, device="usb:1")
    assert a._infer_lock is not b._infer_lock


def test_unspecified_device_is_one_key(fake_tflite):
    """`device: None` means "the default stick" for every caller, so two
    detectors that both leave it unset must land on the same lock."""
    a = _tpu_detector(fake_tflite, device=None)
    b = _tpu_detector(fake_tflite, device="")
    assert a._infer_lock is b._infer_lock


# ── the behaviour the identity is there for ────────────────────────────


def _run_concurrently(detectors, frame):
    threads = [
        threading.Thread(target=lambda d=d: d.detect_frame_raw(frame, threshold=0.9))
        for d in detectors
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)


def test_tpu_invokes_never_overlap(fake_tflite):
    """Two per-camera detectors on one stick must not be inside invoke()
    at the same time."""
    tracker = _ConcurrencyTracker()
    fake_tflite["tracker"] = tracker
    fake_tflite["hold"] = 0.05
    dets = [_tpu_detector(fake_tflite) for _ in range(3)]
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    _run_concurrently(dets, frame)
    assert tracker.peak == 1, f"{tracker.peak} concurrent EdgeTPU invokes — the device is one"


def test_cpu_invokes_are_allowed_to_overlap(fake_tflite):
    """Mirror image: CPU interpreters SHOULD run in parallel."""
    tracker = _ConcurrencyTracker()
    fake_tflite["tracker"] = tracker
    fake_tflite["hold"] = 0.05
    dets = [CoralObjectDetector(_cfg(prefer_cpu=True)) for _ in range(3)]
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    _run_concurrently(dets, frame)
    assert tracker.peak > 1, "CPU stages were serialised — that is the throughput we moved them for"


# ── the timing split has to see the contention ─────────────────────────


def test_wait_bucket_records_tpu_contention(fake_tflite):
    """The whole point of the shared lock is that queueing becomes
    visible in `wait` instead of hiding inside the driver."""
    fake_tflite["hold"] = 0.05
    dets = [_tpu_detector(fake_tflite) for _ in range(3)]
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    _run_concurrently(dets, frame)
    waits = [d.timing_breakdown().get("wait", 0.0) for d in dets]
    assert max(waits) > 10.0, f"contention invisible in the wait bucket: {waits}"


def test_wait_p95_is_reported(fake_tflite):
    """An average hides the stall that actually drops frames."""
    det = CoralObjectDetector(_cfg(prefer_cpu=True))
    det._record_timing(0.0, 0.001, 0.002, 0.003)
    det._record_timing(0.0, 0.001, 0.200, 0.201)
    bd = det.timing_breakdown()
    assert "wait_p95" in bd
    assert bd["wait_p95"] >= bd["wait"]
