"""THR-2 · the corpus finally has a consumer, and it knows when to refuse.

Before this, `judged_alerts` / `score_summary` / `corpus_stats` had no
non-test caller inside the app at all — `scripts/corpus_report` read the
roll-up and nothing ever turned it into a decision. `recommend_push` is
that consumer.

The properties worth pinning are not "it returns a float". They are:

* it refuses below the evidence bar, in WORDS, with `recommended` None;
* it never leaves the hard floor/ceiling;
* it never proposes RAISING a threshold on a label the camera marks
  `alarm` — the security asymmetry, where the error the data cannot
  see (the intruder who was never alerted on) is the expensive one;
* it reports what it did to the samples it saw, not just a number;
* it reports the LIVE gate next to the resolved ladder, because the
  shipped push consumer reads neither the per-camera override nor the
  shipped defaults, and printing only the ladder would print a number
  the system does not use.
"""

from __future__ import annotations

from app.detection_feedback import MIN_JUDGED_PER_CLASS
from app.thresholds import (
    PUSH_CEILING,
    PUSH_FLOOR,
    SEPARATION_CLEAN,
    SEPARATION_OVERLAP,
    VERDICT_HOLD,
    VERDICT_INSUFFICIENT,
    VERDICT_LOWER,
    VERDICT_RAISE,
    enforced_push,
    recommend_push,
)

PUSH = {"labels": {"person": {"push": True, "threshold": 0.85}}}


def _pairs(true_scores, false_scores):
    """`judged_alerts()`-shaped input: (alert dict, user said it was right)."""
    return [({"score": s}, True) for s in true_scores] + [
        ({"score": s}, False) for s in false_scores
    ]


def _stratum(true_scores, false_scores, *, ready=True, cam="cam1", label="person", blockers=None):
    """A `corpus_stats()["strata"]` row over those scores."""
    t, f = sorted(true_scores), sorted(false_scores)
    return {
        "cam": cam,
        "label": label,
        "n_total": len(t) + len(f),
        "n_true": len(t),
        "n_false": len(f),
        "answer_rate": 0.5,
        "true_min": t[0] if t else None,
        "true_median": t[len(t) // 2] if t else None,
        "false_max": f[-1] if f else None,
        "false_median": f[len(f) // 2] if f else None,
        "ready": ready,
        "blockers": list(blockers or []),
    }


def _spread(lo, hi, n):
    """n scores evenly across [lo, hi]."""
    step = (hi - lo) / max(n - 1, 1)
    return [round(lo + i * step, 4) for i in range(n)]


# ── refusing ──────────────────────────────────────────────────────────


def test_refuses_below_the_evidence_bar_in_words():
    st = _stratum(
        _spread(0.7, 0.9, 4),
        _spread(0.2, 0.4, 4),
        ready=False,
        blockers=["judged 8/50", "confirmed-true 4/20"],
    )
    rec = recommend_push(st, _pairs(_spread(0.7, 0.9, 4), _spread(0.2, 0.4, 4)), {}, PUSH)
    assert rec.verdict == VERDICT_INSUFFICIENT
    assert rec.recommended is None
    assert rec.confidence == "none"
    # The refusal has to name what is missing, not just decline.
    assert "judged 8/50" in rec.reason
    assert "confirmed-true 4/20" in rec.reason
    # And it must still report where the bar stands today.
    assert rec.current == 0.85


def test_refuses_on_an_empty_stratum():
    rec = recommend_push(_stratum([], [], ready=False), None, {}, PUSH)
    assert rec.verdict == VERDICT_INSUFFICIENT
    assert rec.recommended is None


def test_refuses_when_the_row_carries_no_readiness_verdict():
    """A hand-built dict must not be able to sneak past the bar."""
    rec = recommend_push({"cam": "c", "label": "person"}, _pairs([0.9] * 40, [0.1] * 40), {}, PUSH)
    assert rec.verdict == VERDICT_INSUFFICIENT
    assert any("readiness" in b for b in rec.blockers)


def test_ready_row_without_scores_says_so_rather_than_guessing():
    st = _stratum(_spread(0.6, 0.9, 30), _spread(0.1, 0.4, 30))
    rec = recommend_push(st, None, {}, PUSH)
    assert rec.verdict == VERDICT_INSUFFICIENT
    assert any("judged_alerts" in b for b in rec.blockers)


# ── proposing ─────────────────────────────────────────────────────────


def test_clean_separation_lands_between_the_classes():
    true_scores = _spread(0.60, 0.95, 30)
    false_scores = _spread(0.10, 0.45, 30)
    rec = recommend_push(
        _stratum(true_scores, false_scores), _pairs(true_scores, false_scores), {}, PUSH
    )
    assert rec.verdict == VERDICT_LOWER
    assert rec.evidence["separation"] == SEPARATION_CLEAN
    # Strictly above every judged false alarm and at/below the trues.
    assert max(false_scores) < rec.recommended <= min(true_scores)
    # It keeps every real sighting on record and blocks every false one.
    assert rec.evidence["at_recommended"] == {"kept_true": 30, "blocked_false": 30}
    # And it says what today's bar costs: 0.85 throws most sightings away.
    assert rec.evidence["at_current"]["kept_true"] < 30


def test_reason_states_the_samples_the_separation_and_the_effect():
    true_scores = _spread(0.60, 0.95, 30)
    false_scores = _spread(0.10, 0.45, 30)
    rec = recommend_push(
        _stratum(true_scores, false_scores), _pairs(true_scores, false_scores), {}, PUSH
    )
    assert "30 confirmed-true" in rec.reason
    assert "30 confirmed-false" in rec.reason
    assert "separate" in rec.reason
    assert "30/30" in rec.reason


def test_overlap_keeps_the_sightings_and_says_a_threshold_cannot_fix_it():
    """Interleaved classes: recall wins, and the report admits the rest."""
    true_scores = _spread(0.40, 0.90, 40)
    false_scores = _spread(0.35, 0.85, 40)
    rec = recommend_push(
        _stratum(true_scores, false_scores), _pairs(true_scores, false_scores), {}, PUSH
    )
    assert rec.evidence["separation"] == SEPARATION_OVERLAP
    # 95% of the confirmed-true sightings survive the proposed bar.
    assert rec.evidence["at_recommended"]["kept_true"] >= 38
    # Some false alarms get through and it says so rather than pretending.
    assert rec.evidence["at_recommended"]["blocked_false"] < 40
    assert "OVERLAP" in rec.reason
    assert "label veto" in rec.reason


def test_hold_when_the_current_bar_is_already_the_right_one():
    true_scores = _spread(0.55, 0.95, 30)
    false_scores = _spread(0.10, 0.48, 30)
    push = {"labels": {"person": {"push": True, "threshold": 0.53}}}
    rec = recommend_push(
        _stratum(true_scores, false_scores), _pairs(true_scores, false_scores), {}, push
    )
    assert rec.verdict == VERDICT_HOLD
    assert rec.recommended == rec.current


def test_can_propose_raising_on_a_non_alarm_label():
    """The recommender is not one-directional — only `alarm` is capped."""
    true_scores = _spread(0.70, 0.95, 30)
    false_scores = _spread(0.30, 0.60, 30)
    push = {"labels": {"person": {"push": True, "threshold": 0.30}}}
    rec = recommend_push(
        _stratum(true_scores, false_scores), _pairs(true_scores, false_scores), {}, push
    )
    assert rec.verdict == VERDICT_RAISE
    assert rec.recommended > 0.30


# ── the rails ─────────────────────────────────────────────────────────


def test_never_proposes_above_the_ceiling():
    """Everything judged sits high; the proposal still stops at the ceiling.

    A threshold above the ceiling is an off switch wearing a decimal
    point, and turning a label off is the operator's call.
    """
    true_scores = [0.99] * 30
    false_scores = [0.985] * 30
    rec = recommend_push(
        _stratum(true_scores, false_scores), _pairs(true_scores, false_scores), {}, PUSH
    )
    assert rec.recommended <= PUSH_CEILING
    assert rec.evidence["clamped"] is True


def test_never_proposes_below_the_floor():
    """Below-floor evidence must produce a refusal, not a floored value.

    This sample is the case the floor clamp was written for — and the
    case that showed the clamp was unsafe. Every confirmed-true score is
    0.10, under PUSH_FLOOR. Clamping the proposal up to 0.20 satisfies
    "not below the floor" while blocking all 30 confirmed sightings: a
    recall of zero, under prose that quoted MIN_TRUE_RECALL. The number
    was legal and the promise attached to it was false.

    The property still holds — nothing below the floor is ever proposed.
    It now holds by proposing nothing.
    """
    true_scores = [0.10] * 30
    false_scores = [0.05] * 30
    push = {"labels": {"person": {"push": True, "threshold": 0.85}}}
    rec = recommend_push(
        _stratum(true_scores, false_scores), _pairs(true_scores, false_scores), {}, push
    )
    assert rec.recommended is None or rec.recommended >= PUSH_FLOOR
    assert (
        rec.recommended is None
    ), "a value here would keep 0 of 30 confirmed sightings while claiming 95 %"


def test_alarm_label_is_never_proposed_upward():
    """The security asymmetry, and the single most important rule here.

    Same evidence that produced a RAISE above; with `person` marked
    `alarm` on this camera the proposal is capped at the current bar.
    A missed intruder costs more than a false alarm, so adaptation may
    lower the bar on an alarm label and never raise it.
    """
    true_scores = _spread(0.70, 0.95, 30)
    false_scores = _spread(0.30, 0.60, 30)
    push = {"labels": {"person": {"push": True, "threshold": 0.30}}}
    cam = {"class_severity": {"person": "alarm"}}
    rec = recommend_push(
        _stratum(true_scores, false_scores), _pairs(true_scores, false_scores), cam, push
    )
    assert rec.verdict == VERDICT_HOLD
    assert rec.recommended == 0.30
    assert rec.evidence["severity_capped"] is True
    assert "alarm" in rec.reason
    assert "never raise" in rec.reason


def test_alarm_label_may_still_be_proposed_downward():
    """The cap is one-directional. Lowering an alarm bar is the whole
    point of adapting it — the dead zone on `person` is exactly this."""
    true_scores = _spread(0.50, 0.95, 30)
    false_scores = _spread(0.10, 0.40, 30)
    cam = {"class_severity": {"person": "alarm"}}
    rec = recommend_push(
        _stratum(true_scores, false_scores), _pairs(true_scores, false_scores), cam, PUSH
    )
    assert rec.verdict == VERDICT_LOWER
    assert rec.recommended < 0.85
    assert rec.evidence["severity_capped"] is False


# ── confidence, and the ladder-vs-live divergence ─────────────────────


def test_confidence_scales_with_the_sample():
    thin_t, thin_f = (
        _spread(0.60, 0.95, MIN_JUDGED_PER_CLASS),
        _spread(0.10, 0.45, MIN_JUDGED_PER_CLASS),
    )
    thick_t, thick_f = (
        _spread(0.60, 0.95, 4 * MIN_JUDGED_PER_CLASS),
        _spread(0.10, 0.45, 4 * MIN_JUDGED_PER_CLASS),
    )
    thin = recommend_push(_stratum(thin_t, thin_f), _pairs(thin_t, thin_f), {}, PUSH)
    thick = recommend_push(_stratum(thick_t, thick_f), _pairs(thick_t, thick_f), {}, PUSH)
    assert thin.confidence == "moderate"
    assert thick.confidence == "high"


def test_enforced_push_mirrors_the_live_consumer_not_the_ladder():
    """`_event_alert._event_ctx` reads the global label threshold and
    falls back to 0.0 — no per-camera map, no shipped defaults."""
    # A label absent from the saved config: ladder says 0.85, gate says 0.
    assert enforced_push({}, "person") == 0.0
    assert enforced_push({"labels": {"person": {"threshold": 0.7}}}, "person") == 0.7
    # A per-camera override the live gate does not read.
    assert enforced_push(PUSH, "person") == 0.85


def test_divergence_between_ladder_and_live_gate_is_surfaced():
    true_scores = _spread(0.60, 0.95, 30)
    false_scores = _spread(0.10, 0.45, 30)
    cam = {"push_thresholds": {"person": 0.60}}
    rec = recommend_push(
        _stratum(true_scores, false_scores), _pairs(true_scores, false_scores), cam, PUSH
    )
    # The ladder honours the per-camera override; the shipped push path
    # does not, and the recommendation must not hide that.
    assert rec.current == 0.60
    assert rec.enforced == 0.85
    assert rec.enforced_matches is False
    assert "live gate" in rec.reason


def test_as_dict_is_json_safe():
    import json

    true_scores = _spread(0.60, 0.95, 30)
    false_scores = _spread(0.10, 0.45, 30)
    rec = recommend_push(
        _stratum(true_scores, false_scores), _pairs(true_scores, false_scores), {}, PUSH
    )
    payload = json.loads(json.dumps(rec.as_dict()))
    assert payload["recommended"] == rec.recommended
    assert payload["evidence"]["separation"] == SEPARATION_CLEAN
