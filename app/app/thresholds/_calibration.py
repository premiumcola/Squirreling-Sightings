"""THR-2 · ADVISORY push-threshold calibration. Public via ``thresholds``.

The first thing in the tree that CONSUMES the verdict corpus. Until this
module existed, ``detection_feedback`` wrote a ledger of alerts and user
judgements that only the operator report ever read back, and the four
board categories that depend on learning from it had nothing to stand
on.

What it does NOT do is apply anything — see the note below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# The evidence policy lives in the ledger package with its reasoning
# attached, and is imported rather than restated: `_consts` says out
# loud that the report script, an API and any calibration must apply the
# SAME bar instead of three guesses. This module is that calibration.
from ..detection_feedback import MIN_JUDGED_PER_CLASS
from ..tracker_core._consts import TRACK_FLOOR_SCORE
from ._ladder import _sub, resolve_effective

# Everything below reads the verdict corpus and PROPOSES a push
# threshold. Nothing here applies one. ``resolve_effective``'s
# ``adapted`` layer is where an applied proposal would enter, and it is
# still fed by nobody — deliberately. That is the whole difference
# between a calibration that can be reviewed and one that changes the
# system while the operator is asleep.
#
# These functions stay pure: the caller reads the ledger
# (``detection_feedback.corpus_stats`` / ``judged_alerts``) and hands the
# rows in. thresholds.py keeps doing no I/O, and the tests can drive the
# whole thing from literal samples.

# Hard rails the proposal may never leave.
#
# FLOOR — the raw detector floor. Nothing below it is ever reported by
#   the detector at all, so a push threshold under it is not a low bar,
#   it is indistinguishable from 0.0. "Push everything" is a decision to
#   express with the push flag, not with a decimal.
# CEILING — detection runs on CPU (the Coral does not compute), and a
#   stock SSD-MobileNet rarely clears 0.95 on anything. A threshold
#   above it is an off switch wearing a decimal point, and switching a
#   label off is the operator's call, never a calibration's.
PUSH_FLOOR = TRACK_FLOOR_SCORE
PUSH_CEILING = 0.95

# The share of user-confirmed TRUE sightings a proposal must keep.
#
# This asymmetry is what makes the recommender usable on a security
# camera: a false alarm costs a glance at a phone, a missed sighting
# costs the entire reason the camera exists. 95% means the proposal may
# sacrifice at most one confirmed sighting in twenty — and at the
# minimum sample size (MIN_JUDGED_PER_CLASS = 20 confirmed-true) that is
# literally one.
MIN_TRUE_RECALL = 0.95

# The ``class_severity`` value that marks a label as a security alarm.
# On such a label the recommender may LOWER the bar and never raise it.
SEVERITY_ALARM = "alarm"

VERDICT_INSUFFICIENT = "insufficient_data"
VERDICT_HOLD = "hold"
VERDICT_LOWER = "lower"
VERDICT_RAISE = "raise"

SEPARATION_CLEAN = "separable"
SEPARATION_OVERLAP = "overlap"

CONFIDENCE_NONE = "none"
CONFIDENCE_LOW = "low"
CONFIDENCE_MODERATE = "moderate"
CONFIDENCE_HIGH = "high"


@dataclass(frozen=True)
class PushRecommendation:
    """A proposal, the evidence under it — or a refusal to make one.

    ``recommended`` is None whenever ``verdict`` is
    :data:`VERDICT_INSUFFICIENT`. That is the normal state of a fresh
    install and it is not an error: ``reason`` then says in words what
    is missing, because a number handed over at n=8 is worse than no
    number at all.
    """

    cam: str
    label: str
    current: float
    current_source: str
    enforced: float
    enforced_matches: bool
    push_enabled: bool
    severity: str
    verdict: str
    recommended: float | None
    reason: str
    confidence: str
    blockers: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """JSON-safe view for the read-only API surface."""
        return {
            "cam": self.cam,
            "label": self.label,
            "current": self.current,
            "current_source": self.current_source,
            "enforced": self.enforced,
            "enforced_matches": self.enforced_matches,
            "push_enabled": self.push_enabled,
            "severity": self.severity,
            "verdict": self.verdict,
            "recommended": self.recommended,
            "reason": self.reason,
            "confidence": self.confidence,
            "blockers": list(self.blockers),
            "evidence": dict(self.evidence),
        }


def enforced_push(push_cfg: dict | None, label: str) -> float:
    """The push threshold the LIVE gate applies today.

    Deliberately NOT ``resolve_effective(...).push``. The shipped
    consumer — ``telegram_bot/_outbound/_event_alert._event_ctx`` —
    reads ``telegram.push.labels[<label>].threshold`` and falls back to
    **0.0**, full stop: it consults neither the per-camera
    ``push_thresholds`` map nor ``TELEGRAM_PUSH_DEFAULTS``. So for a
    label missing from the saved config the ladder here says 0.85 while
    the live gate says "let everything through", and a per-camera
    override the operator typed is inert — ``settings/_consts`` says so
    out loud: the key "is settable and deliberately inert" until THR-3
    switches the consumer over.

    Reporting only the ladder value would print a number the system does
    not use. Both are reported side by side, with ``enforced_matches``
    flagging the divergence, rather than papering over it here.
    """
    return float(_sub(_sub(push_cfg or {}, "labels"), label).get("threshold", 0.0) or 0.0)


def _floor2(x: float) -> float:
    """Round DOWN to two decimals.

    A threshold must never drift UP by rounding — that silently drops a
    sighting the sample proved it would keep.
    """
    return math.floor(x * 100.0) / 100.0


def _split_scores(pairs) -> tuple:
    """``judged_alerts()`` output → sorted confirmed-true / -false scores."""
    true_scores = sorted(float(a.get("score") or 0.0) for a, ok in pairs if ok)
    false_scores = sorted(float(a.get("score") or 0.0) for a, ok in pairs if not ok)
    return true_scores, false_scores


def _window(true_scores: list, false_scores: list) -> tuple:
    """The ``(lo, hi)`` band of thresholds worth proposing.

    ``hi`` — the highest bar that still keeps :data:`MIN_TRUE_RECALL` of
    the confirmed-true scores. ``lo`` — one hundredth above the highest
    confirmed-false score, i.e. the lowest bar that blocks every judged
    false alarm. ``lo > hi`` means no single threshold does both: the
    two classes overlap in this sample.
    """
    n = len(true_scores)
    sacrifice = int(math.floor(n * (1.0 - MIN_TRUE_RECALL)))
    hi = _floor2(true_scores[min(sacrifice, n - 1)])
    lo = round(_floor2(false_scores[-1]) + 0.01, 2) if false_scores else PUSH_FLOOR
    return lo, hi


def _simulate(pairs, threshold: float) -> dict:
    """What a threshold would have done to the judged alerts on record.

    The most convincing evidence line there is: not a distribution
    statistic but "this bar would have passed 38 of your 40 real
    sightings and stopped 17 of your 22 false ones".
    """
    return {
        "kept_true": sum(1 for a, ok in pairs if ok and float(a.get("score") or 0.0) >= threshold),
        "blocked_false": sum(
            1 for a, ok in pairs if not ok and float(a.get("score") or 0.0) < threshold
        ),
    }


def _confidence(n_true: int, n_false: int, separation: str) -> str:
    """How far the proposal deserves to be trusted, in one word."""
    ample = min(n_true, n_false) >= 2 * MIN_JUDGED_PER_CLASS
    if separation == SEPARATION_CLEAN:
        return CONFIDENCE_HIGH if ample else CONFIDENCE_MODERATE
    return CONFIDENCE_MODERATE if ample else CONFIDENCE_LOW


def _context(stratum: dict, cam_cfg: dict | None, push_cfg: dict | None) -> dict:
    """The read-only surroundings every recommendation carries, ready or not."""
    label = str(stratum.get("label") or "?")
    eff = resolve_effective(cam_cfg, push_cfg, label)
    live = enforced_push(push_cfg, label)
    return {
        "cam": str(stratum.get("cam") or "?"),
        "label": label,
        "current": eff.push,
        "current_source": eff.source["push"],
        "enforced": live,
        "enforced_matches": abs(live - eff.push) < 1e-9,
        "push_enabled": eff.push_enabled,
        "severity": str(_sub(cam_cfg or {}, "class_severity").get(label) or "").lower(),
    }


def _counts(stratum: dict) -> dict:
    """The sample sizes, echoed into every recommendation including a refusal."""
    return {
        "n_judged": int(stratum.get("n_total") or 0),
        "n_true": int(stratum.get("n_true") or 0),
        "n_false": int(stratum.get("n_false") or 0),
        "answer_rate": stratum.get("answer_rate"),
        "true_min": stratum.get("true_min"),
        "true_median": stratum.get("true_median"),
        "false_max": stratum.get("false_max"),
        "false_median": stratum.get("false_median"),
    }


def _refusal(ctx: dict, blockers: list, evidence: dict) -> PushRecommendation:
    """Say "not yet" in words, and say exactly what is still missing."""
    reason = (
        "Not enough judged alerts to propose a threshold for `{label}` on `{cam}` yet — "
        "{missing}. The current bar of {current:.2f} stays. A separation computed from a "
        "handful of samples is noise wearing a decimal point, so this refuses rather than "
        "guesses.".format(
            label=ctx["label"],
            cam=ctx["cam"],
            missing="; ".join(blockers) if blockers else "no judged alerts on record",
            current=ctx["current"],
        )
    )
    return PushRecommendation(
        verdict=VERDICT_INSUFFICIENT,
        recommended=None,
        reason=reason,
        confidence=CONFIDENCE_NONE,
        blockers=blockers,
        evidence=evidence,
        **ctx,
    )


def _explain(ctx: dict, value: float, ev: dict) -> str:
    """The proposal in sentences — which samples, what separation, how sure."""
    if ev["separation"] == SEPARATION_CLEAN:
        head = (
            "The {n_true} confirmed-true and {n_false} confirmed-false judgements separate: "
            "no judged false alarm scored above {false_max:.2f}, and keeping {recall:.0%} of "
            "the confirmed sightings allows a bar as high as {hi:.2f}. Any threshold in "
            "[{lo:.2f}, {hi:.2f}] does both; {value:.2f} is the middle of that window."
        )
    else:
        head = (
            "The two classes OVERLAP in these {n_true} confirmed-true and {n_false} "
            "confirmed-false judgements — false alarms reach {false_max:.2f} while a bar "
            "keeping {recall:.0%} of the real sightings sits at {hi:.2f}, so no threshold "
            "separates them cleanly. {value:.2f} is the highest bar that still keeps the "
            "sightings; the false alarms it lets through cannot be removed by a threshold "
            "at all and need a label veto or a better classifier."
        )
    parts = [
        head.format(
            n_true=ev["n_true"],
            n_false=ev["n_false"],
            false_max=ev["false_max"] if ev["false_max"] is not None else 0.0,
            recall=MIN_TRUE_RECALL,
            lo=ev["window_low"],
            hi=ev["window_high"],
            value=value,
        ),
        "On the judged record it would pass {}/{} real sightings and stop {}/{} false ones; "
        "today's {:.2f} passes {}/{} and stops {}/{}.".format(
            ev["at_recommended"]["kept_true"],
            ev["n_true"],
            ev["at_recommended"]["blocked_false"],
            ev["n_false"],
            ctx["current"],
            ev["at_current"]["kept_true"],
            ev["n_true"],
            ev["at_current"]["blocked_false"],
            ev["n_false"],
        ),
    ]
    if ev["severity_capped"]:
        parts.append(
            "Capped at the current value: `{}` is marked `{}` on this camera, and adaptation "
            "may lower the bar on a security label but never raise it — a missed intruder "
            "costs more than a false alarm.".format(ctx["label"], SEVERITY_ALARM)
        )
    if ev["clamped"]:
        parts.append(
            "Clamped into the hard range [{:.2f}, {:.2f}]: below the floor a threshold is "
            "indistinguishable from off, above the ceiling it IS off.".format(
                PUSH_FLOOR, PUSH_CEILING
            )
        )
    if not ctx["push_enabled"]:
        parts.append(
            "Advisory only for now — `{}` has push disabled globally, so no value here "
            "changes anything until that flag is turned on.".format(ctx["label"])
        )
    if not ctx["enforced_matches"]:
        parts.append(
            "Heads up: the live gate currently enforces {:.2f}, not the {:.2f} this ladder "
            "resolves — the shipped consumer reads only the global telegram.push value.".format(
                ctx["enforced"], ctx["current"]
            )
        )
    return " ".join(parts)


def recommend_push(
    stratum: dict,
    pairs=None,
    cam_cfg: dict | None = None,
    push_cfg: dict | None = None,
) -> PushRecommendation:
    """Propose a push threshold for one (camera, label) — or refuse to.

    ``stratum`` — one row out of ``detection_feedback.corpus_stats()``
    ``["strata"]``. Its ``ready`` / ``blockers`` fields ARE the evidence
    bar (``MIN_JUDGED_PER_STRATUM`` judged, ``MIN_JUDGED_PER_CLASS`` of
    each verdict, ``MIN_ANSWER_RATE`` answered); this function does not
    invent a second one.
    ``pairs`` — ``detection_feedback.judged_alerts(root, cam, label)``.
    Only needed when the stratum clears the bar; the score lists are
    what a threshold is actually computed from.

    Never applies anything. The result is advisory, and on a label
    marked ``alarm`` in ``class_severity`` it can only ever propose
    lowering the bar.
    """
    ctx = _context(stratum, cam_cfg, push_cfg)
    evidence = _counts(stratum)
    blockers = list(stratum.get("blockers") or [])
    true_scores, false_scores = _split_scores(pairs or [])
    if stratum.get("ready") is None:
        blockers.append("stratum row carries no readiness verdict")
    elif stratum.get("ready") and not (true_scores and false_scores):
        blockers.append("judged scores not supplied — pass judged_alerts() output in `pairs`")
    if blockers or not stratum.get("ready"):
        return _refusal(ctx, blockers, evidence)

    lo, hi = _window(true_scores, false_scores)
    separable = lo <= hi
    raw = round((lo + hi) / 2.0, 2) if separable else hi
    value = round(max(PUSH_FLOOR, min(PUSH_CEILING, raw)), 2)
    capped = ctx["severity"] == SEVERITY_ALARM and value > ctx["current"]
    if capped:
        value = ctx["current"]

    # The clamps above are applied AFTER the window was computed, so the
    # value that leaves here is not necessarily the value the window
    # guaranteed anything about. Concretely: if every confirmed-true
    # score sits below PUSH_FLOOR, the clamp lifts the recommendation to
    # the floor — where it now blocks *every* true positive, a recall of
    # zero. The prose downstream would still quote MIN_TRUE_RECALL,
    # because it reads the constant rather than the outcome.
    #
    # A calibration tool that states a false guarantee is worse than one
    # that refuses: the operator acts on it. So verify the invariant
    # against the data at the value actually being recommended, and
    # refuse when it no longer holds.
    achieved = _simulate(pairs, value)
    n_true = len(true_scores)
    recall = (achieved["kept_true"] / n_true) if n_true else 0.0
    if recall < MIN_TRUE_RECALL:
        return _refusal(
            ctx,
            [
                "kein Schwellwert erfüllt die Recall-Zusage: bei {:.2f} blieben nur "
                "{}/{} bestätigte Treffer über ({:.0%} statt {:.0%}). Die Grenzwerte "
                "{:.2f}–{:.2f} und die beurteilten Scores sind hier unvereinbar.".format(
                    value,
                    achieved["kept_true"],
                    n_true,
                    recall,
                    MIN_TRUE_RECALL,
                    PUSH_FLOOR,
                    PUSH_CEILING,
                )
            ],
            evidence,
        )
    evidence.update(
        {
            # Restated from the score lists actually used, not from the
            # stratum row's own summary. The two come from the same
            # ledger and should agree, but the sentences below quote
            # these numbers as the basis of a threshold — they have to
            # be the numbers the threshold was computed from.
            "n_true": len(true_scores),
            "n_false": len(false_scores),
            "true_min": true_scores[0],
            "false_max": false_scores[-1],
            "separation": SEPARATION_CLEAN if separable else SEPARATION_OVERLAP,
            "window_low": lo,
            "window_high": hi,
            "min_true_recall": MIN_TRUE_RECALL,
            "clamped": abs(value - raw) > 1e-9 and not capped,
            "severity_capped": capped,
            "at_current": _simulate(pairs, ctx["current"]),
            "at_recommended": _simulate(pairs, value),
        }
    )
    delta = value - ctx["current"]
    verdict = VERDICT_HOLD
    if delta <= -0.005:
        verdict = VERDICT_LOWER
    elif delta >= 0.005:
        verdict = VERDICT_RAISE
    return PushRecommendation(
        verdict=verdict,
        recommended=value,
        reason=_explain(ctx, value, evidence),
        confidence=_confidence(evidence["n_true"], evidence["n_false"], evidence["separation"]),
        blockers=[],
        evidence=evidence,
        **ctx,
    )
