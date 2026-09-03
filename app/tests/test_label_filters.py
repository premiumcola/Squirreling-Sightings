"""The post-inference plausibility gates, and what they report.

`LabelFilterMixin` decides which model output survives, and every drop
has to carry a machine-readable reason — `_decision_log` turns those
into the German line an operator reads in `docker logs`, and a silent
drop is the hardest kind of detection bug to chase.

`test_sim_production_parity.py` pins the `_LABEL_MIN_BBOX` table and
which call paths arm it. Nothing exercised the gate itself, which is
why a parameter could sit in its signature unread: this file covers the
behaviour so the surface can be trimmed to what is actually used.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.detectors._filters import LabelFilterMixin  # noqa: E402
from app.detectors._types import Detection  # noqa: E402

FRAME = np.zeros((400, 600, 3), dtype=np.uint8)  # h=400, w=600


class _Host(LabelFilterMixin):
    """The mixin's host contract, in its smallest honest form."""

    min_score = 0.20


def _det(label: str, score: float, bbox: tuple[int, int, int, int]) -> Detection:
    return Detection(label=label, score=score, bbox=bbox)


def _run(dets, thresholds=None):
    return _Host()._apply_label_filters_with_reasons(dets, FRAME, thresholds)


# A person box that clears both floors: h=80 (0.20 of 400) and
# area=80*100=8000 (0.033 of 240000).
BIG_PERSON = (100, 100, 200, 180)


def test_an_empty_list_is_returned_untouched():
    kept, drops = _run([])
    assert kept == [] and drops == []


def test_a_detection_with_no_rule_against_it_survives():
    d = _det("cat", 0.4, (10, 10, 60, 60))
    kept, drops = _run([d])
    assert kept == [d] and drops == []


def test_a_per_label_threshold_drops_and_says_so():
    d = _det("cat", 0.30, (10, 10, 60, 60))
    kept, drops = _run([d], {"cat": 0.50})
    assert kept == []
    assert len(drops) == 1
    assert drops[0][0] is d
    assert "label_threshold(cat)" in drops[0][1]


def test_a_per_label_threshold_only_binds_its_own_label():
    cat = _det("cat", 0.30, (10, 10, 60, 60))
    dog = _det("dog", 0.30, (10, 10, 60, 60))
    kept, _drops = _run([cat, dog], {"cat": 0.50})
    assert kept == [dog]


def test_a_detection_exactly_at_its_threshold_is_kept():
    """`score < t` drops — equality is a keep, and that boundary is the
    difference between a tuned camera reporting and going quiet."""
    d = _det("cat", 0.50, (10, 10, 60, 60))
    kept, _ = _run([d], {"cat": 0.50})
    assert kept == [d]


def test_a_short_person_box_hits_the_height_floor():
    # h = 40 = 0.10 of the frame, under the 0.15 floor.
    d = _det("person", 0.9, (100, 100, 300, 140))
    kept, drops = _run([d])
    assert kept == []
    assert "size_floor" in drops[0][1] and "h_frac" in drops[0][1]


def test_a_tall_but_thin_person_box_hits_the_area_floor():
    # h = 100 = 0.25 (clears height); area = 100*4 = 400 = 0.0017 of the
    # frame, under the 0.02 floor.
    d = _det("person", 0.9, (100, 100, 104, 200))
    kept, drops = _run([d])
    assert kept == []
    assert "size_floor" in drops[0][1] and "area_frac" in drops[0][1]


def test_a_full_size_person_clears_both_floors():
    d = _det("person", 0.9, BIG_PERSON)
    kept, drops = _run([d])
    assert kept == [d] and drops == []


def test_the_size_floor_only_applies_to_labelled_classes():
    """A tiny cat is not implausible; a tiny person is."""
    tiny_cat = _det("cat", 0.9, (100, 100, 104, 140))
    tiny_person = _det("person", 0.9, (100, 100, 104, 140))
    kept, drops = _run([tiny_cat, tiny_person])
    assert kept == [tiny_cat]
    assert len(drops) == 1


def test_the_confidence_gate_runs_before_the_size_gate():
    """Both would drop this box; the reason must name the first one, or
    the operator tunes the wrong knob."""
    d = _det("person", 0.10, (100, 100, 104, 140))
    _kept, drops = _run([d], {"person": 0.50})
    assert "label_threshold" in drops[0][1]


def test_kept_and_dropped_partition_the_input():
    dets = [
        _det("person", 0.9, BIG_PERSON),
        _det("person", 0.9, (100, 100, 104, 140)),
        _det("cat", 0.1, (10, 10, 60, 60)),
    ]
    kept, drops = _run(dets, {"cat": 0.5})
    assert len(kept) + len(drops) == len(dets)
    assert set(id(d) for d in kept).isdisjoint(id(d) for d, _ in drops)


def test_the_gate_takes_no_argument_it_does_not_read():
    """`global_threshold` sat in this signature unread for its whole
    life — the one caller passed its resolved confidence threshold and
    the body never looked at it. Removed; pinned here so it cannot come
    back by habit."""
    import inspect

    params = list(inspect.signature(_Host._apply_label_filters_with_reasons).parameters)
    assert params == ["self", "dets", "frame", "label_thresholds"]
