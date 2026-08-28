"""The loop, end to end: an answer moves a threshold, or says why not.

    detection → question → answer → corpus → calibration → the net's
    shape → the thresholds the detector uses

The properties pinned here are the ones the operator's complaint was
actually about: the number shown is the number the pipeline uses, a drag
moves that number, and a change that did not happen is still reported.
"""

from __future__ import annotations

import time

import pytest

from app import net_archive
from app.detection_feedback import (
    MIN_JUDGED_PER_CLASS,
    MIN_JUDGED_PER_STRATUM,
    corpus_stats,
    record_alert,
    record_verdict,
    resolve_stratum,
)
from app.thresholds import resolve_effective
from app.thresholds._apply import adapted_layer, effective_e, manual_patch, push_for, spawn_for
from app.thresholds._learner import evaluate_axis

CAM = "cam_werkstatt"
PUSH = {"labels": {"person": {"push": True, "threshold": 0.85}}}


def _cam(**over):
    return {"id": CAM, "name": "Werkstatt", "object_filter": ["person"], **over}


def _eff(cam, label="person"):
    return resolve_effective(cam, PUSH, label, adapted=adapted_layer(cam, label))


# ── the resolution order picks the right layer ────────────────────────


def test_the_ladder_ranks_camera_above_adapted_above_global(tmp_storage_root):
    base = _cam()
    assert _eff(base).push == 0.85
    assert _eff(base).source["push"] == "global"

    learned = _cam(net_adapted={"person": {"E": 20}})
    assert _eff(learned).push == pytest.approx(push_for("person", 20))
    assert _eff(learned).source["push"] == "adapted"

    dragged = _cam(
        net_adapted={"person": {"E": 20}},
        push_thresholds={"person": push_for("person", 80)},
        net_pin={"person": {"E": 80}},
    )
    assert _eff(dragged).push == pytest.approx(push_for("person", 80))
    assert _eff(dragged).source["push"] == "camera"


def test_a_drag_moves_the_value_the_push_gate_reads(tmp_storage_root):
    """THR-3 + A7 in one assertion. Before THR-3 this key was settable
    and inert; the drag would have been decoration."""
    patch = manual_patch("person", 70)
    cam = _cam(**patch)
    eff = _eff(cam)
    assert eff.push == pytest.approx(push_for("person", 70))
    assert eff.spawn == pytest.approx(spawn_for("person", 70))
    assert eff.push < 0.85  # more sensitive: the bar came DOWN
    assert effective_e(cam, "person") == 70


def test_the_learner_writes_a_layer_a_pin_outranks(tmp_storage_root):
    """The precedence question answers itself: a drag writes the camera
    layer, the learner writes `adapted`, and the ladder already ranks
    them. Neither has to know about the other."""
    cam = _cam(
        net_pin={"person": {"E": 80}},
        push_thresholds={"person": push_for("person", 80)},
        net_adapted={"person": {"E": 10}},
    )
    assert _eff(cam).push == pytest.approx(push_for("person", 80))


# ── the corpus and its bars ───────────────────────────────────────────


def _fill(root, cam, label, n_true, n_false, *, hi=0.95, lo=0.20):
    """Judged alerts with cleanly separated true / false score bands."""
    for i in range(n_true):
        eid = f"{cam}-t-{label}-{i}"
        record_alert(
            root,
            cam_id=cam,
            event_id=eid,
            label=label,
            score=hi - i * 0.001,
            threshold=0.5,
            ts=time.time(),
        )
        record_verdict(root, event_id=eid, correct=True, ts=time.time(), cam_id=cam)
    for i in range(n_false):
        eid = f"{cam}-f-{label}-{i}"
        record_alert(
            root,
            cam_id=cam,
            event_id=eid,
            label=label,
            score=lo + i * 0.001,
            threshold=0.5,
            ts=time.time(),
        )
        record_verdict(root, event_id=eid, correct=False, ts=time.time(), cam_id=cam)


def test_the_empty_state_reports_no_evidence_not_a_fabricated_number(tmp_storage_root):
    stats = corpus_stats(tmp_storage_root)
    row = resolve_stratum(stats, CAM, "person")
    assert row["ready"] is False
    assert row["n_total"] == 0
    assert row["blockers"]
    outcome = evaluate_axis(tmp_storage_root, _cam(), PUSH, "person", stats)
    assert outcome["state"] == net_archive.STATE_PENDING
    assert outcome["write"] is False
    assert outcome["e_after"] == outcome["e_before"] == 50
    assert f"0 von {MIN_JUDGED_PER_STRATUM}" in outcome["reason"]


def test_a_stratum_under_the_bar_never_moves_anything(tmp_storage_root):
    _fill(tmp_storage_root, CAM, "person", MIN_JUDGED_PER_CLASS - 1, MIN_JUDGED_PER_CLASS - 1)
    stats = corpus_stats(tmp_storage_root)
    outcome = evaluate_axis(tmp_storage_root, _cam(), PUSH, "person", stats)
    assert outcome["state"] == net_archive.STATE_PENDING
    assert outcome["write"] is False


def test_pooling_widens_the_sample_without_weakening_the_class_bars(tmp_storage_root):
    """P3 · at seven events a day, 50 per (camera, label) is a decade for
    the tail. Three cameras' worth of `squirrel` is still squirrel."""
    for cam in ("cam_a", "cam_b", "cam_c"):
        _fill(tmp_storage_root, cam, "squirrel", 20, 20)
    stats = corpus_stats(tmp_storage_root)
    own = resolve_stratum(stats, "cam_a", "squirrel")
    assert own["scope"] == "pooled"
    assert own["ready"] is True
    assert own["n_total"] == 120


def test_a_pooled_stratum_still_needs_twenty_of_each_verdict(tmp_storage_root):
    for cam in ("cam_a", "cam_b", "cam_c"):
        _fill(tmp_storage_root, cam, "squirrel", 30, 2)
    stats = corpus_stats(tmp_storage_root)
    row = resolve_stratum(stats, "cam_a", "squirrel")
    assert row["ready"] is False
    assert any("confirmed-false" in b for b in row["blockers"])


# ── the five outcomes ─────────────────────────────────────────────────


def test_an_answer_that_changed_nothing_is_recorded_not_omitted(tmp_storage_root):
    """Silence is indistinguishable from a bug, and the operator asked
    whether their judgement was an optimisation. "Bestätigt, keine
    Änderung" is an answer; an absent card is not."""
    _fill(tmp_storage_root, CAM, "person", 40, 40, hi=0.95, lo=0.20)
    stats = corpus_stats(tmp_storage_root)
    # Walk the axis to where the corpus wants it — five points a night,
    # which is the rail, so it takes several runs to get there.
    cam = _cam()
    outcome = None
    for _ in range(30):
        outcome = evaluate_axis(tmp_storage_root, cam, PUSH, "person", stats)
        if outcome["state"] != net_archive.STATE_CHANGED:
            break
        cam = _cam(net_adapted={"person": {"E": outcome["e_after"]}})
    assert outcome["state"] == net_archive.STATE_CONFIRMED
    assert outcome["write"] is False
    assert "bleibt bei" in outcome["reason"]
    assert "keine" not in outcome["reason"] or "Einschätzung" in outcome["reason"]


def test_a_pinned_axis_is_proposed_to_and_never_written(tmp_storage_root):
    _fill(tmp_storage_root, CAM, "person", 40, 40)
    stats = corpus_stats(tmp_storage_root)
    cam = _cam(net_pin={"person": {"E": 50, "ts": time.time()}})
    outcome = evaluate_axis(tmp_storage_root, cam, PUSH, "person", stats)
    assert outcome["state"] == net_archive.STATE_PINNED
    assert outcome["write"] is False
    assert outcome["proposal"] is not None
    assert "die Automatik rührt sie nicht an" in outcome["reason"]


def test_the_person_floor_holds_against_a_corpus_that_wants_e_ten(tmp_storage_root):
    """MANDATORY #3, driven by a real corpus rather than by the clamp.

    Every judged `person` is a false alarm at a high score and every true
    one is low — the shape that argues for a very strict bar. The
    automatic path must still refuse to go below E 35.
    """
    _fill(tmp_storage_root, CAM, "person", 40, 40, hi=0.35, lo=0.90)
    stats = corpus_stats(tmp_storage_root)
    cam = _cam(role="security", net_adapted={"person": {"E": 36}})
    outcome = evaluate_axis(tmp_storage_root, cam, PUSH, "person", stats)
    assert outcome["e_after"] >= 35


def test_the_learner_never_jumps_more_than_five_points_in_one_run(tmp_storage_root):
    """MANDATORY #4, through the real evaluation path."""
    _fill(tmp_storage_root, CAM, "person", 40, 40, hi=0.95, lo=0.20)
    stats = corpus_stats(tmp_storage_root)
    cam = _cam(net_adapted={"person": {"E": 95}})
    outcome = evaluate_axis(tmp_storage_root, cam, PUSH, "person", stats)
    assert abs(outcome["e_after"] - outcome["e_before"]) <= 5
