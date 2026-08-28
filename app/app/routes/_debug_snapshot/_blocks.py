"""One function per Markdown section of the debug snapshot.

Section order is the diagnosis order: verdict first, then the gates that
can silence an alert, then the raw evidence. The server log rides near
the end because it is the longest block and the least often needed once
the gates above have answered the question.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ._findings import _ladder_block
from ._helpers import (
    _UNKNOWN,
    _fenced,
    _fmt_float,
    _fmt_fps,
    _fmt_schedule,
    _log_block,
    _section,
)


def _head_block(cam: dict, cam_id: str) -> str:
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (
        "# Squirreling · Sightings Live-Detect Debug Snapshot\n"
        f"Camera: {cam.get('name') or cam_id} (id: {cam_id})\n"
        f"Timestamp: {now_iso}\n"
        "User-Agent: <<frontend_state_ua>>\n"
    )


def _live_status_block(cam: dict, last: dict, diag: dict, cluster_ev: dict) -> str:
    fs = last.get("frame_size") or {"w": 0, "h": 0}
    c4 = cluster_ev.get("cluster4") or {}
    src = diag.get("frame_src") or _UNKNOWN
    mode = "sub-fast" if src == "sub" else "main-slow" if src == "main_fallback" else src
    infer = int(round(float(diag.get("inference_ms") or 0)))
    # `next` and `hold` are frontend scheduler state — the server never
    # sees them. Placeholders, substituted at clipboard-write time.
    return _fenced(
        [
            f"TICK     {'ok' if last else 'noch kein Tick'} · "
            f"{int(diag.get('frame_interval_avg_ms') or 0)} ms · next <<tick_next_ms>>",
            f"QUELLE   {mode} · {fs.get('w', 0)}×{fs.get('h', 0)} · "
            f"age {last.get('frame_age_ms') or 0} ms · inference {infer} ms",
            f"CADENCE  avg_cycle {c4.get('tick_cycle_ema_ms', 0)} · hold <<hold_ms>> · "
            f"drops {c4.get('dropped_ticks_session', 0)}",
            f"PROFIL   {diag.get('validator_profile') or _UNKNOWN} · "
            f"ARMED={'true' if cam.get('armed', True) else 'false'}",
        ]
    )


def _gates_block(cam: dict) -> str:
    sev = cam.get("class_severity") or {}
    return _fenced(
        [
            f"armed:             {'true' if cam.get('armed', True) else 'false'}",
            f"telegram_enabled:  {'true' if cam.get('telegram_enabled', True) else 'false'}",
            f"recording_enabled: {'true' if cam.get('recording_enabled', True) else 'false'}",
            f"schedule_notify:   {_fmt_schedule(cam.get('schedule_notify') or {})}",
            f"schedule_record:   {_fmt_schedule(cam.get('schedule_record') or {})}",
            "class_severity:    "
            + (" · ".join(f"{k}={v}" for k, v in sorted(sev.items())) if sev else "(leer)"),
        ]
    )


def _motion_block(cam: dict, eff_cfg: dict) -> str:
    wl_global = (
        ((eff_cfg.get("processing") or {}).get("wildlife") or {}).get("min_score")
        if eff_cfg
        else None
    )
    wl_cam = float(cam.get("wildlife_min_score") or 0.0)
    wl_line = _fmt_float(wl_cam)
    if wl_cam <= 0.0:
        wl_line += f" (0 → global processing.wildlife.min_score = {_fmt_float(wl_global)})"
    wl_motion = float(cam.get("wildlife_motion_sensitivity") or 0.0)
    wl_motion_line = _fmt_float(wl_motion)
    if wl_motion <= 0.0:
        wl_motion_line += " (0 → aus motion_sensitivity abgeleitet)"
    return _fenced(
        [
            # NB: the config key is `detection_trigger`, not `trigger_mode`,
            # and the sensitivity key is `motion_sensitivity`. The older
            # snapshot asked for the wrong names and printed "?" forever.
            f"detection_trigger:  {cam.get('detection_trigger', 'motion_and_objects')}",
            f"motion_enabled:     {'true' if cam.get('motion_enabled', True) else 'false'}",
            f"motion_sensitivity: {_fmt_float(cam.get('motion_sensitivity', 0.5))}",
            f"wildlife_motion_sensitivity: {wl_motion_line}",
            f"post_motion_tail_s: {_fmt_float(cam.get('post_motion_tail_s', 0.0), 1)}",
            f"roi_mode:           {cam.get('roi_mode', 'off')}",
            f"wildlife_min_score: {wl_line}",
        ]
    )


def _tracks_block(runtime) -> str:
    if runtime is None or not hasattr(runtime, "_tracker"):
        return f"({_UNKNOWN} — kein Runtime-Thread für diese Kamera)"
    rows = []
    for tr in getattr(runtime._tracker.state, "active", []) or []:
        rows.append(
            "#{} {} · samples {} · misses {} · best {:.2f}".format(
                getattr(tr, "track_id", ""),
                getattr(tr, "label", "?"),
                len(getattr(tr, "samples", []) or []),
                getattr(tr, "missed_windows", 0),
                getattr(tr, "best_score", 0.0),
            )
        )
    return _fenced(rows) if rows else "(keine)"


def _tracker_override(cam: dict, key: str, digits: int = 2) -> str:
    """A per-camera tracker override, or an explicit "falls back to the
    module default" note. 0.0 is the schema's "unset" marker here, so
    printing a bare 0.00 would claim the tracker accepts anything."""
    val = float(cam.get(key) or 0.0)
    if val <= 0.0:
        return "0.00 (nicht gesetzt → tracker_core-Default)"
    return _fmt_float(val, digits)


def _tracker_thresholds_block(cam: dict) -> str:
    return _fenced(
        [
            f"track_spawn_min_score:     {_tracker_override(cam, 'track_spawn_min_score')}",
            f"track_continue_min_score:  {_tracker_override(cam, 'track_continue_min_score')}",
            f"track_miss_grace_seconds:  {_tracker_override(cam, 'track_miss_grace_seconds', 1)}",
            f"track_iou_match_threshold: {_tracker_override(cam, 'track_iou_match_threshold')}",
            "object_filter:    " + str(sorted(cam.get("object_filter") or []) or "(alle Klassen)"),
            "excluded_classes: " + str(sorted(cam.get("excluded_classes") or []) or "(keine)"),
        ]
    )


def _events_block(cluster_ev: dict) -> str:
    events = (cluster_ev.get("cluster5") or {}).get("events_60s") or []
    if not events:
        return "(keine)"
    lines = []
    for ev in events:
        lines.append(
            "-{}s  {:6s}  #{} {} {}".format(
                ev.get("t_ago_seconds", 0),
                (ev.get("kind") or "").upper(),
                ev.get("track_num"),
                ev.get("label", ""),
                ev.get("extra", ""),
            ).rstrip()
        )
    return _fenced(lines)


def _detections_block(last: dict, cluster_ev: dict) -> str:
    out = last.get("detections") or []

    def _fmt(dets, with_track):
        return ", ".join(
            (
                f"#{d.get('track_num', '?')} {d['label']} "
                f"{int(round((d.get('score') or 0) * 100))}%"
                if with_track
                else f"{d['label']} {int(round((d.get('score') or 0) * 100))}%"
            )
            for d in dets
        )

    passed = [d for d in out if d.get("verdict") == "pass"]
    below = [d for d in out if d.get("verdict") == "belowthresh"]
    off = (cluster_ev.get("cluster3") or {}).get("off_filter_60s_counts") or {}
    top_off = sorted(off.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return _fenced(
        [
            "PASS:    " + (_fmt(passed, True) or "(keine)"),
            "u.Schw:  " + (_fmt(below, False) or "(keine)"),
            "gefiltert (60s, top 5): "
            + (", ".join(f"{lbl} {n}×" for lbl, n in top_off) or "(keine)"),
        ]
    )


def _perf_block(cluster_ev: dict, diag: dict, runtime) -> str:
    c4 = cluster_ev.get("cluster4") or {}
    src = diag.get("frame_src") or _UNKNOWN
    return _fenced(
        [
            f"tick_cycle_ema_ms:     {c4.get('tick_cycle_ema_ms', 0)}",
            f"dropped_ticks_session: {c4.get('dropped_ticks_session', 0)}",
            f"sim_frame_src:         {src} (Simulator)",
            "alarm_pipeline_src:    main (camera_runtime/_main_loop)",
            f"main_stream_fps:       {_fmt_fps(runtime, '_main_fps')}",
            f"sub_stream_fps:        {_fmt_fps(runtime, '_sub_fps')}",
        ]
    )


def assemble(**ctx) -> str:
    """Stitch the sections into the finished document."""
    cam = ctx["cam"]
    cluster_ev = ctx["cluster_ev"]
    trace = ctx["last"].get("trace") or []
    findings = "\n".join(f"- [{f['tone']}] {f['text']}" for f in ctx["findings"])
    zones = cam.get("zones") or []
    masks = cam.get("masks") or []
    return (
        _head_block(cam, ctx["cam_id"])
        + _section("Befund", findings)
        + _section("Live-Status", _live_status_block(cam, ctx["last"], ctx["diag"], cluster_ev))
        + _section("Alarm-Weg (Gates)", _gates_block(cam))
        + _section("Schwellen-Leiter (pro Klasse)", _ladder_block(ctx["ladder"]))
        + _section("Motion-Gate", _motion_block(cam, ctx["eff_cfg"]))
        + _section("Tracker-Schwellen (effektive Werte)", _tracker_thresholds_block(cam))
        + _section(
            "Zonen / Masken",
            _fenced([f"Inklusiv-Zonen: {len(zones)}", f"Exklusiv-Masken: {len(masks)}"]),
        )
        + _section("Aktive Tracks", _tracks_block(ctx["runtime"]))
        + _section("Detections (letzter Tick)", _detections_block(ctx["last"], cluster_ev))
        + _section("Tracker-Ereignisse (letzte 60s)", _events_block(cluster_ev))
        + _section(
            "Decision-Trace (letzter Tick)",
            _fenced(trace) if trace else "(keine — noch kein erfolgreicher Tick)",
        )
        + _section("Performance", _perf_block(cluster_ev, ctx["diag"], ctx["runtime"]))
        + _section("Server-Log (gefiltert)", _log_block(ctx["cam_id"], ctx["log_records"]))
        + _section("Frontend State", "<<frontend_state>>")
    )
