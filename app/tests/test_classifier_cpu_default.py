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


# ── The iNat second-stage backend ─────────────────────────────────────────
#
# The fixture above pins `sys.modules["pycoral"] = None`, so tier 1 always
# raises there and every classifier lands on CPU no matter what the code
# does. That is faithful to the Python-3.11 image — and it is exactly why a
# missing prefer_cpu guard in _load_inat_backend stayed invisible for
# months. The moment the :coral image (Python 3.9, real pycoral) went live
# on 2026-08-28 the backend started claiming the TPU and evicting the
# object detector on every bird.
#
# These tests therefore supply a WORKING fake pycoral. Absence of a symptom
# under a stub that cannot exercise the path is not evidence of a guard.


@pytest.fixture
def pycoral_spy(monkeypatch, tmp_path):
    """A pycoral that imports and works, recording every TPU claim."""
    calls = {"make_interpreter": 0}

    class _Interp:
        def allocate_tensors(self):
            return None

    def _make_interpreter(path, device=None):
        calls["make_interpreter"] += 1
        return _Interp()

    edgetpu_mod = types.ModuleType("pycoral.utils.edgetpu")
    edgetpu_mod.make_interpreter = _make_interpreter
    utils_mod = types.ModuleType("pycoral.utils")
    utils_mod.edgetpu = edgetpu_mod
    adapters_mod = types.ModuleType("pycoral.adapters")
    adapters_mod.classify = types.ModuleType("pycoral.adapters.classify")
    adapters_mod.common = types.ModuleType("pycoral.adapters.common")
    pkg = types.ModuleType("pycoral")
    pkg.utils = utils_mod
    pkg.adapters = adapters_mod
    for name, mod in {
        "pycoral": pkg,
        "pycoral.utils": utils_mod,
        "pycoral.utils.edgetpu": edgetpu_mod,
        "pycoral.adapters": adapters_mod,
        "pycoral.adapters.classify": adapters_mod.classify,
        "pycoral.adapters.common": adapters_mod.common,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    interp_mod = types.ModuleType("tflite_runtime.interpreter")

    class _CpuInterp:
        def __init__(self, **kw):
            self.kw = kw

        def allocate_tensors(self):
            return None

    interp_mod.Interpreter = lambda **kw: _CpuInterp(**kw)
    interp_mod.load_delegate = lambda lib, options=None: (_ for _ in ()).throw(OSError("no tpu"))
    tfl = types.ModuleType("tflite_runtime")
    tfl.interpreter = interp_mod
    monkeypatch.setitem(sys.modules, "tflite_runtime", tfl)
    monkeypatch.setitem(sys.modules, "tflite_runtime.interpreter", interp_mod)

    model = tmp_path / "inat_edgetpu.tflite"
    model.write_bytes(b"stub")
    cpu_model = tmp_path / "inat.tflite"
    cpu_model.write_bytes(b"stub")
    calls["model"] = str(model)
    calls["cpu_model"] = str(cpu_model)
    return calls


def _inat_cfg(spy, **over):
    cfg = {"model_path": spy["model"], "cpu_model_path": spy["cpu_model"]}
    cfg.update(over)
    return cfg


def test_inat_backend_stays_off_the_tpu_even_when_pycoral_works(pycoral_spy):
    """THE regression test. Pre-fix this reached make_interpreter."""
    wc = WildlifeClassifier(
        {
            "enabled": True,
            "model_path": pycoral_spy["model"],
            "cpu_model_path": pycoral_spy["cpu_model"],
        },
        _inat_cfg(pycoral_spy),
    )
    assert pycoral_spy["make_interpreter"] == 0, (
        "the iNat backend must not evict the object detector from the TPU; "
        "it runs on gated crops, the detector runs on every frame"
    )
    assert wc._inat_cpu_mode is True


def test_inat_backend_can_be_put_back_on_the_tpu(pycoral_spy):
    """The default must be an override, not a hard-coded decision."""
    wc = WildlifeClassifier(
        {
            "enabled": True,
            "model_path": pycoral_spy["model"],
            "cpu_model_path": pycoral_spy["cpu_model"],
        },
        _inat_cfg(pycoral_spy, prefer_cpu=False),
    )
    assert wc is not None
    assert pycoral_spy["make_interpreter"] == 1
