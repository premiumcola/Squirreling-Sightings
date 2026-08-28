"""Writing an archive record — and the German sentence that explains it.

Three moments, three writes:

  ask time   ``capture`` — the full threshold state in force RIGHT NOW,
             plus the frame. Synchronous, in the same call that sends
             the question (and for every alarm too, so the archive
             covers both bands).
  answer     ``append_verdict`` — what the operator said, and how long
             they took.
  03:30      ``append_consequence`` — what it moved, in one sentence a
             human reads.

The sentence itself is data, not a log line: it is assembled here with
the numbers passed in, stored on the record, and rendered verbatim by
the archive UI. That is what makes "war meine Einstufung eine
Optimierung?" answerable months later, when the thresholds it talks
about have long since changed.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from ..telegram_helpers import LABEL_DE
from ..thresholds import resolve_effective
from ..thresholds._apply import adapted_layer, effective_e, provenance
from ._consts import (
    KIND_NETZ,
    SCOPE_POOLED,
    STATE_CHANGED,
    STATE_CONFIRMED,
    STATE_PENDING,
    STATE_PINNED,
)
from ._io import load_record, save_frame, save_record

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _de(label: str) -> str:
    return LABEL_DE.get(label, label)


def _pct(value) -> str:
    try:
        return f"{round(float(value) * 100)} %"
    except (TypeError, ValueError):
        return "—"


def _axis_evidence(stratum: dict) -> dict:
    """The four numbers the vertex's evidence encoding is drawn from."""
    return {
        "judged": int(stratum.get("n_total") or 0),
        "true": int(stratum.get("n_true") or 0),
        "false": int(stratum.get("n_false") or 0),
        "answer_rate": stratum.get("answer_rate") or 0.0,
        "ready": bool(stratum.get("ready")),
        "scope": stratum.get("scope") or "stratum",
    }


def build_net_state(cam_cfg: dict, push_cfg: dict, labels, strata_for) -> dict:
    """One line per axis of this camera: the numbers the pipeline used.

    ``source`` comes from ``EffectiveThresholds.source`` — which makes
    the archive the SECOND conforming consumer of the ladder, after
    ``routes/_debug_snapshot/_findings``. That is the point: these are
    the numbers the pipeline used, by construction, and not a second
    reading of the same config that can drift away from it.

    ``strata_for`` is a callable ``label -> stratum row`` so this stays
    pure — the caller does the ledger I/O once for the whole camera.
    """
    out: dict = {}
    for label in labels:
        eff = resolve_effective(cam_cfg, push_cfg, label, adapted=adapted_layer(cam_cfg, label))
        out[label] = {
            "E": effective_e(cam_cfg, label),
            "spawn": eff.spawn,
            "push": eff.push,
            "confirm_n": eff.confirm_n,
            "confirm_s": eff.confirm_seconds,
            "source": dict(eff.source),
            "provenance": provenance(cam_cfg, label),
            "evidence": _axis_evidence(strata_for(label) or {}),
        }
    return out


def capture(
    storage_root,
    *,
    event_id: str,
    cam_id: str,
    cam_name: str,
    kind: str,
    detection: dict,
    net_state: dict,
    rails: dict,
    asked: bool,
    asked_via: str = "telegram",
    frame_bytes=None,
) -> bool:
    """Write the ask-time record. Best-effort; never raises at a caller."""
    payload = {
        "ts": _now_iso(),
        "event_id": event_id,
        "cam_id": cam_id,
        "cam_name": cam_name,
        "kind": kind,
        "detection": detection,
        "asked_via": asked_via,
        "asked_ts": _now_iso() if asked else None,
        "asked": bool(asked),
        "net_state": net_state,
        "rails": rails,
        "consequence": {
            "state": STATE_PENDING,
            "label": detection.get("label"),
            "cam_id": cam_id,
            "reason_de": "Noch nicht ausgewertet — die Nachtberechnung um 03:30 trägt hier ein, "
            "was deine Antwort bewegt hat.",
        },
    }
    ok = save_record(storage_root, event_id, payload)
    if ok and frame_bytes:
        save_frame(storage_root, event_id, frame_bytes)
    return ok


def append_verdict(
    storage_root,
    event_id: str,
    *,
    value: str,
    source: str,
    corrected_label: str | None = None,
) -> bool:
    """Attach the operator's answer, with how long it took them.

    ``delay_s`` is measured against ``asked_ts`` — a late answer is a
    perfectly valid answer, and the delay is the only way to see later
    that a stratum's verdicts were volunteered days after the fact.
    """
    rec = load_record(storage_root, event_id)
    if rec is None:
        return False
    delay = None
    try:
        asked = rec.get("asked_ts")
        if asked:
            delay = round(time.time() - datetime.fromisoformat(asked).timestamp(), 1)
    except Exception:
        delay = None
    rec["verdict"] = {
        "value": value,
        "corrected_label": corrected_label,
        "ts": _now_iso(),
        "delay_s": delay,
        "source": source,
    }
    return save_record(storage_root, event_id, rec)


def append_consequence(storage_root, event_id: str, consequence: dict) -> bool:
    """The 03:30 job's verdict on the verdict."""
    rec = load_record(storage_root, event_id)
    if rec is None:
        return False
    rec["consequence"] = consequence
    return save_record(storage_root, event_id, rec)


def record_net_change(
    storage_root,
    *,
    event_id: str,
    cam_id: str,
    cam_name: str,
    label: str,
    e_before: int,
    e_after: int,
    push_before: float,
    push_after: float,
    net_state: dict,
    rails: dict,
) -> bool:
    """A manual drag gets its own record — same list, same detail sheet.

    No image: there is no moment to show. This is what makes "Netz zu
    diesem Zeitpunkt wiederherstellen" possible for a hand-set value as
    well as for a learned one.
    """
    payload = {
        "ts": _now_iso(),
        "event_id": event_id,
        "cam_id": cam_id,
        "cam_name": cam_name,
        "kind": KIND_NETZ,
        "detection": {"label": label, "score": None, "all": []},
        "asked": False,
        "asked_via": "web",
        "asked_ts": None,
        "net_state": net_state,
        "rails": rails,
        "consequence": {
            "state": STATE_CHANGED,
            "label": label,
            "cam_id": cam_id,
            "before": {"E": e_before, "push": push_before},
            "after": {"E": e_after, "push": push_after},
            "reason_de": (
                f"Du hast {_de(label)} auf {cam_name} von {e_before} auf {e_after} gezogen. "
                f"Meldeschwelle {_pct(push_before)} → {_pct(push_after)}."
            ),
        },
    }
    return save_record(storage_root, event_id, payload)


# ── the five German templates ─────────────────────────────────────────
#
# One sentence a human reads, with the numbers in it. Never a
# placeholder, never a blank card: `pending` is a real state with real
# copy, because a card that says nothing reads as a bug.


def _modifiers(*, scope: str | None, floor_held: dict | None) -> str:
    out = ""
    if scope == SCOPE_POOLED:
        out += " · aus allen Kameras zusammengerechnet, deshalb vorsichtig."
    if floor_held:
        out += (
            f" · Vorschlag wäre {floor_held.get('wanted')}, die Sicherheitsgrenze für Person "
            f"liegt bei {floor_held.get('floor')} — nicht angewandt."
        )
    return out


def sentence_changed(
    *,
    label: str,
    cam_name: str,
    n_verdicts: int,
    push_before: float,
    push_after: float,
    blocked_false: int,
    n_false: int,
    kept_true: int,
    n_true: int,
    scope: str | None = None,
    floor_held: dict | None = None,
) -> str:
    return (
        f"Deine Rückmeldung war die {n_verdicts}. für <b>{_de(label)}</b> auf "
        f"<b>{cam_name}</b>. Die Meldeschwelle geht von {_pct(push_before)} auf "
        f"{_pct(push_after)} — {blocked_false} von {n_false} Fehlalarmen lagen darunter, "
        f"{kept_true} von {n_true} echten Treffern darüber."
    ) + _modifiers(scope=scope, floor_held=floor_held)


def sentence_confirmed(*, push: float, scope: str | None = None) -> str:
    return (
        f"Bestätigt. Der Wert bleibt bei {_pct(push)} — deine Antwort passt zur bisherigen "
        f"Einschätzung."
    ) + _modifiers(scope=scope, floor_held=None)


def sentence_pending(*, label: str, cam_name: str, judged: int, needed: int) -> str:
    return (
        f"Gezählt — {judged} von {needed} Rückmeldungen für <b>{_de(label)} · {cam_name}</b>. "
        f"Ab {needed} passt sich der Wert automatisch an."
    )


def sentence_pinned(*, pinned_on: str | None, proposal: int | None) -> str:
    when = f" am {pinned_on}" if pinned_on else ""
    tail = f" Der Vorschlag wäre {proposal}." if proposal is not None else ""
    return (
        f"Gezählt. Diese Achse hast du{when} selbst gesetzt, die Automatik rührt sie nicht an."
        + tail
    )


STATE_SENTENCE = {
    STATE_CHANGED: sentence_changed,
    STATE_CONFIRMED: sentence_confirmed,
    STATE_PENDING: sentence_pending,
    STATE_PINNED: sentence_pinned,
}
