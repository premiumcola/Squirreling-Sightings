"""Downstream routing trace for the Simulieren panel.

Severity matrix → armed → telegram_enabled → Stummschaltung → per-label
push flag / push threshold → suppress → Rate-Limit → Melde-Cooldown →
schedule_notify → final verdict. Split out of ``_sim_trace`` because
those lines answer a different question: ``_sim_trace`` reports what the
DETECTION pipeline did to this frame, this module reports what the
NOTIFICATION pipeline would do with the result. Read-only throughout —
the panel inspects, it never sends.

The gates and their ORDER are production's own, read off
``telegram_bot/_outbound/_event_alert._event_blocked``, and every value
they decide on is resolved through the function production calls:
``thresholds.resolve_effective`` (with the learner's ``adapted_layer``)
for the push ladder, and the notifier's own ``mute_state`` /
``_is_suppressed`` / ``_is_rate_limited`` predicates for the runtime
throttles.

That is the whole point of this module's rewrite. It used to RE-DERIVE
the push decision from ``eff_cfg["telegram"]["push"]["labels"][label]``
with ``push=False, threshold=0.0`` defaults, and reached conclusions
opposite to production:

  * ``class_severity`` OUTRANKS the global push flag (``_ladder
    ._resolve_push_enabled``) in BOTH directions. The shipped globals
    carry ``push: false`` for cat / bird / motion / fox / hedgehog, so a
    feeder camera whose matrix said ``cat: info`` was told its cats
    would be skipped — production pushes them. A camera whose matrix
    said ``person: off`` was told a 91 % person "würde PASSIEREN" —
    production sends nothing. Both were live, in the same report, beside
    a ladder table that said the opposite.
  * a per-camera ``push_thresholds`` override — the key the Netz radar
    writes — was invisible, as was every axis the nightly learner moved
    through ``net_adapted``.

And the four gates that were not merely wrong but absent: both mutes,
``suppress`` and ``rate_limit_seconds``. With a mute running the panel
concluded "würden die Push-Pipeline erreichen" while production dropped
every alert — the single most common cause of "ich bekomme keine
Meldungen", actively denied by the tool meant to find it.
"""

from __future__ import annotations

import time as _time
from datetime import datetime

from ..thresholds import (
    SOURCE_ADAPTED,
    SOURCE_CAMERA,
    SOURCE_DEFAULT,
    SOURCE_GLOBAL,
    resolve_effective,
)
from ..thresholds._apply import adapted_layer
from ._sim_pipeline import SimPass

# Where a resolved value came from, in the operator's words. Same four
# layers ``thresholds`` documents — named so the trace answers "warum
# diese Zahl?" without a second lookup in the settings UI.
_SOURCE_DE = {
    SOURCE_CAMERA: "Kamera",
    SOURCE_ADAPTED: "Lernkurve",
    SOURCE_GLOBAL: "global",
    SOURCE_DEFAULT: "Werk",
}


def routing_lines(
    *,
    cam: dict,
    cam_id: str,
    sim: SimPass,
    eff_cfg: dict,
    notifier,
) -> tuple[list[str], bool]:
    """``(trace_lines, blocked)``.

    Evaluated even when nothing passed: "what WOULD have happened if a
    hit passed" is usually the actual debugging question.

    Every chunk returns its lines AND the gates it found shut, so the
    final verdict is assembled from the same evaluation the operator
    reads above it. The old ``_final_line`` branched on the push gate
    alone and dropped ``armed`` / ``telegram_enabled`` /
    ``schedule_notify`` — printed two lines earlier and then ignored, so
    a disarmed camera still reported a reachable pipeline.
    """
    pass_rows = sim.pass_rows
    push_lines, push_blockers, push_ok = _push_lines(cam=cam, pass_rows=pass_rows, eff_cfg=eff_cfg)
    chunks = [
        _matrix_lines(cam, pass_rows),
        _switch_lines(cam),
        _mute_lines(cam_id=cam_id, notifier=notifier),
        (push_lines, push_blockers),
        _throttle_lines(cam_id=cam_id, pass_rows=pass_rows, notifier=notifier),
        _cooldown_lines(cam=cam, cam_id=cam_id, pass_rows=pass_rows, notifier=notifier),
        _schedule_lines(cam),
    ]
    lines: list[str] = []
    push_blocked: list[str] = []
    for chunk_lines, chunk_blockers in chunks:
        lines.extend(chunk_lines)
        push_blocked.extend(chunk_blockers)
    lines.append(_final_line(pass_rows=pass_rows, push_ok=push_ok, blockers=push_blocked))
    return lines, bool(push_blocked)


def _final_line(*, pass_rows: list, push_ok: int, blockers: list[str]) -> str:
    """The verdict — and it may only claim what the lines above checked.

    Deliberately hedged on the way out: the motion gate and the N-of-M
    confirmation window are NOT simulated (see
    ``_sim_trace.stated_gate_lines``), so an unqualified "would route" is
    a claim this endpoint cannot make.
    """
    if not pass_rows:
        tail = f" · zusätzlich gesperrt: {'; '.join(blockers)}" if blockers else ""
        return "[final] kein Push (keine Detektion hat bestanden)" + tail
    if blockers:
        return (
            f"[final] KEIN Alarm — gesperrt durch: {'; '.join(blockers)}. "
            f"Aufzeichnung läuft davon unabhängig, es wird keine Nachricht gesendet."
        )
    return (
        f"[final] {push_ok} Detektion(en) würden die Push-Pipeline erreichen — "
        f"vorbehaltlich Bewegungs-Gate und Bestätigungsfenster, die die Simu nicht prüft"
    )


def _matrix_lines(cam: dict, pass_rows: list) -> tuple[list[str], list[str]]:
    """The per-class severity matrix — the camera's own answer, and the
    one that decides whether the event carries ``notify`` at all."""
    from ..event_logic import compute_severity_from_matrix

    class_sev_cfg = cam.get("class_severity") or {}
    lines = [
        f"[matrix] class_severity: "
        f"{class_sev_cfg if class_sev_cfg else '(leer — Rückfall auf alarm_profile)'}"
    ]
    blockers: list[str] = []
    if pass_rows:
        labels_pass = sorted({r["label"] for r in pass_rows})
        severity = (
            compute_severity_from_matrix(class_sev_cfg, labels_pass) if class_sev_cfg else "alarm"
        )
        lines.append(f"[matrix] Schweregrad für {labels_pass}: {severity}")
        if severity == "off":
            blockers.append("Schweregrad 'off' aus der Klassen-Matrix")
    return lines, blockers


def _switch_lines(cam: dict) -> tuple[list[str], list[str]]:
    """The two camera-level switches. Applied in
    ``camera_runtime/_recording/_publish._publish_alert``, i.e. ABOVE the
    notifier — nothing below them runs when one is off."""
    armed = bool(cam.get("armed", True))
    tg_on = bool(cam.get("telegram_enabled", True))
    blockers: list[str] = []
    if not armed:
        blockers.append("Kamera nicht scharf (armed=false)")
    if not tg_on:
        blockers.append("telegram_enabled=false")
    return (
        [f"[armed] Kamera scharf={armed}", f"[telegram_enabled] cam.telegram_enabled={tg_on}"],
        blockers,
    )


def _mute_lines(*, cam_id: str, notifier) -> tuple[list[str], list[str]]:
    """Global + per-camera mute — production's FIRST notifier gate.

    Read through the notifier's own ``mute_state`` so the panel and the
    push path can never disagree, and because that predicate is log-free:
    a diagnostic peek must not write "[tg] skip:" for an alert nobody
    tried to send.
    """
    if notifier is None:
        return ["[mute] Telegram-Dienst nicht aktiv — Stummschaltung nicht prüfbar"], []
    try:
        reason, until = notifier.mute_state(cam_id)
    except Exception as e:  # noqa: BLE001 — a diagnostic must not 500
        return [f"[mute] Abfrage fehlgeschlagen: {e}"], []
    if not reason:
        return ["[mute] keine Stummschaltung aktiv → würde PASSIEREN"], []
    scope = "System" if reason == "global_mute" else f"Kamera {cam_id}"
    rest = max(0, int(float(until) - _time.time()))
    return (
        [f"[mute] {scope} stumm bis {_hhmm(until)} (noch {rest} s) → würde ÜBERSPRINGEN"],
        [f"Stummschaltung aktiv ({scope})"],
    )


def _throttle_lines(*, cam_id: str, pass_rows: list, notifier) -> tuple[list[str], list[str]]:
    """``suppress`` and ``rate_limit_seconds`` — production's gates after
    the threshold. Both are the notifier's own predicates; neither logs.

    ``rate_limit_seconds`` is read off ``notifier.push_cfg`` rather than
    the effective config so the number shown is the number the predicate
    that decides actually used.
    """
    if notifier is None:
        return ["[suppress] Telegram-Dienst nicht aktiv — nicht prüfbar"], []
    lines: list[str] = []
    blockers: list[str] = []
    label = pass_rows[0]["label"] if pass_rows else None
    try:
        if label is None:
            lines.append("[suppress] keine Detektion — nichts zu prüfen")
        elif notifier._is_suppressed(cam_id, label):
            blockers.append(f"'{label}' auf dieser Kamera unterdrückt")
            lines.append(f"[suppress] {label}@{cam_id}: unterdrückt → würde ÜBERSPRINGEN")
        else:
            lines.append(f"[suppress] {label}@{cam_id}: nicht unterdrückt → würde PASSIEREN")
        rl = float((getattr(notifier, "push_cfg", None) or {}).get("rate_limit_seconds", 30) or 0)
        if rl <= 0:
            lines.append("[rate_limit] rate_limit_seconds=0 — Gate aus")
        elif notifier._is_rate_limited(cam_id):
            blockers.append(f"Rate-Limit ({int(rl)} s) aktiv")
            lines.append(
                f"[rate_limit] {cam_id}: letzter Push liegt < {int(rl)} s zurück "
                f"→ würde ÜBERSPRINGEN"
            )
        else:
            lines.append(f"[rate_limit] {cam_id}: Fenster {int(rl)} s frei → würde PASSIEREN")
    except Exception as e:  # noqa: BLE001 — a diagnostic must not 500
        lines.append(f"[suppress] Abfrage fehlgeschlagen: {e}")
    return lines, blockers


def _cooldown_lines(
    *, cam: dict, cam_id: str, pass_rows: list, notifier
) -> tuple[list[str], list[str]]:
    """Read-only peek at the notifier's per-(cam,label) cooldown map.

    Mirrors the keying in telegram_bot/_outbound so the trace matches what
    would actually happen at notify time; swallows any structural drift
    between the notifier internals and this inspection.
    """
    if notifier is None or not pass_rows:
        return [], []
    try:
        top_label = pass_rows[0]["label"]
        last_mono = getattr(notifier, "_last_notify", {}).get((cam_id, top_label), 0.0)
        cd_seconds = int((cam.get("notification_cooldown") or {}).get(top_label, 60))
        if not last_mono:
            return [f"[cooldown] {top_label}@{cam_id}: nie gepusht → würde PASSIEREN"], []
        elapsed = _time.monotonic() - last_mono
        if elapsed < cd_seconds:
            return (
                [
                    f"[cooldown] {top_label}@{cam_id}: letzter Push vor {int(elapsed)} s · "
                    f"noch {int(cd_seconds - elapsed)} s → würde ÜBERSPRINGEN"
                ],
                [f"Melde-Cooldown für '{top_label}' läuft noch"],
            )
        return (
            [
                f"[cooldown] {top_label}@{cam_id}: ruhig (zuletzt vor {int(elapsed)} s, "
                f"Schwelle {cd_seconds} s) → würde PASSIEREN"
            ],
            [],
        )
    except Exception as e:  # noqa: BLE001 — a diagnostic must not 500
        return [f"[cooldown] Abfrage fehlgeschlagen: {e}"], []


def _schedule_lines(cam: dict) -> tuple[list[str], list[str]]:
    """The per-camera notification window — production's last gate."""
    from ..event_logic import is_schedule_window_active

    sch_notify = cam.get("schedule_notify") or {}
    if not sch_notify:
        return ["[schedule_notify] (keins — Rückfall auf den Alt-Zeitplan)"], []
    try:
        active_now = is_schedule_window_active(sch_notify)
    except Exception as e:  # noqa: BLE001 — a diagnostic must not 500
        return [f"[schedule_notify] Auswertung fehlgeschlagen: {e}"], []
    line = (
        f"[schedule_notify] enabled={bool(sch_notify.get('enabled', False))} "
        f"Fenster={sch_notify.get('from', '?')}→{sch_notify.get('to', '?')} · "
        f"aktiv={active_now}"
    )
    return [line], ([] if active_now else ["schedule_notify-Fenster ist gerade zu"])


def _push_lines(*, cam: dict, pass_rows: list, eff_cfg: dict) -> tuple[list[str], list[str], int]:
    """``(lines, blockers, surviving_rows)`` for the per-label push gate.

    Resolved the way ``_event_alert._event_ctx`` resolves it —
    ``resolve_effective`` plus the learner's ``adapted`` layer — because
    that is the only reading that knows the camera > adapted > global >
    default order and that ``class_severity`` outranks the global flag.

    The gate is reported as blocking only when NO label survives it: a
    multi-class tick where one class clears the bar still reaches the
    push pipeline, on that class.
    """
    try:
        push_cfg = (eff_cfg.get("telegram") or {}).get("push") or {}
    except Exception as e:  # noqa: BLE001 — a diagnostic must not 500
        return [f"[push_threshold] Abfrage fehlgeschlagen: {e}"], [], 0
    lines: list[str] = []
    reasons: list[str] = []
    survivors = 0
    for r in pass_rows:
        lbl = r["label"]
        try:
            eff = resolve_effective(cam, push_cfg, lbl, adapted=adapted_layer(cam, lbl))
        except Exception as e:  # noqa: BLE001 — a diagnostic must not 500
            lines.append(f"[push_threshold] {lbl}: Auflösung fehlgeschlagen: {e}")
            continue
        line, reason = _push_row_line(lbl, float(r.get("score", 0.0)), eff)
        lines.append(line)
        if reason:
            reasons.append(reason)
        else:
            survivors += 1
    blockers = reasons if (pass_rows and survivors == 0) else []
    return lines, blockers, survivors


def _push_row_line(lbl: str, score: float, eff) -> tuple[str, str | None]:
    """One label's push verdict: ``(line, blocking_reason_or_None)``."""
    if not eff.push_enabled:
        src = _src_de(eff, "push_enabled")
        return (
            f"[push_flag] {lbl}: push=false (Quelle: {src}) → würde ÜBERSPRINGEN (kein Alarm)",
            f"push=false für '{lbl}' (Quelle: {src})",
        )
    bar = float(eff.push)
    src = _src_de(eff, "push")
    if score < bar:
        return (
            f"[push_threshold] {lbl}: {_pct(score)} % < {_pct(bar)} % (Quelle: {src}) "
            f"→ würde ÜBERSPRINGEN (erkannt, aber nicht gemeldet)",
            f"'{lbl}' unter der Push-Schwelle {_pct(bar)} %",
        )
    return (
        f"[push_threshold] {lbl}: {_pct(score)} % ≥ {_pct(bar)} % (Quelle: {src}) "
        f"→ würde PASSIEREN",
        None,
    )


def _src_de(eff, field: str) -> str:
    source = eff.source.get(field, "")
    return _SOURCE_DE.get(source, source or "?")


def _pct(value: float) -> int:
    return int(round(value * 100))


def _hhmm(epoch: float) -> str:
    try:
        return datetime.fromtimestamp(float(epoch)).strftime("%H:%M")
    except (OSError, OverflowError, TypeError, ValueError):
        return "?"
