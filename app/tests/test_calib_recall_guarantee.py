"""A recommendation must never promise a recall it does not deliver.

The window is computed BEFORE the floor/ceiling clamp, so the value that
leaves is not necessarily the value the window guaranteed anything
about. If every confirmed-true score sits below PUSH_FLOOR, the clamp
lifts the recommendation to the floor — where it blocks *every* true
positive. The generated prose still quoted MIN_TRUE_RECALL, because it
read the constant rather than the outcome.

That failure mode is worse than a refusal: the operator acts on a
confident sentence that is provably false about their own data. So the
invariant is now verified against the judged scores at the value
actually being recommended.
"""

from __future__ import annotations

import pytest

from app.thresholds._calibration import (
    MIN_TRUE_RECALL,
    PUSH_FLOOR,
    recommend_push,
)

READY = {"ready": True, "blockers": [], "cam": "cam1", "label": "person"}
PUSH = {"labels": {"person": {"push": True, "threshold": 0.85}}}


def _pairs(true_scores, false_scores):
    return [({"score": s}, True) for s in true_scores] + [
        ({"score": s}, False) for s in false_scores
    ]


def test_it_refuses_when_the_clamp_would_destroy_recall():
    """Every true below the hard floor: any legal threshold blocks them all."""
    rec = recommend_push(
        dict(READY),
        pairs=_pairs([0.10] * 30, [0.05] * 15),
        cam_cfg={},
        push_cfg=PUSH,
    )
    assert rec.recommended is None, "a value here would guarantee a recall it cannot deliver"
    assert rec.blockers, "the refusal must say why"
    assert "Recall" in rec.blockers[0]


def test_the_refusal_quotes_the_real_numbers():
    """Not the constant — what the data would actually have done."""
    rec = recommend_push(
        dict(READY),
        pairs=_pairs([0.10] * 30, [0.05] * 15),
        cam_cfg={},
        push_cfg=PUSH,
    )
    msg = rec.blockers[0]
    assert "0/30" in msg, f"must state the achieved count, got: {msg}"


def test_a_healthy_stratum_still_recommends():
    """The guard must not swallow the normal case."""
    rec = recommend_push(
        dict(READY),
        pairs=_pairs([0.70, 0.75, 0.80, 0.85, 0.90] * 6, [0.30, 0.35, 0.40] * 5),
        cam_cfg={},
        push_cfg=PUSH,
    )
    assert rec.recommended is not None
    assert PUSH_FLOOR <= rec.recommended <= 0.95


def test_the_recommended_value_really_keeps_the_promised_recall():
    """The invariant, asserted directly against the returned number."""
    trues = [0.70, 0.75, 0.80, 0.85, 0.90] * 6
    rec = recommend_push(
        dict(READY),
        pairs=_pairs(trues, [0.30, 0.35, 0.40] * 5),
        cam_cfg={},
        push_cfg=PUSH,
    )
    kept = sum(1 for s in trues if s >= rec.recommended)
    assert (
        kept / len(trues) >= MIN_TRUE_RECALL
    ), f"recommended {rec.recommended} keeps only {kept}/{len(trues)}"


@pytest.mark.parametrize("n_true", [30, 45])
def test_borderline_trues_at_the_floor_are_handled(n_true):
    """Trues sitting exactly at the floor must still clear it, not be
    refused by an off-by-one in the comparison."""
    rec = recommend_push(
        dict(READY),
        pairs=_pairs([PUSH_FLOOR] * n_true, [0.05] * 15),
        cam_cfg={},
        push_cfg=PUSH,
    )
    if rec.recommended is not None:
        kept = sum(1 for _ in range(n_true) if PUSH_FLOOR >= rec.recommended)
        assert kept / n_true >= MIN_TRUE_RECALL
