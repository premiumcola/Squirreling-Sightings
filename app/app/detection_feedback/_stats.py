"""The read side — and its willingness to say "not yet".

``judged_alerts`` answers one (camera, label) question per full read of
the file. An overview needs the whole picture from one pass, with the
sample size attached to every number it shows, plus an explicit verdict
on whether each downstream use may act on it at all.

Three downstream uses, three different bars, because they are three
different statistical questions:

* **threshold calibration** — where do confirmed-true and confirmed-false
  scores separate? A question about two distributions.
* **per-camera label veto** — is this label essentially always wrong on
  this camera? A question about one proportion, whose false positive
  suppresses real alerts, so it is judged on the 95% lower bound.
* **nearest-centroid classifier** — a question about class means, which
  needs examples per class and at least two classes to choose between.

The bars themselves live in ``_consts`` with the reasoning attached.

One thing this module must get right and its predecessor did not: the
answer rate. Compaction evicts unjudged alerts and never judged ones, so
counting what is left on disk inflates the rate every time the ledger
rolls over — and an inflated answer rate is exactly the input that lets a
"do we have enough data?" check say yes when it should not. The census
records written by ``_retention`` restore the real denominator.
"""

from __future__ import annotations

import math
from collections import Counter

from ._consts import (
    MIN_AGREEING_CORRECTIONS,
    MIN_ANSWER_RATE,
    MIN_CLASSES_FOR_CENTROID,
    MIN_EXAMPLES_PER_CLASS,
    MIN_JUDGED_FOR_VETO,
    MIN_JUDGED_PER_CLASS,
    MIN_JUDGED_PER_STRATUM,
    MIN_VETO_WRONG_RATE_LOWER,
)
from ._io import iter_records, ledger_health
from ._retention import index_records, stratum


def judged_alerts(storage_root, cam_id: str | None = None, label: str | None = None):
    """Alerts that carry a verdict, as ``(alert, correct)`` pairs.

    This is the shape threshold calibration consumes: the score the
    detector produced, and whether the user considered it real. Alerts
    with no verdict are excluded — an unanswered alert says nothing.
    A later verdict supersedes an earlier one for the same event.
    """
    idx = index_records(iter_records(storage_root))
    out = []
    for eid, alert in idx.alerts.items():
        verdict = idx.verdicts.get(eid)
        if verdict is None:
            continue
        if cam_id and alert.get("cam") != cam_id:
            continue
        if label and alert.get("label") != label:
            continue
        out.append((alert, bool(verdict.get("correct"))))
    out.sort(key=lambda p: p[0].get("ts", 0))
    return out


def _score_stats(pairs) -> dict:
    """Score distribution of ``(alert, correct)`` pairs.

    Deliberately reports counts alongside the numbers: a separation
    computed from three samples is noise, and any caller deciding to move
    a threshold must be able to see that before acting on it.
    """
    true_scores = sorted(a.get("score", 0.0) for a, ok in pairs if ok)
    false_scores = sorted(a.get("score", 0.0) for a, ok in pairs if not ok)
    return {
        "n_total": len(pairs),
        "n_true": len(true_scores),
        "n_false": len(false_scores),
        "true_min": true_scores[0] if true_scores else None,
        "true_median": true_scores[len(true_scores) // 2] if true_scores else None,
        "false_max": false_scores[-1] if false_scores else None,
        "false_median": false_scores[len(false_scores) // 2] if false_scores else None,
    }


def score_summary(storage_root, cam_id: str, label: str) -> dict:
    """Score distribution of judged alerts for one camera + label."""
    out = {"cam": cam_id, "label": label}
    out.update(_score_stats(judged_alerts(storage_root, cam_id=cam_id, label=label)))
    return out


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    """95% lower bound on a proportion. 0.0 for an empty sample.

    Wilson rather than the textbook normal interval because k/n here is
    routinely near 0 or 1, where the normal interval runs off the end of
    the scale and reports impossible confidence.
    """
    if n <= 0:
        return 0.0
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max((centre - margin) / (1 + z * z / n), 0.0)


def calibration_readiness(st: dict) -> dict:
    """Can a score threshold be moved on this stratum — and in which direction?

    ``ready`` = enough evidence to consider RAISING a threshold,
    ``can_lower`` = enough judged sub-threshold candidates to LOWER one,
    ``blockers`` = what is missing. Two directions, two bars: an alert
    that never went out cannot be judged in Telegram, so the below-the-
    bar side fills far more slowly.
    """
    blockers = []
    n_judged = st.get("n_total", 0)
    n_true = st.get("n_true", 0)
    n_false = st.get("n_false", 0)
    rate = st.get("answer_rate", 0.0)
    if n_judged < MIN_JUDGED_PER_STRATUM:
        blockers.append(f"judged {n_judged}/{MIN_JUDGED_PER_STRATUM}")
    if n_true < MIN_JUDGED_PER_CLASS:
        blockers.append(f"confirmed-true {n_true}/{MIN_JUDGED_PER_CLASS}")
    if n_false < MIN_JUDGED_PER_CLASS:
        blockers.append(f"confirmed-false {n_false}/{MIN_JUDGED_PER_CLASS}")
    if rate < MIN_ANSWER_RATE:
        blockers.append(f"answer rate {rate:.0%} < {MIN_ANSWER_RATE:.0%}")
    return {
        "ready": not blockers,
        "can_lower": st.get("n_judged_below", 0) >= MIN_JUDGED_PER_CLASS,
        "blockers": blockers,
    }


def veto_readiness(st: dict) -> dict:
    """May this (camera, label) be suppressed outright, or redirected?

    A veto that fires wrongly silences real alerts, so the test is on the
    95% lower bound of the wrong-rate, not the point estimate. A REDIRECT
    additionally needs the corrections to agree on one replacement label
    rather than merely to exist.
    """
    n_judged = st.get("n_total", 0)
    n_false = st.get("n_false", 0)
    lower = _wilson_lower(n_false, n_judged)
    blockers = []
    if n_judged < MIN_JUDGED_FOR_VETO:
        blockers.append(f"judged {n_judged}/{MIN_JUDGED_FOR_VETO}")
    if lower < MIN_VETO_WRONG_RATE_LOWER:
        blockers.append(f"wrong-rate lower bound {lower:.0%} < {MIN_VETO_WRONG_RATE_LOWER:.0%}")
    corrections = st.get("corrections") or []
    top_label, top_n = corrections[0] if corrections else (None, 0)
    return {
        "ready": not blockers,
        "wrong_rate": round(n_false / n_judged, 3) if n_judged else 0.0,
        "wrong_rate_lower": round(lower, 3),
        "blockers": blockers,
        "redirect_to": top_label if top_n >= MIN_AGREEING_CORRECTIONS else None,
        "redirect_blocker": (
            None
            if top_n >= MIN_AGREEING_CORRECTIONS
            else f"agreeing corrections {top_n}/{MIN_AGREEING_CORRECTIONS}"
        ),
    }


def centroid_readiness(examples: dict) -> dict:
    """Is there enough per-class material for a nearest-centroid classifier?

    ``examples`` maps a label to the number of confirmed examples of it:
    alerts the user confirmed as that label, plus events the user
    corrected TO that label. Aggregated across cameras, because a
    centroid is per class, not per camera.

    A hard caveat the caller must repeat: the ledger holds no pixels. The
    crops a centroid is computed over come from CORP-2, which is not
    built. These counts say the LABELS would suffice; they do not say the
    classifier can be trained today.
    """
    qualifying = sorted(lab for lab, n in examples.items() if n >= MIN_EXAMPLES_PER_CLASS)
    blockers = []
    if len(qualifying) < MIN_CLASSES_FOR_CENTROID:
        best = sorted(examples.values(), reverse=True)[:MIN_CLASSES_FOR_CENTROID]
        blockers.append(
            f"classes with >={MIN_EXAMPLES_PER_CLASS} examples: {len(qualifying)}/{MIN_CLASSES_FOR_CENTROID} (best counts: {best or [0]})"
        )
    return {
        "ready": not blockers,
        "classes": qualifying,
        "examples": dict(sorted(examples.items(), key=lambda kv: -kv[1])),
        "blockers": blockers,
        "needs_crops_from": "CORP-2",
    }


def _stratum_row(cam: str, label: str, items, evicted: int) -> dict:
    """One (camera, label) cell, with every rate on an honest denominator."""
    pairs = [(a, bool(v.get("correct"))) for a, v in items if v is not None]
    fixes = [v["corrected_label"] for _, v in items if v and v.get("corrected_label")]
    seen = len(items) + evicted
    st = {
        "cam": cam,
        "label": label,
        "n_alerts_retained": len(items),
        "n_alerts_evicted": evicted,
        # The denominator that matters: alerts that ever happened, not
        # alerts still on disk. Retention keeps every judged alert and
        # evicts only unjudged ones, so without `evicted` this rate
        # climbs with every compaction and the gate below can never say
        # no.
        "n_alerts": seen,
    }
    st.update(_score_stats(pairs))
    st["answer_rate"] = round(len(pairs) / seen, 3) if seen else 0.0
    st["n_below"] = sum(1 for a, _ in items if not a.get("passed_threshold", True))
    st["n_judged_below"] = sum(1 for a, _ in pairs if not a.get("passed_threshold", True))
    st["corrections"] = Counter(fixes).most_common(3)
    st.update(calibration_readiness(st))
    st["veto"] = veto_readiness(st)
    return st


def _class_examples(idx) -> dict:
    """Confirmed examples per class, across all cameras.

    A confirmed-true alert is an example of its own label; a correction
    is an example of the label it was corrected TO — including when the
    corrected event has no alert record, which is common for cameras
    whose pushes are muted.
    """
    counts: Counter = Counter()
    for eid, verdict in idx.verdicts.items():
        fixed = verdict.get("corrected_label")
        if fixed:
            counts[fixed] += 1
            continue
        alert = idx.alerts.get(eid)
        if alert is not None and verdict.get("correct"):
            counts[alert.get("label") or "?"] += 1
    return dict(counts)


def corpus_stats(storage_root) -> dict:
    """One pass over the ledger, rolled up per camera and label."""
    idx = index_records(iter_records(storage_root))
    grouped: dict = {}
    for eid, alert in idx.alerts.items():
        grouped.setdefault(stratum(alert), []).append((alert, idx.verdicts.get(eid)))
    # A stratum whose retained alerts were all evicted still exists — its
    # census entry is the only trace, and dropping it would hide the very
    # alerts that make the global rate honest.
    keys = sorted(set(grouped) | set(idx.census))
    strata = [
        _stratum_row(cam, lab, grouped.get((cam, lab), []), idx.census.get((cam, lab), 0))
        for cam, lab in keys
    ]

    n_judged = sum(1 for eid in idx.alerts if eid in idx.verdicts)
    n_seen = sum(s["n_alerts"] for s in strata)
    protected = n_judged * 2 + len(idx.orphan_verdicts()) + len(idx.passthrough)
    health = ledger_health(storage_root)
    return {
        "n_alerts": n_seen,
        "n_alerts_retained": len(idx.alerts),
        "n_alerts_evicted": sum(idx.census.values()),
        "n_verdicts": len(idx.verdicts),
        "n_judged": n_judged,
        "answer_rate": round(n_judged / n_seen, 3) if n_seen else 0.0,
        "orphan_verdicts": len(idx.orphan_verdicts()),
        "unjoinable_records": idx.unjoinable,
        "unknown_kind_records": len(idx.passthrough),
        "protected_records": protected,
        "over_record_budget": protected > health["max_retained_records"],
        "strata": strata,
        "centroid": centroid_readiness(_class_examples(idx)),
        "health": health,
    }
