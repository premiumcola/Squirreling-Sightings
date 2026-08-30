"""``excluded_classes`` is a deny-list that nobody read.

The Simulieren panel's Cluster 3 offers one-tap false-positive pills —
"ein Tap entfernt sie aus der Detection-Pipeline". The tap wrote
``cameras[].excluded_classes``, ``routes/cameras.py`` validated it, saved
it, and echoed it back under ``"effective"``, which made it look
confirmed-active. Nothing ever read it: ``detect_setup`` resolved
``object_filter`` and nothing else, so the pill vanished, the toast said
success, and the class kept firing forever. On these cameras that meant
``book`` 379x and ``bench`` 71x in a 60-second window, with the
operator's only suppression tool quietly doing nothing.

The interaction that matters most is the empty ``object_filter``: it
means "allow every class", and if that also meant "ignore the deny-list"
then exclusions would fail on precisely the cameras that filter nothing.
"""

from __future__ import annotations

from app.detect_setup import apply_object_filter, build_detection_setup
from app.detectors._types import Detection
from app.routes._sim_evidence import _off_filter

CAM = "reolink_cx810_garten_172"


def _det(label: str, score: float = 0.8) -> Detection:
    return Detection(label=label, score=score, bbox=(10, 10, 100, 100))


def _labels(dets) -> list[str]:
    return [d.label for d in dets]


# ── the setup carries the deny-list at all ────────────────────────────────


def test_the_setup_resolves_excluded_classes():
    setup = build_detection_setup(CAM, {"excluded_classes": ["book", "bench"]})
    assert setup.excluded_classes == frozenset({"book", "bench"})


def test_an_absent_deny_list_is_empty_not_none():
    assert build_detection_setup(CAM, {}).excluded_classes == frozenset()


# ── the gate actually subtracts ───────────────────────────────────────────


def test_an_excluded_class_is_dropped():
    dets = [_det("person"), _det("book"), _det("cat")]
    kept, dropped = apply_object_filter(dets, frozenset(), frozenset({"book"}))
    assert _labels(kept) == ["person", "cat"]
    assert _labels([d for d, _ in dropped]) == ["book"]


def test_the_drop_says_why_in_german():
    _kept, dropped = apply_object_filter([_det("bench")], frozenset(), frozenset({"bench"}))
    assert dropped[0][1] == "Klasse 'bench' ist ausgeschlossen"


def test_an_empty_object_filter_still_honours_the_deny_list():
    """The interaction that would have broken the fix. No allow-list means
    "every class passes" — it must not also mean "and nothing is denied",
    or the feature would fail on the cameras that need it most."""
    dets = [_det("person"), _det("book")]
    kept, _dropped = apply_object_filter(dets, frozenset(), frozenset({"book"}))
    assert _labels(kept) == ["person"]


def test_an_exclusion_beats_an_inclusion():
    """Precedence: the deny-list is the more recent and more specific act —
    the operator tapped it after watching the class fire, while the
    allow-list is usually the seeded default nobody revisited."""
    dets = [_det("person"), _det("bird")]
    kept, dropped = apply_object_filter(dets, frozenset({"person", "bird"}), frozenset({"bird"}))
    assert _labels(kept) == ["person"]
    assert dropped[0][1] == "Klasse 'bird' ist ausgeschlossen"


def test_both_gates_report_their_own_reason():
    dets = [_det("person"), _det("book"), _det("bench")]
    _kept, dropped = apply_object_filter(dets, frozenset({"person"}), frozenset({"book"}))
    reasons = {d.label: reason for d, reason in dropped}
    assert reasons["book"] == "Klasse 'book' ist ausgeschlossen"
    assert reasons["bench"] == "Klasse 'bench' nicht im Objektfilter"


def test_nothing_configured_is_still_a_pass_through():
    dets = [_det("person"), _det("book")]
    kept, dropped = apply_object_filter(dets, frozenset(), frozenset())
    assert _labels(kept) == ["person", "book"]
    assert dropped == []


# ── the panel's pill has to stay gone ─────────────────────────────────────


def test_an_excluded_class_stops_offering_its_pill():
    """Cluster 3's pills come from the "filtered" verdict, which an
    exclusion now also produces. Left alone, the pill for a class the
    operator already excluded would reappear every tick, inviting the same
    tap forever."""
    class_log = [
        (0.0, "book", "filtered"),
        (0.1, "book", "filtered"),
        (0.2, "bench", "filtered"),
    ]
    assert _off_filter(class_log, ("book",)) == {"off_filter_60s_counts": {"bench": 1}}
    assert _off_filter(class_log) == {"off_filter_60s_counts": {"book": 2, "bench": 1}}
