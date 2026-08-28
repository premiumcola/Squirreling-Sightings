"""The 03:30 run — the only writer of the ladder's ``adapted`` layer.

One nightly job, not one recomputation per answer. Recomputing on every
tap would make the net twitch, make the archive unreadable, and spend
the 24 h / 5-point movement budget in minutes. A tap is durable
immediately; what it MEANS is decided once a night.

Per (camera, class):

    corpus_stats → resolve_stratum  (per-camera, else pooled per P3)
      ├─ not ready       → archive "gezählt, 24 von 50"      pending
      ├─ ready, pinned   → archive "Vorschlag 58, manuell"   pinned
      └─ ready, free:
           recommend_push(...)          incl. the recall re-check
           E_neu = clamp(e_from_push, E_alt ± 5, rails, person floor)
           if E_neu == E_alt → "bestätigt, keine Änderung"   confirmed
           else              → write net_adapted             changed

An answer that changed nothing is RECORDED as "bestätigt, keine
Änderung" rather than omitted: silence is indistinguishable from a bug,
and the operator asked whether their judgement was an optimisation.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from .. import net_archive
from ..detection_feedback import (
    MIN_JUDGED_PER_STRATUM,
    corpus_stats,
    judged_alerts,
    resolve_stratum,
)
from ._apply import (
    AUTO_E_FLOOR_PERSON_SECURITY,
    AXIS_ORDER,
    LEARNER_MIN_INTERVAL_S,
    clamp_e,
    clamp_learner_e,
    e_from_push,
    effective_e,
    person_floor_applies,
    pinned_e,
    push_for,
    thresholds_for,
)
from ._calibration import _simulate, recommend_push

log = logging.getLogger(__name__)


def camera_axes(cam_cfg: dict) -> list:
    """The classes this camera has an axis for, in the fixed global order.

    One axis per class enabled in the camera's Klassen-Filter. That
    control stays — it is a "what do I care about" choice, not a number
    — and it becomes the axis selector.
    """
    enabled = [c for c in (cam_cfg.get("object_filter") or []) if isinstance(c, str)]
    if not enabled:
        return [lab for lab in AXIS_ORDER if lab in ("person", "cat", "bird", "squirrel")]
    return [lab for lab in AXIS_ORDER if lab in set(enabled)]


def _due(cam_cfg: dict, label: str, now: float) -> bool:
    """One run per 24 h per (camera, class)."""
    entry = (cam_cfg.get("net_adapted") or {}).get(label)
    if not isinstance(entry, dict):
        return True
    try:
        return now - float(entry.get("ts") or 0.0) >= LEARNER_MIN_INTERVAL_S
    except (TypeError, ValueError):
        return True


def _pinned_on(cam_cfg: dict, label: str) -> str | None:
    entry = (cam_cfg.get("net_pin") or {}).get(label)
    if not isinstance(entry, dict):
        return None
    try:
        return datetime.fromtimestamp(float(entry["ts"])).strftime("%d.%m.")
    except Exception:
        return None


def _record_ids(storage_root, cam_id: str, label: str) -> list:
    """Archive records for this stratum that still await a consequence.

    The 03:30 job's output has to land on the cards the operator will
    actually open, which are the ones carrying a verdict and still
    marked ``pending``.
    """
    page = net_archive.list_records(storage_root, cam=cam_id, label=label, limit=10_000)
    return [
        row["event_id"]
        for row in page["items"]
        if row.get("verdict") and row.get("state") == net_archive.STATE_PENDING
    ]


def _write_consequence(storage_root, cam_id, label, state, reason, before=None, after=None):
    payload = {
        "state": state,
        "label": label,
        "cam_id": cam_id,
        "reason_de": reason,
        "before": before,
        "after": after,
    }
    for eid in _record_ids(storage_root, cam_id, label):
        net_archive.append_consequence(storage_root, eid, payload)


def evaluate_axis(storage_root, cam_cfg: dict, push_cfg: dict, label: str, stats: dict) -> dict:
    """Decide one (camera, class). Pure decision + archive prose; the
    caller performs the settings write.

    Returns ``{state, e_before, e_after, reason, write}``.
    """
    cam_id = cam_cfg.get("id") or "?"
    cam_name = cam_cfg.get("name") or cam_id
    stratum = resolve_stratum(stats, cam_id, label)
    scope = stratum.get("scope")
    e_before = effective_e(cam_cfg, label)
    if not stratum.get("ready"):
        return {
            "state": net_archive.STATE_PENDING,
            "e_before": e_before,
            "e_after": e_before,
            "write": False,
            "reason": net_archive.sentence_pending(
                label=label,
                cam_name=cam_name,
                judged=int(stratum.get("n_total") or 0),
                needed=MIN_JUDGED_PER_STRATUM,
            ),
        }
    pairs = judged_alerts(
        storage_root, cam_id=None if scope == net_archive.SCOPE_POOLED else cam_id, label=label
    )
    rec = recommend_push(stratum, pairs, cam_cfg, push_cfg)
    if rec.recommended is None:
        return {
            "state": net_archive.STATE_PENDING,
            "e_before": e_before,
            "e_after": e_before,
            "write": False,
            "reason": net_archive.sentence_pending(
                label=label,
                cam_name=cam_name,
                judged=int(stratum.get("n_total") or 0),
                needed=MIN_JUDGED_PER_STRATUM,
            ),
        }
    wanted = e_from_push(label, rec.recommended)
    e_after = clamp_learner_e(cam_cfg, label, e_before, wanted)
    floor_held = (
        {"wanted": wanted, "floor": AUTO_E_FLOOR_PERSON_SECURITY}
        if person_floor_applies(cam_cfg, label) and wanted < AUTO_E_FLOOR_PERSON_SECURITY
        else None
    )
    if pinned_e(cam_cfg, label) is not None:
        return {
            "state": net_archive.STATE_PINNED,
            "e_before": e_before,
            "e_after": e_before,
            "write": False,
            "proposal": e_after,
            "reason": net_archive.sentence_pinned(
                pinned_on=_pinned_on(cam_cfg, label), proposal=e_after
            ),
        }
    push_before, push_after = push_for(label, e_before), push_for(label, e_after)
    if e_after == e_before:
        return {
            "state": net_archive.STATE_CONFIRMED,
            "e_before": e_before,
            "e_after": e_after,
            "write": False,
            "reason": net_archive.sentence_confirmed(push=push_before, scope=scope),
        }
    at_new = _simulate(pairs, push_after)
    return {
        "state": net_archive.STATE_CHANGED,
        "e_before": e_before,
        "e_after": e_after,
        "write": True,
        "reason": net_archive.sentence_changed(
            label=label,
            cam_name=cam_name,
            n_verdicts=int(stratum.get("n_total") or 0),
            push_before=push_before,
            push_after=push_after,
            blocked_false=at_new["blocked_false"],
            n_false=int(stratum.get("n_false") or 0),
            kept_true=at_new["kept_true"],
            n_true=int(stratum.get("n_true") or 0),
            scope=scope,
            floor_held=floor_held,
        ),
        "before": {"E": e_before, "push": push_before},
        "after": {"E": e_after, "push": push_after},
    }


def _apply_write(settings_store, cam_id: str, label: str, e_after: int) -> None:
    """Land one learned value on the ``adapted`` layer.

    Additive merge through ``update_section`` — never a wholesale write
    of settings.json — and into ``net_adapted``, never into
    ``label_thresholds`` / ``push_thresholds``. Those two ARE the camera
    layer, which ranks above ``adapted``; writing them from here would
    let the learner impersonate a manual decision and the precedence
    rule would stop meaning anything.
    """
    cams = []
    for cam in settings_store.data.get("cameras", []):
        if cam.get("id") != cam_id:
            continue
        adapted = dict(cam.get("net_adapted") or {})
        adapted[label] = {"E": clamp_e(e_after), "ts": time.time()}
        cams.append({**cam, "net_adapted": adapted})
    if cams:
        settings_store.upsert_camera(cams[0])


def run_pass(storage_root, settings_store, push_cfg: dict) -> dict:
    """The whole nightly run. Returns a summary for the log line."""
    stats = corpus_stats(storage_root)
    now = time.time()
    summary = {"changed": 0, "confirmed": 0, "pending": 0, "pinned": 0, "skipped": 0}
    for cam_cfg in list(settings_store.data.get("cameras", [])):
        if not isinstance(cam_cfg, dict):
            continue
        cam_id = cam_cfg.get("id") or ""
        auto_on = cam_cfg.get("net_auto") is not False
        for label in camera_axes(cam_cfg):
            if not _due(cam_cfg, label, now):
                summary["skipped"] += 1
                continue
            outcome = evaluate_axis(storage_root, cam_cfg, push_cfg, label, stats)
            state = outcome["state"]
            summary[state if state in summary else "pending"] += 1
            _write_consequence(
                storage_root,
                cam_id,
                label,
                state,
                outcome["reason"],
                outcome.get("before"),
                outcome.get("after"),
            )
            if outcome["write"] and auto_on:
                _apply_write(settings_store, cam_id, label, outcome["e_after"])
                log.info(
                    "[det] Netz gelernt: cam=%s label=%s E %d -> %d push %.2f -> %.2f",
                    cam_id,
                    label,
                    outcome["e_before"],
                    outcome["e_after"],
                    outcome["after"]["push"] if outcome.get("after") else 0.0,
                    outcome["after"]["push"] if outcome.get("after") else 0.0,
                )
    net_archive.enforce(storage_root)
    log.info(
        "[det] Netz-Nachtlauf: %d geändert, %d bestätigt, %d offen, %d gepinnt, %d übersprungen",
        summary["changed"],
        summary["confirmed"],
        summary["pending"],
        summary["pinned"],
        summary["skipped"],
    )
    return summary


def axis_proposal(storage_root, cam_cfg: dict, push_cfg: dict, label: str, stats: dict):
    """The learner's current recommendation for one axis, without writing.

    What the dashed proposal polygon and the detail sheet's
    „Vorschlag: 58 · [Übernehmen]" chip are drawn from.
    """
    outcome = evaluate_axis(storage_root, cam_cfg, push_cfg, label, stats)
    if outcome["state"] == net_archive.STATE_PINNED:
        return outcome.get("proposal")
    if outcome["state"] in (net_archive.STATE_CHANGED, net_archive.STATE_CONFIRMED):
        return outcome["e_after"]
    return None


def _alerts_at(pairs, push_value: float) -> tuple:
    """``(gesamt, davon Fehlalarme)`` a push threshold would have sent."""
    sim = _simulate(pairs, push_value)
    n_false = sum(1 for _a, ok in pairs if not ok)
    passed_false = n_false - sim["blocked_false"]
    return sim["kept_true"] + passed_false, passed_false


def preview(storage_root, cam_cfg: dict, label: str, e_value: int) -> dict:
    """„Rückblick 90 Tage: +4 Meldungen, davon 1 Fehlalarm".

    The consequence-before-commit line the drag pill shows, expressed as
    a DELTA against where the axis stands now — "+4 Meldungen" is
    actionable, "31 Meldungen" is not.

    Already computable: ``_calibration._simulate`` over ``judged_alerts``
    does exactly this arithmetic. This is a projection of numbers the
    corpus already holds, not a second estimator that could disagree
    with the one the learner uses.
    """
    cam_id = cam_cfg.get("id") or ""
    pairs = judged_alerts(storage_root, cam_id=cam_id, label=label)
    thresholds = thresholds_for(label, e_value)
    if not pairs:
        return {"has_corpus": False, "thresholds": thresholds}
    now_alerts, now_false = _alerts_at(pairs, push_for(label, effective_e(cam_cfg, label)))
    new_alerts, new_false = _alerts_at(pairs, thresholds["push"])
    return {
        "has_corpus": True,
        "n_judged": len(pairs),
        "delta_alerts": new_alerts - now_alerts,
        "delta_false": new_false - now_false,
        "alerts": new_alerts,
        "false_alarms": new_false,
        "thresholds": thresholds,
    }
