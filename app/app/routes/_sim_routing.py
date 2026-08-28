"""Downstream routing trace for the Simulieren panel.

Severity matrix → armed → telegram_enabled → schedule_notify →
notification cooldown → per-label push threshold → final verdict. Split
out of ``_sim_trace`` because those lines answer a different question:
``_sim_trace`` reports what the DETECTION pipeline did to this frame,
this module reports what the NOTIFICATION pipeline would do with the
result. Read-only throughout — the panel inspects, it never sends.
"""

from __future__ import annotations

import time as _time

from ._sim_pipeline import SimPass


def routing_lines(
    *,
    cam: dict,
    cam_id: str,
    sim: SimPass,
    eff_cfg: dict,
    notifier,
) -> tuple[list[str], bool]:
    """``(trace_lines, push_blocked)``.

    Evaluated even when nothing passed: "what WOULD have happened if a
    hit passed" is usually the actual debugging question.
    """
    from ..event_logic import compute_severity_from_matrix, is_schedule_window_active

    pass_rows = sim.pass_rows
    class_sev_cfg = cam.get("class_severity") or {}
    lines = [
        f"[matrix] class_severity: "
        f"{class_sev_cfg if class_sev_cfg else '(leer — Rückfall auf alarm_profile)'}"
    ]
    if pass_rows:
        labels_pass = sorted({r["label"] for r in pass_rows})
        severity = (
            compute_severity_from_matrix(class_sev_cfg, labels_pass) if class_sev_cfg else "alarm"
        )
        lines.append(f"[matrix] Schweregrad für {labels_pass}: {severity}")
    lines.append(f"[armed] Kamera scharf={bool(cam.get('armed', True))}")
    lines.append(
        f"[telegram_enabled] cam.telegram_enabled={bool(cam.get('telegram_enabled', True))}"
    )
    sch_notify = cam.get("schedule_notify") or {}
    if sch_notify:
        try:
            active_now = is_schedule_window_active(sch_notify)
        except Exception as e:  # noqa: BLE001 — a diagnostic must not 500
            active_now = f"(Auswertung fehlgeschlagen: {e})"
        lines.append(
            f"[schedule_notify] enabled={bool(sch_notify.get('enabled', False))} "
            f"Fenster={sch_notify.get('from', '?')}→{sch_notify.get('to', '?')} · "
            f"aktiv={active_now}"
        )
    else:
        lines.append("[schedule_notify] (keins — Rückfall auf den Alt-Zeitplan)")
    lines.extend(_cooldown_lines(cam=cam, cam_id=cam_id, pass_rows=pass_rows, notifier=notifier))
    push_lines, push_blocked = _push_lines(pass_rows=pass_rows, eff_cfg=eff_cfg)
    lines.extend(push_lines)
    lines.append(_final_line(pass_rows, push_blocked))
    return lines, push_blocked


def _final_line(pass_rows: list, push_blocked: bool) -> str:
    if not pass_rows:
        return "[final] kein Push (keine Detektion hat bestanden)"
    if push_blocked:
        return (
            "[final] KEIN Alarm — die Erkennung überlebt alle Tore oben, scheitert "
            "aber an der Push-Schwelle. Clip wird aufgezeichnet, Nachricht nicht gesendet."
        )
    # Deliberately hedged: the motion gate and the N-of-M confirmation
    # window are NOT simulated (see _sim_trace.stated_gate_lines), so an
    # unqualified "would route" is a claim this endpoint cannot make.
    return (
        f"[final] {len(pass_rows)} Detektion(en) würden die Push-Pipeline erreichen — "
        f"vorbehaltlich Bewegungs-Gate und Bestätigungsfenster, die die Simu nicht prüft"
    )


def _cooldown_lines(*, cam: dict, cam_id: str, pass_rows: list, notifier) -> list[str]:
    """Read-only peek at the notifier's per-(cam,label) cooldown map.

    Mirrors the keying in telegram_bot/_outbound so the trace matches what
    would actually happen at notify time; swallows any structural drift
    between the notifier internals and this inspection.
    """
    if notifier is None or not pass_rows:
        return []
    try:
        top_label = pass_rows[0]["label"]
        last_mono = getattr(notifier, "_last_notify", {}).get((cam_id, top_label), 0.0)
        cd_seconds = int((cam.get("notification_cooldown") or {}).get(top_label, 60))
        if not last_mono:
            return [f"[cooldown] {top_label}@{cam_id}: nie gepusht → würde PASSIEREN"]
        elapsed = _time.monotonic() - last_mono
        if elapsed < cd_seconds:
            return [
                f"[cooldown] {top_label}@{cam_id}: letzter Push vor {int(elapsed)} s · "
                f"noch {int(cd_seconds - elapsed)} s → würde ÜBERSPRINGEN"
            ]
        return [
            f"[cooldown] {top_label}@{cam_id}: ruhig (zuletzt vor {int(elapsed)} s, "
            f"Schwelle {cd_seconds} s) → würde PASSIEREN"
        ]
    except Exception as e:  # noqa: BLE001 — a diagnostic must not 500
        return [f"[cooldown] Abfrage fehlgeschlagen: {e}"]


def _push_lines(*, pass_rows: list, eff_cfg: dict) -> tuple[list[str], bool]:
    """The per-label PUSH threshold — a second, independent bar.

    It is the gate that actually silences most alerts (shipped defaults:
    person 0.85, squirrel 0.80, cat + bird push:false against a detection
    floor of 0.45), and the simulator used to omit it entirely: it
    reported "would route through the push pipeline" for a detection the
    push pipeline then dropped without a word.
    """
    lines: list[str] = []
    push_blocked = False
    try:
        push_cfg = ((eff_cfg.get("telegram") or {}).get("push") or {}).get("labels") or {}
    except Exception as e:  # noqa: BLE001 — a diagnostic must not 500
        return [f"[push_threshold] Abfrage fehlgeschlagen: {e}"], False
    for r in pass_rows:
        lbl = r["label"]
        lbl_cfg = push_cfg.get(lbl) or {}
        if not lbl_cfg.get("push", False):
            push_blocked = True
            lines.append(f"[push_flag] {lbl}: push=false → würde ÜBERSPRINGEN (kein Alarm)")
            continue
        bar = float(lbl_cfg.get("threshold", 0.0) or 0.0)
        score = float(r.get("score", 0.0))
        if score < bar:
            push_blocked = True
            lines.append(
                f"[push_threshold] {lbl}: {int(round(score * 100))} % < "
                f"{int(round(bar * 100))} % → würde ÜBERSPRINGEN "
                f"(erkannt, aber nicht gemeldet)"
            )
        else:
            lines.append(
                f"[push_threshold] {lbl}: {int(round(score * 100))} % ≥ "
                f"{int(round(bar * 100))} % → würde PASSIEREN"
            )
    return lines, push_blocked
