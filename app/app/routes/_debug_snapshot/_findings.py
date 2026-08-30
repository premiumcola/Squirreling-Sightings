"""The auto-diagnosis — the only part of the snapshot rendered on screen.

Every entry is one plain-language sentence naming a gate that is shut,
so the operator reads a verdict instead of a wall of numbers. The
threshold ladder is resolved through :mod:`app.thresholds` rather than
re-implemented, which is what makes the "tote Zone" finding possible:
a class whose push bar sits above its spawn bar is recorded forever and
never sent, and nothing in the UI used to say so.
"""

from __future__ import annotations

from ...thresholds import resolve_effective
from ...thresholds._apply import adapted_layer
from ._helpers import _fenced, _schedule_blocks


def ladder_rows(cam: dict, push_cfg: dict, labels) -> list:
    """Resolve the full detect→spawn→confirm→push ladder per label.

    Delegates to :func:`app.thresholds.resolve_effective` — the one
    place that knows the camera > adapted > global > default order — so
    the snapshot reports the same numbers the pipeline uses instead of
    re-implementing the lookup.

    ``adapted=`` is not optional here even though the signature allows
    it: without it the ``adapted`` layer is empty and the table shows the
    factory bar for every axis the nightly learner has moved. Production
    passes it (``_event_alert._event_ctx``), so a snapshot that omits it
    reports a threshold nothing runs on.
    """
    rows = []
    for label in labels:
        eff = resolve_effective(cam, push_cfg, label, adapted=adapted_layer(cam, label))
        rows.append(eff)
    return rows


def _ladder_status(eff) -> str:
    if not eff.push_enabled:
        return "push=false → wird NIE gemeldet"
    if eff.dead_zone:
        return f"TOTE ZONE: erkannt ab {eff.spawn:.2f}, gemeldet erst ab {eff.push:.2f}"
    return "ok"


def _ladder_block(rows) -> str:
    if not rows:
        return "(keine Klassen — object_filter leer und noch nichts erkannt)"
    lines = [f"{'Klasse':<10}{'detect':>7}{'spawn':>7}{'confirm':>10}{'push':>7}  Status"]
    for eff in rows:
        confirm = f"{eff.confirm_n}/{eff.confirm_seconds:.0f}s"
        push = f"{eff.push:.2f}" if eff.push_enabled else "—"
        lines.append(
            f"{eff.label:<10}{eff.detect:>7.2f}{eff.spawn:>7.2f}{confirm:>10}{push:>7}  "
            f"{_ladder_status(eff)}"
        )
    lines.append("")
    lines.append("Quellen (push): " + " · ".join(f"{e.label}={e.source.get('push')}" for e in rows))
    return _fenced(lines)


# Sort order for the verdict list — a blocked gate outranks an FYI.
_TONE_ORDER = {"red": 0, "warn": 1, "info": 2, "ok": 3}


def build_findings(cam: dict, last: dict, cluster_ev: dict, ladder) -> list:
    """Short, plain-language verdicts — the only part rendered on screen.

    Each entry is ``{"tone": red|warn|info|ok, "text": str}``. Ordered
    most-blocking first so the first line is the one worth reading.
    """
    out = []
    if not last:
        out.append(
            {
                "tone": "warn",
                "text": "Noch kein abgeschlossener Tick — Live-Werte fehlen. Simulation läuft?",
            }
        )
    out += _gate_findings(cam)
    out += _ladder_findings(ladder)
    out += _cluster_findings(cluster_ev)
    if not out:
        # "Alle Tore offen" was a claim about EVERY gate, made by a check
        # that opens six of them. Bewegungs-Gate, Bestätigungsfenster,
        # Wildtier-Kaskade, Vogelarten, Identität, Ereignis-Cooldown,
        # Aufnahme-Zeitplan und Frame-Validator werden hier nie
        # ausgewertet — die Entwarnung nennt jetzt ihren eigenen Umfang,
        # statt für Tore zu bürgen, die niemand angesehen hat.
        out.append(
            {
                "tone": "ok",
                "text": (
                    "Geprüfte Tore offen: scharf, Telegram, Aufnahme, Zeitpläne, "
                    "Schwellen-Leiter. Bewegung, Bestätigung und Wildtier-Kaskade "
                    "bleiben ungeprüft."
                ),
            }
        )
    # Most-blocking first. Only the first two or three lines survive on a
    # phone screen, so a red gate must never be pushed below an FYI by
    # the incidental order the checks run in. Stable → ties keep it.
    out.sort(key=lambda f: _TONE_ORDER.get(f["tone"], 9))
    return out


def _gate_findings(cam: dict) -> list:
    """The camera's own switches and windows — the six gates the
    all-clear above is allowed to speak for."""
    out = []
    if cam.get("armed", True) is False:
        out.append({"tone": "red", "text": "Kamera ist NICHT scharf (armed=false) — kein Alarm."})
    if cam.get("telegram_enabled", True) is False:
        out.append({"tone": "red", "text": "telegram_enabled=false — diese Kamera meldet nie."})
    if cam.get("recording_enabled", True) is False:
        out.append({"tone": "warn", "text": "recording_enabled=false — es wird nichts archiviert."})
    if _schedule_blocks(cam.get("schedule_notify") or {}):
        out.append(
            {
                "tone": "red",
                "text": "schedule_notify-Fenster ist gerade ZU — Meldungen sind jetzt gesperrt.",
            }
        )
    if _schedule_blocks(cam.get("schedule_record") or {}):
        out.append(
            {
                "tone": "warn",
                "text": "schedule_record-Fenster ist gerade ZU — es wird jetzt nicht aufgezeichnet.",
            }
        )
    return out


def _ladder_findings(ladder) -> list:
    """The two ways the threshold ladder silences a class for good."""
    out = []
    for eff in ladder or []:
        if not eff.push_enabled:
            out.append(
                {
                    "tone": "warn",
                    "text": f"{eff.label}: push=false — wird erkannt, aber nie gemeldet.",
                }
            )
        elif eff.dead_zone:
            out.append(
                {
                    "tone": "warn",
                    "text": (
                        f"{eff.label}: tote Zone {eff.spawn:.2f}–{eff.push:.2f} — "
                        f"Treffer darunter werden aufgezeichnet und nie gemeldet."
                    ),
                }
            )
    return out


def _cluster_findings(cluster_ev: dict) -> list:
    """The 60-s aggregates — FYIs, never blockers."""
    out = []
    c1 = (cluster_ev or {}).get("cluster1") or {}
    if int(c1.get("deaths_60s", 0)) > 0:
        out.append(
            {
                "tone": "info",
                "text": f"{c1['deaths_60s']} Track-Abbrüche in 60 s — IoU / Grace / Floor prüfen.",
            }
        )
    c2 = (cluster_ev or {}).get("cluster2") or {}
    if c2.get("missing_classes_60s"):
        out.append(
            {
                "tone": "info",
                "text": "Ohne Detection in 60 s: " + ", ".join(c2["missing_classes_60s"]),
            }
        )
    c3 = (cluster_ev or {}).get("cluster3") or {}
    off = c3.get("off_filter_60s_counts") or {}
    if off:
        top = sorted(off.items(), key=lambda kv: kv[1], reverse=True)[:3]
        out.append(
            {
                "tone": "info",
                "text": "Häufigste gefilterte Klassen: " + ", ".join(f"{k} ({n}×)" for k, n in top),
            }
        )
    c4 = (cluster_ev or {}).get("cluster4") or {}
    if int(c4.get("tick_cycle_ema_ms", 0)) > 2000:
        out.append(
            {
                "tone": "info",
                "text": f"Langsamer Zyklus ({c4['tick_cycle_ema_ms']} ms) — Sub-Stream erwägen.",
            }
        )
    return out
