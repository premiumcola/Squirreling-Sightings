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
    det.wait_for_warmup()
    assert det.mode == "coral", det.reason
    assert det.interpreter.invokes >= 1, "interpreter was never invoked during construction"


def test_cpu_detector_is_warm_too(fake_tflite):
    det = CoralObjectDetector(_cfg(prefer_cpu=True))
    det.wait_for_warmup()
    assert det.mode == "cpu"
    assert det.interpreter.invokes >= 1


def test_the_first_real_detection_is_not_the_first_invoke(fake_tflite):
    """The point of the whole exercise, stated as behaviour."""
    det = CoralObjectDetector(_cfg())
    det.wait_for_warmup()
    warmed = det.interpreter.invokes
    det.detect_frame_raw(np.zeros((240, 320, 3), dtype=np.uint8), threshold=0.5)
    assert warmed >= 1
    assert det.interpreter.invokes == warmed + 1


def test_failed_tpu_warmup_falls_back_to_cpu(fake_tflite):
    """A failed warmup on the TPU is a failed TIER, not a slow frame.

    Observed on the real box: the delegate loaded, so the detector
    advertised mode="coral"/available=True, and then EVERY invoke raised
    "unresolved custom op … EdgeTpuDelegateForCustomOp failed to invoke".
    No detection ever survived, no motion event was built, and nothing
    downstream could tell "nothing moved" apart from "the detector is
    dead". Staying on a tier that cannot compute is worse than being
    slow, so we drop to the CPU twin of the same model.
    """
    fake_tflite["fail"] = True
    det = CoralObjectDetector(_cfg())
    det.wait_for_warmup()

    assert det.available is True, "falling back must not cost us the detector"
    assert det.mode == "cpu", "a TPU that cannot invoke must not keep claiming the TPU"
    assert "warmup failed" in det.reason


def test_cpu_warmup_failure_keeps_the_detector(fake_tflite):
    """On CPU there is nowhere left to fall, and a synthetic black frame
    is a weak reason to refuse real ones."""
    fake_tflite["fail"] = True
    det = CoralObjectDetector(_cfg(prefer_cpu=True))
    det.wait_for_warmup()

    assert det.available is True
    assert det.mode == "cpu"


def test_fallback_releases_the_tpu_lock(fake_tflite):
    """A CPU detector holding the process-wide TPU lock would serialise
    itself against the other cameras for no reason at all."""
    from app.detectors._device_lock import inference_lock

    fake_tflite["fail"] = True
    det = CoralObjectDetector(_cfg())
    det.wait_for_warmup()

    assert det._infer_lock is not inference_lock("coral", det.device)


def test_warmup_is_excluded_from_the_timing_window(fake_tflite):
    """The cold invoke is not a sample of steady-state latency. Leaving
    it in the 60-frame window would inflate the average — and, worse,
    show up in wait_p95 as a stall that never happened."""
    det = CoralObjectDetector(_cfg())
    det.wait_for_warmup()
    assert det.timing_breakdown() == {}, "warmup polluted the rolling timings"


def test_disabled_detector_runs_no_warmup(fake_tflite):
    """No model, no tier, nothing to warm — and nothing to crash on."""
    det = CoralObjectDetector({})
    det.wait_for_warmup()
    assert det.available is False
    assert det.interpreter is None


def test_unavailable_detector_runs_no_warmup(fake_tflite, monkeypatch):
    """Every tier failed: warmup must not be attempted on a None
    interpreter."""

    def _boom(**kwargs):
        raise OSError("no interpreter anywhere")

    sys.modules["tflite_runtime.interpreter"].Interpreter = _boom
    det = CoralObjectDetector(_cfg())
    det.wait_for_warmup()
    assert det.available is False
    assert det.interpreter is None


def test_warmup_never_blocks_the_constructing_thread(fake_tflite, monkeypatch):
    """Construction happens on Flask request threads and the bot thread.

    rebuild_runtimes / restart_single_camera are reached from the camera
    save, the wizard, settings import, /api/reload, the Coral test panel
    and a Telegram button. Since the device lock became process-wide, a
    synchronous warmup would park those threads behind whatever is on the
    TPU — including the model-switch route, which is the escape hatch
    from a wedged stick. So __init__ must return without waiting.
    """
    import threading
    import time as _time

    from app.detectors import coral_object as mod

    release = threading.Event()
    original = mod.CoralObjectDetector._warmup

    def _slow_warmup(self):
        release.wait(5.0)
        return original(self)

    monkeypatch.setattr(mod.CoralObjectDetector, "_warmup", _slow_warmup)

    started = _time.perf_counter()
    det = mod.CoralObjectDetector(_cfg())
    elapsed = _time.perf_counter() - started
    release.set()

    assert elapsed < 1.0, (
        f"__init__ blocked {elapsed:.2f}s on the warmup — a request thread "
        "would hang behind the device lock"
    )
    assert det.wait_for_warmup(timeout=5.0)


def test_warmup_runs_off_the_main_thread(fake_tflite):
    """Belt and braces: the thread must actually exist and be a daemon,
    so a stuck warmup can never keep the process alive at shutdown."""
    det = CoralObjectDetector(_cfg())
    thread = det._warmup_thread
    assert thread.daemon is True
    assert det.wait_for_warmup()
