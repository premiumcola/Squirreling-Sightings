"""The Simulieren panel's decision trace.

One German line per gate, from capture to Telegram, rendered verbatim in
the panel's terminal block. Two kinds of line live here and the
difference matters:

  * gates the panel actually RAN — size floor, object filter, masks,
    zones, tracker, spawn threshold. These report what happened to this
    tick's boxes.
  * gates the panel deliberately does NOT run — the motion window, the
    N-of-M confirmation, the wildlife cascade, the event cooldown, the
    recording schedule. These are STATED, with the reason they cannot be
    simulated honestly at ~1 Hz over HTTP.

The second kind is the point of this module. The panel's old failure was
not that it skipped those gates; it was that it skipped them silently and
then concluded "would route through the push pipeline" for a single-frame
hit production would never have confirmed.
"""

from __future__ import annotations

from ..detect_setup import DetectionSetup
from ._sim_pipeline import (
    VERDICT_FILTERED,
    VERDICT_MASKED,
    VERDICT_NO_TRACK,
    VERDICT_OUTSIDE_ZONE,
    VERDICT_PASS,
    VERDICT_TENTATIVE,
    SimPass,
)
from ._sim_tiling import sahi_trace_line

# Verdict → the German word the per-detection line prints.
_VERDICT_WORD = {
    VERDICT_PASS: "PASS",
    VERDICT_TENTATIVE: "TENTATIV",
    VERDICT_NO_TRACK: "VERWORFEN",
    VERDICT_FILTERED: "GEFILTERT",
    VERDICT_MASKED: "MASKIERT",
    VERDICT_OUTSIDE_ZONE: "AUSSERHALB",
}


def capture_lines(
    *,
    cam: dict,
    setup: DetectionSetup,
    sim: SimPass,
    frame_age_ms: int,
    stream_used: str,
    stream_override: bool,
) -> list[str]:
    """Frame provenance, crop, the skipped validator and the two clocks."""
    lines = [
        f"[capture] Frame {sim.frame_w}×{sim.frame_h} · Alter {frame_age_ms} ms · "
        f"Stream '{stream_used}'"
    ]
    if stream_override:
        lines.append(
            "[capture] ABWEICHUNG: Produktion wertet immer den Main-Stream aus — "
            "diese Ansicht läuft auf dem Sub-Stream"
        )
    if setup.bottom_crop_px > 0:
        lines.append(
            f"[capture] bottom_crop_px={setup.bottom_crop_px} angewendet "
            f"(wie in der Produktion, vor der Inferenz)"
        )
    else:
        lines.append("[capture] bottom_crop_px=0 — kein Zuschnitt konfiguriert")
    # Deliberate, documented divergence — see the wait loop's rationale.
    lines.append(
        "[capture] Frame-Validator übersprungen (Diagnose-Ansicht zeigt den "
        "aktuellen Frame) — Produktion verwirft hier zusätzlich ungültige Frames"
    )
    prod_fps = 1000.0 / float(cam.get("frame_interval_ms") or 350)
    lines.append(
        f"[takt] Simu-Takt ≈ {sim.tick_fps:.2f}/s · Produktion ≈ {prod_fps:.1f}/s — "
        f"HTTP-Polling kann den Produktionstakt nicht erreichen; die Tracker-"
        f"Grace wird gegen den gemessenen Simu-Takt gerechnet"
    )
    return lines


def config_lines(*, setup: DetectionSetup, sim: SimPass, mode_override: bool) -> list[str]:
    """The numbers the pass ran on — all from the shared DetectionSetup."""
    per_class = setup.label_thresholds
    lines = [
        f"[coral] Inferenz-Schwelle {setup.floor:.2f} (Tracker-Continue-Floor, "
        f"wie in der Produktion) · Spawn {setup.spawn_default:.2f} · "
        f"pro Klasse: {dict(per_class) if per_class else '(keine)'}",
        f"[coral] detection_min_score={setup.min_score:.2f} — NICHT der Live-Cutoff. "
        f"Der Zwei-Stufen-Tracker hat ihn ersetzt; steht hier nur zur Information",
        f"[coral] object_filter: "
        f"{sorted(setup.object_filter) if setup.object_filter else '(keiner — alle Klassen)'}",
        f"[coral] roh {sim.raw_count} Detektion(en) · {sim.invokes} Inferenz(en) · "
        f"{sim.inference_ms} ms",
    ]
    sahi = sahi_trace_line(sim.sahi_diag or {"mode": "off"})
    if sahi:
        lines.append(sahi)
    if mode_override:
        lines.append(
            "[sahi] ABWEICHUNG: Kachel-Modus per Schalter gesetzt — "
            f"die Kamera läuft mit roi_mode='{setup.det_mode}'"
        )
    if (sim.sahi_diag or {}).get("mode", "off") != "off":
        tiles = max(0, sim.invokes - 1)
        lines.append(
            "[sahi] Produktion kachelt NUR als Rettung (kohärenter Bewegungs-Blob, "
            "1.5 s Cooldown, keine bestätigbare Box darauf) und bezahlt dabei nur "
            f"die {tiles} Kachel(n), weil sie den Vollbild-Durchlauf wiederverwendet. "
            f"Die Simu kachelt jeden Tick und braucht den Vollbild-Durchlauf für die "
            f"Anzeige, also {sim.invokes} Inferenz(en)."
        )
    return lines


def gate_lines(*, cam: dict, setup: DetectionSetup, sim: SimPass, active_tracks: int) -> list[str]:
    """What each gate the panel actually ran did to this tick's boxes."""
    n_masks = len(cam.get("masks") or [])
    n_zones = len(cam.get("zones") or [])
    return [
        f"[filter] {sim.count(VERDICT_FILTERED)} Box(en) durch object_filter verworfen",
        f"[mask] {n_masks} Maske(n) konfiguriert · "
        f"{sim.count(VERDICT_MASKED)} Box(en) verworfen",
        f"[zone] {n_zones} Zone(n) konfiguriert · "
        f"{sim.count(VERDICT_OUTSIDE_ZONE)} Box(en) außerhalb verworfen",
        f"[tracker] {sim.count(VERDICT_NO_TRACK)} Box(en) ohne Track verworfen · "
        f"{sim.count(VERDICT_TENTATIVE)} tentativ · {active_tracks} aktive(r) Track(s)",
    ]


def detection_lines(sim: SimPass) -> list[str]:
    """One line per box, with the gate that decided it."""
    lines = []
    for r in sim.rows:
        pct = int(round(r["score"] * 100))
        word = _VERDICT_WORD.get(r["verdict"], r["verdict"].upper())
        tail = f" ({r['reason']})" if r["reason"] else ""
        num = f" #{r['track_num']}" if r.get("track_num") is not None else ""
        lines.append(f"[det] {r['label']}{num} {pct}% → {word}{tail}")
    if not sim.pass_rows:
        lines.append(
            "[verdict] keine Detektion hat alle Tore überlebt · " "Alarm-Pipeline NICHT ausgelöst"
        )
    return lines


def stated_gate_lines(*, cam: dict, setup: DetectionSetup, eff_cfg: dict) -> list[str]:
    """Gates production runs that the panel refuses to fake.

    Simulating an N-of-M window across ~1 Hz ticks measures a different
    thing than the same window at 6.7 Hz and would produce a confidently
    wrong answer, which is worse than an honest "nicht geprüft".
    """
    cw = setup.confirmation_window
    cd = max(10, int((eff_cfg.get("processing") or {}).get("event_cooldown_seconds", 10) or 10))
    sch_rec = cam.get("schedule_record") or {}
    return [
        f"[motion] detection_trigger={setup.trigger_mode} · das Bewegungs-Gate "
        f"(2 von 3 Frames) läuft in der Simu NICHT — es braucht aufeinanderfolgende "
        f"Frames im Produktionstakt",
        f"[confirmation] confirmation_window={cw if cw else '(Standard n=3 in 5 s)'} — "
        f"die Simu prüft das Fenster NICHT; ein einzelner Treffer hier ist in der "
        f"Produktion noch kein Ereignis",
        "[wildlife] Wildtier-Kaskade, Vogelarten und Identitäts-Zuordnung laufen in "
        "der Simu NICHT — ein Eichhörnchen kann hier als schwache 'cat' erscheinen",
        f"[event_cooldown] {cd} s zwischen Ereignissen (person ausgenommen) — "
        f"in der Simu nicht geprüft",
        f"[recording] recording_enabled={bool(cam.get('recording_enabled', True))} · "
        f"schedule_record={sch_rec if sch_rec else '(kein Fenster)'} — in der Simu "
        f"nicht geprüft",
    ]
