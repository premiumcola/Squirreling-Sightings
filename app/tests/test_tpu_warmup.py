"""The first invoke on a fresh interpreter is the expensive one.

An Edge TPU caches model parameters in on-chip SRAM, and that cache is
filled on the first invoke — the weights cross USB before any inference
happens. Nothing warmed the interpreter up, so that cost was paid by the
first REAL frame: the first motion event after every restart (and after
every settings save, which rebuilds the runtimes) ran against a cold
device. It is also the frame most likely to matter, because something
just moved.

The CPU tier has a smaller version of the same problem — first-call
allocation and lazily-resolved kernels.

Warmup must be strictly optional, though. A detector that cannot run a
throwaway frame is not necessarily a detector that cannot run a real
one, and refusing to come up because a warmup failed would turn a
latency optimisation into an outage.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from app.detectors.coral_object import CoralObjectDetector

EDGETPU_MODEL = "/app/models/coco_ssd_mobilenet_v2_coco_quant_postprocess_edgetpu.tflite"
CPU_MODEL = "/app/models/efficientdet_lite0.tflite"


class _CountingInterpreter:
    """tflite Interpreter stub that counts invokes and can fail on cue."""

    def __init__(self, fail: bool = False):
        self.invokes = 0
        self._fail = fail
        self.warm_cost_s = 0.0

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
        if self._fail:
            raise RuntimeError("cold interpreter refused the throwaway frame")

    def get_tensor(self, index):
        if index == 1:
            return np.zeros((1, 5, 4), dtype=np.float32)
        return np.zeros((1, 5), dtype=np.float32)


@pytest.fixture
def fake_tflite(monkeypatch):
    state: dict = {"fail": False, "made": []}

    interp_mod = types.ModuleType("tflite_runtime.interpreter")

    def _load_delegate(lib, options=None):
        if lib != "libedgetpu.so.1":
            raise OSError(f"no such delegate library: {lib}")
        return object()

    def _interpreter(**kwargs):
        interp = _CountingInterpreter(fail=state["fail"])
        state["made"].append(interp)
        return interp

    interp_mod.load_delegate = _load_delegate
    interp_mod.Interpreter = _interpreter

    pkg = types.ModuleType("tflite_runtime")
    pkg.interpreter = interp_mod
    monkeypatch.setitem(sys.modules, "tflite_runtime", pkg)
    monkeypatch.setitem(sys.modules, "tflite_runtime.interpreter", interp_mod)
    monkeypatch.setitem(sys.modules, "pycoral", None)
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


def test_tpu_detector_is_warm_before_the_first_frame(fake_tflite):
    det = CoralObjectDetector(_cfg())
    assert det.mode == "coral", det.reason
    assert det.interpreter.invokes >= 1, "interpreter was never invoked during construction"


def test_cpu_detector_is_warm_too(fake_tflite):
    det = CoralObjectDetector(_cfg(prefer_cpu=True))
    assert det.mode == "cpu"
    assert det.interpreter.invokes >= 1


def test_the_first_real_detection_is_not_the_first_invoke(fake_tflite):
    """The point of the whole exercise, stated as behaviour."""
    det = CoralObjectDetector(_cfg())
    warmed = det.interpreter.invokes
    det.detect_frame_raw(np.zeros((240, 320, 3), dtype=np.uint8), threshold=0.5)
    assert warmed >= 1
    assert det.interpreter.invokes == warmed + 1


def test_warmup_failure_leaves_the_detector_available(fake_tflite):
    """A throwaway frame that fails must not cost us the detector."""
    fake_tflite["fail"] = True
    det = CoralObjectDetector(_cfg())
    assert det.available is True
    assert det.mode == "coral"
    assert det.reason == "edgetpu_delegate"


def test_warmup_is_excluded_from_the_timing_window(fake_tflite):
    """The cold invoke is not a sample of steady-state latency. Leaving
    it in the 60-frame window would inflate the average — and, worse,
    show up in wait_p95 as a stall that never happened."""
    det = CoralObjectDetector(_cfg())
    assert det.timing_breakdown() == {}, "warmup polluted the rolling timings"


def test_disabled_detector_runs_no_warmup(fake_tflite):
    """No model, no tier, nothing to warm — and nothing to crash on."""
    det = CoralObjectDetector({})
    assert det.available is False
    assert det.interpreter is None


def test_unavailable_detector_runs_no_warmup(fake_tflite, monkeypatch):
    """Every tier failed: warmup must not be attempted on a None
    interpreter."""

    def _boom(**kwargs):
        raise OSError("no interpreter anywhere")

    sys.modules["tflite_runtime.interpreter"].Interpreter = _boom
    det = CoralObjectDetector(_cfg())
    assert det.available is False
    assert det.interpreter is None
