"""C4 · append-only ledger of alerts and the user's verdicts on them.

Everything in the lower half of the tuning board — adaptive thresholds,
targeted follow-up questions, background learning, processing user
corrections — needs one thing that did not exist: a durable record
pairing *what the detector said* with *what the user said about it*.

Today the judgement surfaces exist but lead nowhere. `event["confirmed"]`
has no reader anywhere in the Python code, and the Telegram verdict
stores neither camera nor label nor the score that produced it — so even
with a thousand taps there is nothing to calibrate against.

Two record kinds, joined by ``event_id``:

  ``alert``   written when an alert is SENT, carrying the camera, the
              primary label, its score, the threshold it had to clear,
              and every detection in the frame. Written at send time
              precisely because the score is only in hand there.
  ``verdict`` written when the user judges that event — right / wrong,
              and optionally what it really was.

Design constraints, and why:

* **Append-only JSONL.** No read-modify-write, so concurrent writers from
  the camera threads, the Telegram callback thread and HTTP handlers
  cannot corrupt each other or lose a record to a torn write.
* **Under ``storage/_diag/``, not in the event folders.** `cleanup_old`
  deletes events by age; a corpus living beside them would dissolve
  inside the retention window. This is the durable artefact.
* **Best-effort.** Any failure is swallowed and logged. A diagnostic
  write must never break a capture loop or drop a real alert.

Mirrors the conventions of ``motion_samples.py``, which does the same
job for the motion gate.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_LEDGER_NAME = "detection_feedback.jsonl"

# Roll over at ~8 MB. At a few hundred bytes per record that is well over
# a hundred thousand events — far more than calibration needs — while
# staying small enough to read fully in one pass.
_MAX_BYTES = 8 * 1024 * 1024

# Serialises the size check + append. The append itself would be atomic
# for short lines on POSIX, but the rotation is a read-modify-write and
# needs the lock regardless.
_write_lock = threading.Lock()


def ledger_path(storage_root) -> Path:
    return Path(storage_root or "storage") / "_diag" / _LEDGER_NAME


def _append(storage_root, record: dict) -> bool:
    """Append one record. Returns True on success; never raises."""
    try:
        path = ledger_path(storage_root)
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > _MAX_BYTES:
                # Keep exactly one previous generation. Losing the oldest
                # records is acceptable; losing the newest is not.
                path.replace(path.with_suffix(path.suffix + ".1"))
            # If the previous append was cut short (power loss, full
            # disk) the file does not end in a newline, and writing
            # straight on would fuse the torn fragment with this record
            # and destroy BOTH. Start a fresh line first; the fragment
            # is then dropped by iter_records on its own.
            needs_newline = False
            if path.exists() and path.stat().st_size:
                with open(path, "rb") as probe:
                    probe.seek(-1, 2)
                    needs_newline = probe.read(1) != b"\n"
            with open(path, "a", encoding="utf-8") as fh:
                if needs_newline:
                    fh.write("\n")
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        log.warning("[storage] detection-feedback write failed: %s", e)
        return False


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
) -> bool:
    """Record that an alert was sent, with the numbers behind it.

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
    return _append(
        storage_root,
        {
            "kind": "alert",
            "ts": round(float(ts), 1),
            "cam": cam_id,
            "event_id": event_id,
            "label": label,
            "score": round(float(score), 4),
            "threshold": round(float(threshold), 4),
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
    so — that is the signal a per-camera label veto is built from.
    """
    return _append(
        storage_root,
        {
            "kind": "verdict",
            "ts": round(float(ts), 1),
            "event_id": event_id,
            "cam": cam_id,
            "correct": bool(correct),
            "corrected_label": corrected_label,
            "source": source,
        },
    )


def iter_records(storage_root):
    """Yield every record, oldest generation first. Skips unparseable lines.

    A truncated final line (power loss mid-append) must not make the
    whole ledger unreadable — that would defeat the point of choosing an
    append-only format.
    """
    path = ledger_path(storage_root)
    for candidate in (path.with_suffix(path.suffix + ".1"), path):
        if not candidate.exists():
            continue
        try:
            with open(candidate, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(rec, dict):
                        yield rec
        except Exception as e:
            log.warning("[storage] detection-feedback read failed (%s): %s", candidate.name, e)


def judged_alerts(storage_root, cam_id: str | None = None, label: str | None = None):
    """Alerts that carry a verdict, as ``(alert, correct)`` pairs.

    This is the shape threshold calibration consumes: the score the
    detector produced, and whether the user considered it real. Alerts
    with no verdict are excluded — an unanswered alert says nothing.
    A later verdict supersedes an earlier one for the same event.
    """
    alerts: dict[str, dict] = {}
    verdicts: dict[str, bool] = {}
    for rec in iter_records(storage_root):
        eid = rec.get("event_id")
        if not eid:
            continue
        if rec.get("kind") == "alert":
            alerts[eid] = rec
        elif rec.get("kind") == "verdict":
            verdicts[eid] = bool(rec.get("correct"))

    out = []
    for eid, alert in alerts.items():
        if eid not in verdicts:
            continue
        if cam_id and alert.get("cam") != cam_id:
            continue
        if label and alert.get("label") != label:
            continue
        out.append((alert, verdicts[eid]))
    out.sort(key=lambda p: p[0].get("ts", 0))
    return out


def score_summary(storage_root, cam_id: str, label: str) -> dict:
    """Score distribution of judged alerts for one camera + label.

    Deliberately reports counts alongside the numbers: a separation
    computed from three samples is noise, and any caller deciding to move
    a threshold must be able to see that before acting on it.
    """
    pairs = judged_alerts(storage_root, cam_id=cam_id, label=label)
    true_scores = sorted(a["score"] for a, ok in pairs if ok)
    false_scores = sorted(a["score"] for a, ok in pairs if not ok)
    return {
        "cam": cam_id,
        "label": label,
        "n_total": len(pairs),
        "n_true": len(true_scores),
        "n_false": len(false_scores),
        "true_min": true_scores[0] if true_scores else None,
        "true_median": true_scores[len(true_scores) // 2] if true_scores else None,
        "false_max": false_scores[-1] if false_scores else None,
        "false_median": false_scores[len(false_scores) // 2] if false_scores else None,
    }
