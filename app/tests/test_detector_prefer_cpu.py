"""`prefer_cpu` must keep a detector off the Edge TPU.

Regression context: the tracking worker is documented to run on CPU so
it does not contend with the camera runtimes for the single USB TPU. It
enforced that by setting `device = None` only. That worked while tier 1
was pycoral (which has no Python 3.11 wheel and always failed), but once
the EdgeTPU *delegate* tier landed, `load_delegate` with no device option
simply took the default device — and the worker silently moved onto the
TPU it was written to avoid.

`prefer_cpu` makes the intent explicit instead of relying on a side
effect of the model filename or the device hint.
"""

from __future__ import annotations

import sys
import types

import pytest

from app.detectors.coral_object import CoralObjectDetector

EDGETPU_MODEL = "/app/models/coco_ssd_mobilenet_v2_coco_quant_postprocess_edgetpu.tflite"


class _FakeInterpreter:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def allocate_tensors(self):
        return None


@pytest.fixture
def fake_tflite(monkeypatch):
    """Install a stub tflite_runtime that records how it was called.

    `load_delegate` raises, standing in for "no TPU on this box" — the
    point of the test is which tier the code *attempts*, recorded in
    `calls`, not whether real hardware answers.
    """
    calls: dict = {"load_delegate": 0, "interpreter_kwargs": []}

    interp_mod = types.ModuleType("tflite_runtime.interpreter")

    def _load_delegate(lib, options=None):
        calls["load_delegate"] += 1
        raise OSError("no edgetpu device in test")

    def _interpreter(**kwargs):
        calls["interpreter_kwargs"].append(kwargs)
        return _FakeInterpreter(**kwargs)

    interp_mod.load_delegate = _load_delegate
    interp_mod.Interpreter = _interpreter

    pkg = types.ModuleType("tflite_runtime")
    pkg.interpreter = interp_mod
    monkeypatch.setitem(sys.modules, "tflite_runtime", pkg)
    monkeypatch.setitem(sys.modules, "tflite_runtime.interpreter", interp_mod)
    # Ensure pycoral is treated as absent so tier 1 fails the same way
    # it does in production on Python 3.11.
    monkeypatch.setitem(sys.modules, "pycoral", None)
    return calls


def _cfg(**over):
    base = {
        "mode": "coral",
        "model_path": EDGETPU_MODEL,
        "cpu_model_path": "/app/models/efficientdet_lite0.tflite",
        "labels_path": None,
    }
    base.update(over)
    return base


def test_prefer_cpu_never_attempts_the_delegate(fake_tflite):
    det = CoralObjectDetector(_cfg(prefer_cpu=True))
    assert fake_tflite["load_delegate"] == 0, "prefer_cpu must not touch the EdgeTPU delegate"
    assert det.mode == "cpu"
    assert det.reason == "cpu_requested"


def test_without_prefer_cpu_the_delegate_is_attempted(fake_tflite):
    """Guards the inverse: the normal path must still try the TPU."""
    CoralObjectDetector(_cfg())
    assert fake_tflite["load_delegate"] > 0


def test_cpu_threads_reaches_the_interpreter(fake_tflite):
    CoralObjectDetector(_cfg(prefer_cpu=True, cpu_threads=3))
    assert fake_tflite["interpreter_kwargs"], "no interpreter was constructed"
    assert fake_tflite["interpreter_kwargs"][0].get("num_threads") == 3


def test_cpu_threads_omitted_when_unset(fake_tflite):
    """Absent config must leave tflite's own default in place, not pass None."""
    CoralObjectDetector(_cfg(prefer_cpu=True))
    assert "num_threads" not in fake_tflite["interpreter_kwargs"][0]


def test_tracking_worker_requests_cpu():
    """The worker's config mutation must set the flag, not just device."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "app" / "tracking_worker" / "__init__.py"
    ).read_text(encoding="utf-8")
    assert 'worker_cfg["prefer_cpu"] = True' in src, (
        "tracking_worker must opt out of the TPU explicitly — nulling `device` "
        "alone lets the EdgeTPU delegate take the default device"
    )
