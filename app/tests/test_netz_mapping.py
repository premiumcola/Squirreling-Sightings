"""The E ↔ Schwelle mapping, its rails, and the JS mirror.

``_mapping.js`` and ``thresholds/_apply.py`` are bit-for-bit mirrors —
the same rule that binds ``build_camera_id`` to ``buildCameraId``. The
fixture written here is what both sides read: Python generates it, and
``test_netz_mapping_mirror.py`` runs the JS against it. A drift in
either direction fails one of the two.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.thresholds._apply import (
    AUTO_E_FLOOR_PERSON_SECURITY,
    AXIS_ORDER,
    E_FACTORY,
    MAX_LEARNER_STEP_E,
    MIN_GAP,
    PUSH_CEIL,
    PUSH_FLOOR,
    SPAWN_CEIL,
    SPAWN_FLOOR,
    clamp_e,
    clamp_learner_e,
    e_from_push,
    effective_e,
    manual_patch,
    provenance,
    push_anchor,
    push_for,
    spawn_anchor,
    spawn_for,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "netz_mapping.json"


def _all_pairs():
    for label in AXIS_ORDER:
        for e in range(0, 101):
            yield label, e


def test_factory_reproduces_the_shipped_values_exactly():
    """E = 50 must mean "Werkseinstellung für diese Klasse".

    That is the whole reason the mapping is anchored rather than
    absolute: one absolute scale cannot reproduce both person's shipped
    spawn (.45) and its shipped push (.85), because those sit at
    different points on any single axis.
    """
    for label in AXIS_ORDER:
        assert spawn_for(label, E_FACTORY) == pytest.approx(spawn_anchor(label))
        expected_push = max(push_anchor(label), spawn_anchor(label) + MIN_GAP)
        expected_push = min(max(expected_push, PUSH_FLOOR), PUSH_CEIL)
        assert push_for(label, E_FACTORY) == pytest.approx(expected_push, abs=1e-4)


def test_bigger_e_is_never_stricter():
    """Direction is the classic radar failure mode. Bigger radius = more
    sensitive = more Meldungen, monotonically, on every axis."""
    for label in AXIS_ORDER:
        spawns = [spawn_for(label, e) for e in range(101)]
        pushes = [push_for(label, e) for e in range(101)]
        assert spawns == sorted(spawns, reverse=True)
        assert pushes == sorted(pushes, reverse=True)


def test_push_stays_at_least_ten_points_above_spawn():
    """MANDATORY #2. The gap IS the question band — if it ever closed,
    the Frage would have nothing to live in and the whole design would
    quietly collapse back into the dead zone it replaces."""
    for label, e in _all_pairs():
        assert push_for(label, e) >= spawn_for(label, e) + MIN_GAP - 1e-9


def test_every_value_stays_inside_the_rails():
    for label, e in _all_pairs():
        assert SPAWN_FLOOR - 1e-9 <= spawn_for(label, e) <= SPAWN_CEIL + 1e-9
        # The min-gap correction may lift push above PUSH_CEIL only when
        # spawn is at its own ceiling; assert the documented ordering
        # rather than a bound the gap rule can legitimately exceed.
        assert push_for(label, e) >= PUSH_FLOOR - 1e-9
        assert push_for(label, e) <= max(PUSH_CEIL, SPAWN_CEIL + MIN_GAP) + 1e-9


def test_e_from_push_round_trips_through_the_anchor():
    for label in AXIS_ORDER:
        for e in range(101):
            back = e_from_push(label, push_anchor(label) + (E_FACTORY - e) * 0.006)
            assert back == e


def test_garbage_e_becomes_factory_not_zero():
    """Zero is the strictest setting there is. A parse failure must never
    silently mean "report nothing"."""
    for junk in (None, "", "abc", [], {}):
        assert clamp_e(junk) == E_FACTORY
    assert clamp_e(-40) == 0
    assert clamp_e(9999) == 100


# ── the learner's own two rails ───────────────────────────────────────


def test_the_learner_moves_at_most_five_points_per_run():
    """MANDATORY #4. A recommendation 30 points away is a recommendation
    to distrust; the corpus that produced it will still be there
    tomorrow, and six nights of five points gets there anyway."""
    assert clamp_learner_e({}, "cat", 50, 80) == 50 + MAX_LEARNER_STEP_E
    assert clamp_learner_e({}, "cat", 50, 20) == 50 - MAX_LEARNER_STEP_E
    assert clamp_learner_e({}, "cat", 50, 52) == 52


def test_person_on_a_security_camera_cannot_be_lowered_past_its_floor():
    """MANDATORY #3. `person` on Werkstatt is what an intruder trips. A
    corpus dominated by the operator's own comings and goings would
    otherwise learn its way to blindness one night at a time."""
    security = {"role": "security"}
    e = 100
    for _ in range(60):  # far more runs than it takes to reach the floor
        e = clamp_learner_e(security, "person", e, 0)
    assert e == AUTO_E_FLOOR_PERSON_SECURITY


def test_the_floor_is_automatic_only_and_class_and_role_specific():
    security = {"role": "security"}
    wildlife = {"role": "wildlife"}
    assert clamp_learner_e(security, "person", 36, 30) == AUTO_E_FLOOR_PERSON_SECURITY
    # Another class on the same camera is unaffected.
    assert clamp_learner_e(security, "cat", 36, 30) == 31
    # `person` on the feeder camera is not an intruder signal.
    assert clamp_learner_e(wildlife, "person", 36, 30) == 31
    # A MANUAL drag may cross it — manual_patch applies no floor at all.
    assert manual_patch("person", 10)["net_pin"]["person"]["E"] == 10


def test_a_camera_with_no_role_is_treated_as_security():
    """The safe direction: a camera nobody has classified is one an
    intruder could trip."""
    assert clamp_learner_e({}, "person", 36, 30) == AUTO_E_FLOOR_PERSON_SECURITY


# ── provenance ────────────────────────────────────────────────────────


def test_provenance_reports_which_force_last_moved_the_axis():
    assert provenance({}, "cat") == "werk"
    assert provenance({"net_adapted": {"cat": {"E": 60}}}, "cat") == "automatisch"
    assert provenance({"net_pin": {"cat": {"E": 60}}}, "cat") == "manuell"


def test_a_pin_outranks_the_learner_permanently():
    """No timeout. A value that silently reverts after 30 days is
    precisely the thing that destroys trust."""
    cam = {"net_pin": {"cat": {"E": 20}}, "net_adapted": {"cat": {"E": 90}}}
    assert effective_e(cam, "cat") == 20
    assert provenance(cam, "cat") == "manuell"


# ── the mirror fixture ────────────────────────────────────────────────


def test_write_mapping_fixture():
    """MANDATORY #1 (Python half). Regenerates the fixture both sides read.

    Kept as a test rather than a script so it cannot rot: a change to
    the mapping updates the fixture in the same run that would otherwise
    have broken the JS mirror silently.
    """
    payload = {
        "step": 0.006,
        "e_factory": E_FACTORY,
        "rails": {
            "spawn": [SPAWN_FLOOR, SPAWN_CEIL],
            "push": [PUSH_FLOOR, PUSH_CEIL],
            "min_gap": MIN_GAP,
        },
        "values": {
            label: {
                str(e): {"spawn": spawn_for(label, e), "push": push_for(label, e)}
                for e in range(101)
            }
            for label in AXIS_ORDER
        },
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    reread = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(reread["values"]) == len(AXIS_ORDER)
    assert len(reread["values"]["person"]) == 101
