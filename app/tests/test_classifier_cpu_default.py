"""Second-stage classifiers default to CPU, the detector does not.

An Edge TPU caches model parameters in ~8 MB of SRAM. The COCO detector,
the iNat bird classifier and the ImageNet wildlife classifier do not fit
there together, so every switch rewrites that cache over USB — and the
live loop switches twice inside a single wildlife frame (detect →
classify → refine bbox).

The detector runs every frame and keeps the TPU. The classifiers run
only on gated frames, so their per-call latency is cheap to trade for
keeping ONE model resident.
"""

from __future__ import annotations

import sys
import types

import pytest

from app.detectors.bird_species import BirdSpeciesClassifier
from app.detectors.coral_object import CoralObjectDetector
from app.detectors.wildlife import WildlifeClassifier


@pytest.fixture
def tflite_spy(monkeypatch, tmp_path):
    """Stub tflite_runtime and record whether the delegate was attempted."""
    calls = {"load_delegate": 0}
    interp_mod = types.ModuleType("tflite_runtime.interpreter")

    def _load_delegate(lib, options=None):
        calls["load_delegate"] += 1
        raise OSError("no edgetpu in test")

    class _Interp:
        def __init__(self, **kw):
            self.kw = kw

        def allocate_tensors(self):
            return None

    interp_mod.load_delegate = _load_delegate
    interp_mod.Interpreter = lambda **kw: _Interp(**kw)
    pkg = types.ModuleType("tflite_runtime")
    pkg.interpreter = interp_mod
    monkeypatch.setitem(sys.modules, "tflite_runtime", pkg)
    monkeypatch.setitem(sys.modules, "tflite_runtime.interpreter", interp_mod)
    monkeypatch.setitem(sys.modules, "pycoral", None)

    # Both classifiers stat the model path before choosing a tier.
    model = tmp_path / "m_edgetpu.tflite"
    model.write_bytes(b"stub")
    cpu_model = tmp_path / "m.tflite"
    cpu_model.write_bytes(b"stub")
    calls["model"] = str(model)
    calls["cpu_model"] = str(cpu_model)
    return calls


def test_bird_classifier_stays_off_the_tpu_by_default(tflite_spy):
    BirdSpeciesClassifier(
        {
            "enabled": True,
            "model_path": tflite_spy["model"],
            "cpu_model_path": tflite_spy["cpu_model"],
        }
    )
    assert tflite_spy["load_delegate"] == 0, "bird classifier must not claim the TPU by default"


def test_wildlife_classifier_stays_off_the_tpu_by_default(tflite_spy):
    WildlifeClassifier(
        {
            "enabled": True,
            "model_path": tflite_spy["model"],
            "cpu_model_path": tflite_spy["cpu_model"],
        }
    )
    assert tflite_spy["load_delegate"] == 0, "wildlife classifier must not claim the TPU by default"


def test_detector_still_claims_the_tpu(tflite_spy):
    """The inverse guard — the detector runs every frame and belongs there."""
    CoralObjectDetector(
        {
            "mode": "coral",
            "model_path": tflite_spy["model"],
            "cpu_model_path": tflite_spy["cpu_model"],
        }
    )
    assert tflite_spy["load_delegate"] > 0, "the detector must still try the TPU"


def test_classifier_can_be_put_back_on_the_tpu(tflite_spy):
    """The default must be an override, not a hard-coded decision."""
    WildlifeClassifier(
        {
            "enabled": True,
            "prefer_cpu": False,
            "model_path": tflite_spy["model"],
            "cpu_model_path": tflite_spy["cpu_model"],
        }
    )
    assert tflite_spy["load_delegate"] > 0
