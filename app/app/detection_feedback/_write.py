"""The two record writers. Both best-effort: a diagnostic write must
never break a capture loop or drop a real alert."""

from __future__ import annotations

from ._consts import KIND_ALERT, KIND_VERDICT
from ._io import append


def record_alert(
    storage_root,
    *,
    cam_id: str,
    event_id: str,
    label: str,
    score: float,
    threshold: float,
    ts: float,
    detections=None,
    passed_threshold: bool | None = None,
) -> bool:
    """Record that an alert was CONSIDERED, with the numbers behind it.

    Considered, not sent — and the distinction decides whether this
    ledger is useful at all. Written behind the push gates, it would
    only ever contain events that cleared the threshold: for `person`
    nothing below 0.85. A calibration fed on that can raise a threshold
    and can never lower one, which is the direction that actually
    matters here. So this must be called BEFORE the gates, while the
    score of a *rejected* candidate is still observable.

    It is still called below the mute and push-flag gates, which is why
    plenty of verdicts have no alert record to join to — see
    ``_retention`` for why those verdicts are kept anyway.

    `passed_threshold` records which side of the bar it fell on.
    `detections` is the full per-frame list so a later calibration can
    see what else was in the frame — a "person" alert that also carried
    a 0.4 "dog" is a different data point from a clean one.
    """
    dets = []
    for d in detections or []:
        try:
            dets.append(
                {
                    "label": getattr(d, "label", None) or d.get("label"),
                    "score": round(float(getattr(d, "score", None) or d.get("score", 0.0)), 4),
                }
            )
        except Exception:
            continue
    return append(
        storage_root,
        {
            "kind": KIND_ALERT,
            "ts": round(float(ts), 1),
            "cam": cam_id,
            "event_id": event_id,
            "label": label,
            "score": round(float(score), 4),
            "threshold": round(float(threshold), 4),
            "passed_threshold": (
                bool(passed_threshold)
                if passed_threshold is not None
                else float(score) >= float(threshold)
            ),
            "detections": dets,
        },
    )


def record_verdict(
    storage_root,
    *,
    event_id: str,
    correct: bool,
    ts: float,
    corrected_label: str | None = None,
    source: str = "unknown",
    cam_id: str | None = None,
) -> bool:
    """Record the user's judgement on an event.

    `source` names the surface it came from (telegram / web / api) so a
    later analysis can tell a deliberate tap apart from a bulk action.
    `corrected_label` carries "it was actually a dog" when the user says
    so — that is the signal a per-camera label veto is built from, and
    it is useful even when no alert record exists to join to.
    """
    return append(
        storage_root,
        {
            "kind": KIND_VERDICT,
            "ts": round(float(ts), 1),
            "event_id": event_id,
            "cam": cam_id,
            "correct": bool(correct),
            "corrected_label": corrected_label,
            "source": source,
        },
    )
