"""Characterisation tests for `WildlifeClassifier` — the second-stage
mammal classifier, which had no test of its own.

`test_wildlife_stage.py` covers the camera_runtime STAGE that calls it;
nothing exercised the classifier itself. Nothing imported
`classify_crop` or `_top3_*` at all before this file, so the five-step
decision ladder, the uint8 dequantisation and the 1000/1001 label offset
were all unpinned.

These tests describe what the code does TODAY. They are the safety net
for splitting the module, not a judgement on the thresholds — where the
current behaviour is arguably wrong, the test says so in its name rather
than quietly asserting the wrong thing is right.

No TFLite, no Coral, no model file: a fake interpreter stands in for
both backends, exactly as the rest of this suite stubs hardware.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.detectors.wildlife import WILDLIFE_MIN_SCORE_DEFAULT, WildlifeClassifier  # noqa: E402


class FakeInterpreter:
    """The slice of the tflite Interpreter surface the CPU paths touch."""

    def __init__(self, scores, *, out_dtype=np.float32, quantization=(0.0, 0), in_dtype=np.uint8):
        self._scores = np.asarray(scores)
        self._out_dtype = out_dtype
        self._quantization = quantization
        self._in_dtype = in_dtype
        self.invoked = 0
        self.last_input = None

    def get_input_details(self):
        return [{"shape": [1, 8, 8, 3], "dtype": self._in_dtype, "index": 0}]

    def get_output_details(self):
        return [
            {"index": 1, "dtype": self._out_dtype, "quantization": self._quantization},
        ]

    def set_tensor(self, index, value):
        self.last_input = value

    def invoke(self):
        self.invoked += 1

    def get_tensor(self, index):
        return np.asarray([self._scores])


def _classifier(**over):
    """A classifier whose __init__ ran for real but loaded no model.

    `enabled: False` returns from __init__ after every base field is
    set, which is precisely the state these tests then arm by hand.
    """
    cfg = {"enabled": False}
    cfg.update(over)
    return WildlifeClassifier(cfg)


def _armed(scores, labels, *, min_score=0.35, **interp):
    wc = _classifier(min_score=min_score)
    wc.available = True
    wc._cpu_mode = True
    wc.interpreter = FakeInterpreter(scores, **interp)
    wc.labels = labels
    return wc


def _arm_inat(wc, scores, labels, *, min_score=0.25, **interp):
    wc._inat_interpreter = FakeInterpreter(scores, **interp)
    wc._inat_labels = labels
    wc._inat_min_score = min_score
    wc._inat_cpu_mode = True
    return wc


CROP = np.zeros((16, 16, 3), dtype=np.uint8)


# ── the disabled / unusable states ──────────────────────────────────────────
def test_a_disabled_classifier_names_nothing():
    wc = _classifier()
    assert wc.available is False
    assert wc.reason == "disabled"
    assert wc.classify_crop(CROP) == (None, None, None)


def test_an_empty_crop_is_refused_without_touching_the_model():
    wc = _armed([0.9, 0.0], {0: "red fox", 1: "x"})
    assert wc.classify_crop(np.zeros((0, 0, 3), dtype=np.uint8)) == (None, None, None)
    assert wc.classify_crop(None) == (None, None, None)
    assert wc.interpreter.invoked == 0


def test_the_shipped_default_threshold_is_the_named_constant():
    assert _classifier().min_score == WILDLIFE_MIN_SCORE_DEFAULT


# ── step 2: a direct MobileNet rule hit ─────────────────────────────────────
def test_a_direct_mobilenet_rule_hit_is_returned_with_its_own_label():
    wc = _armed([0.81, 0.02], {0: "red fox", 1: "tabby cat"})
    assert wc.classify_crop(CROP) == ("fox", "red fox", pytest.approx(0.81))


def test_the_rule_hit_may_come_from_any_of_the_top_three():
    wc = _armed([0.55, 0.50, 0.45], {0: "tabby cat", 1: "beagle", 2: "hedgehog"})
    cat, label, _score = wc.classify_crop(CROP)
    assert (cat, label) == ("hedgehog", "hedgehog")


def test_an_unmatched_top1_is_returned_as_a_diagnostic_label_only():
    """Step 5 — no category, but the UI still learns what the model saw."""
    wc = _armed([0.77, 0.01], {0: "tabby cat", 1: "beagle"})
    cat, label, score = wc.classify_crop(CROP)
    assert cat is None
    assert (label, score) == ("tabby cat", pytest.approx(0.77))


def test_junk_below_half_the_threshold_yields_nothing_at_all():
    wc = _armed([0.10, 0.0], {0: "tabby cat", 1: "beagle"}, min_score=0.60)
    assert wc.classify_crop(CROP) == (None, None, None)


# ── step 3 + 4: the iNat second opinion ─────────────────────────────────────
def test_an_inat_rule_hit_wins_when_mobilenet_has_none():
    wc = _armed([0.40, 0.0], {0: "tabby cat", 1: "beagle"})
    _arm_inat(wc, [0.88, 0.0], {0: "Vulpes vulpes (Red Fox)", 1: "other"})
    assert wc.classify_crop(CROP) == ("fox", "Vulpes vulpes (Red Fox)", pytest.approx(0.88))


def test_mobilenet_is_consulted_before_inat():
    wc = _armed([0.70, 0.0], {0: "hedgehog", 1: "x"})
    _arm_inat(wc, [0.99, 0.0], {0: "Vulpes vulpes", 1: "y"})
    cat, label, _ = wc.classify_crop(CROP)
    assert (cat, label) == ("hedgehog", "hedgehog")


def test_a_squirrel_likely_label_plus_a_sciuridae_genus_cross_validates():
    """Step 4 — neither half is a squirrel on its own; together they are,
    and the reported score is the mean of the two.

    "Marmota" is deliberate: it is in `_SCIURIDAE_GENERA` (so it can
    cross-validate) but NOT in `_INAT_WILDLIFE_RULES`, so step 3 does
    not claim it first and step 4 is genuinely the branch under test.
    """
    wc = _armed([0.46, 0.0], {0: "hare", 1: "x"})
    _arm_inat(wc, [0.84, 0.0], {0: "Marmota marmota (Alpine Marmot)", 1: "y"})
    cat, label, score = wc.classify_crop(CROP)
    assert cat == "squirrel"
    assert score == pytest.approx((0.46 + 0.84) / 2.0)
    assert "hare" in label and "Marmota marmota" in label


def test_a_squirrel_likely_label_alone_never_cross_validates():
    wc = _armed([0.46, 0.0], {0: "hare", 1: "x"})
    cat, label, _ = wc.classify_crop(CROP)
    assert cat is None and label == "hare"


def test_the_inat_backend_is_skipped_when_it_is_not_loaded():
    wc = _armed([0.46, 0.0], {0: "hare", 1: "x"})
    assert wc._inat_interpreter is None
    assert wc.classify_crop(CROP)[0] is None


# ── the threshold band the operator's knob does NOT cover ───────────────────
def test_a_rule_hit_below_min_score_is_still_accepted_today():
    """Documented as found, not endorsed.

    Steps 2 and 3 return on the first rule match without ever comparing
    against `min_score`; the only score gate is the collector's floor of
    `max(0.05, min_score * 0.5)`. So the effective acceptance threshold
    is HALF the configured one, and the per-camera "Wildtier-Schwelle"
    admits everything in `[min_score/2, min_score)`.

    Pinned here so the behaviour cannot change by accident. Whether the
    knob SHOULD mean what its label says is an operator decision, not a
    refactor's to make.
    """
    wc = _armed([0.46, 0.0], {0: "red fox", 1: "x"}, min_score=0.90)
    assert wc.classify_crop(CROP) == ("fox", "red fox", pytest.approx(0.46))
    assert wc.classify_crop(CROP, min_score=0.90) == ("fox", "red fox", pytest.approx(0.46))


def test_the_per_call_threshold_is_restored_afterwards():
    wc = _armed([0.46, 0.0], {0: "red fox", 1: "x"}, min_score=0.35)
    wc.classify_crop(CROP, min_score=0.80)
    assert wc.min_score == 0.35


# ── _top3_cpu: the tensor plumbing ──────────────────────────────────────────
def test_top3_returns_at_most_three_sorted_descending():
    wc = _armed([0.1, 0.9, 0.5, 0.7, 0.3], {i: f"l{i}" for i in range(5)})
    got = wc._top3_mobilenet(CROP)
    assert [lbl for lbl, _ in got] == ["l1", "l3", "l2"]
    assert [round(s, 3) for _, s in got] == [0.9, 0.7, 0.5]


def test_top3_stops_at_the_half_threshold_floor():
    """The collector floor is `max(0.05, min_score * 0.5)`, NOT
    `min_score` — deliberately, so the step-4 cross-check can still see
    weak evidence. At min_score=0.50 the floor is 0.25, so 0.30 survives
    the cut and only 0.02 breaks the loop."""
    wc = _armed([0.9, 0.30, 0.02], {0: "a", 1: "b", 2: "c"}, min_score=0.50)
    assert [lbl for lbl, _ in wc._top3_mobilenet(CROP)] == ["a", "b"]


def test_the_collector_floor_never_drops_below_five_percent():
    """`max(0.05, …)` — a tiny min_score must not admit pure noise."""
    wc = _armed([0.9, 0.04, 0.0], {0: "a", 1: "b", 2: "c"}, min_score=0.02)
    assert [lbl for lbl, _ in wc._top3_mobilenet(CROP)] == ["a"]


def test_a_uint8_output_is_dequantised_with_the_models_scale_and_zero_point():
    wc = _armed(
        np.array([200, 10, 0], dtype=np.uint8),
        {0: "a", 1: "b", 2: "c"},
        out_dtype=np.uint8,
        quantization=(0.005, 20),
    )
    got = wc._top3_mobilenet(CROP)
    assert got[0][1] == pytest.approx((200 - 20) * 0.005)


def test_a_uint8_output_without_a_scale_falls_back_to_255ths():
    wc = _armed(
        np.array([255, 0, 0], dtype=np.uint8),
        {0: "a", 1: "b", 2: "c"},
        out_dtype=np.uint8,
        quantization=(0.0, 0),
    )
    assert wc._top3_mobilenet(CROP)[0][1] == pytest.approx(1.0)


def test_a_1000_entry_label_file_against_1001_bins_shifts_by_one():
    """The background-class offset, detected lazily on first inference."""
    scores = np.zeros(1001, dtype=np.float32)
    scores[701] = 0.9
    wc = _armed(scores, {i: f"label{i}" for i in range(1000)})
    assert wc._label_offset == 0
    assert wc._top3_mobilenet(CROP)[0][0] == "label700"
    assert wc._label_offset == 1


def test_a_float_model_is_normalised_around_127_5():
    wc = _armed([0.9, 0.0], {0: "a", 1: "b"}, in_dtype=np.float32)
    wc._top3_mobilenet(CROP)
    assert wc.interpreter.last_input.dtype == np.float32
    assert wc.interpreter.last_input.min() == pytest.approx(-1.0)


def test_an_unknown_class_id_degrades_to_its_index():
    wc = _armed([0.0, 0.9], {0: "a"})
    assert wc._top3_mobilenet(CROP)[0][0] == "1"


# ── _top3_inat: the same plumbing, its own thresholds ───────────────────────
def test_the_inat_backend_uses_its_own_floor_not_the_wildlife_one():
    wc = _armed([0.0, 0.0], {0: "a", 1: "b"}, min_score=0.90)
    _arm_inat(wc, [0.20, 0.02], {0: "Sciurus vulgaris", 1: "y"}, min_score=0.30)
    assert [lbl for lbl, _ in wc._top3_inat(CROP)] == ["Sciurus vulgaris"]


def test_the_inat_backend_dequantises_the_same_way():
    wc = _armed([0.0, 0.0], {0: "a", 1: "b"})
    _arm_inat(
        wc,
        np.array([180, 0, 0], dtype=np.uint8),
        {0: "Vulpes vulpes", 1: "y", 2: "z"},
        out_dtype=np.uint8,
        quantization=(0.004, 10),
    )
    assert wc._top3_inat(CROP)[0][1] == pytest.approx((180 - 10) * 0.004)


def test_the_two_backends_keep_separate_timing_windows():
    wc = _armed([0.9, 0.0], {0: "red fox", 1: "x"})
    _arm_inat(wc, [0.9, 0.0], {0: "Vulpes vulpes", 1: "y"})
    wc._top3_mobilenet(CROP)
    assert wc._inat_timing is not wc
    wc._top3_inat(CROP)
    assert wc.interpreter.invoked == 1
    assert wc._inat_interpreter.invoked == 1
