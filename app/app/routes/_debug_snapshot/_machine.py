"""The same snapshot, shaped for a machine instead of a reader.

"Vielleicht machst Du den Debug gar nicht so menschenlesefreundlich,
sondern eher maschinenfreundlich, dass wenn ich den kopiere — ich schau
mir den ja nie manuell an, ich paste den immer nur zum Debuggen ins
Codefenster."

So "Debug kopieren" now puts THIS document on the clipboard: one JSON
object, stable key names, units in the key (``_ms`` / ``_s``), raw typed
values, and no German sentence carrying a number inside it. Two
snapshots of the same camera diff line-by-line, which the ASCII tables in
the Markdown rendering never did.

The Markdown document (:mod:`._blocks`) stays — it is what
``GET …/debug-snapshot`` serves without ``format=json``, for the times a
human reads it in a terminal. Two renderings of one dataset is fine; two
renderings that DRIFT is not, so :data:`SECTION_KEYS` maps every Markdown
section onto its key here and ``test_simu_log`` fails the moment one
gains a section the other does not have.

Conventions, both deliberate:

* ``None`` means "not knowable", never 0. The Markdown's ``n/v`` says the
  same thing in prose; a reader that has to tell "the sub-stream is dead"
  from "nobody counts the sub-stream" gets a ``*_state`` sibling naming
  which it is.
* Frontend-only values (the next-tick delay, the bbox hold time, the
  browser's own view state) are ``None`` here and filled in by the
  browser immediately before the clipboard write. The Markdown uses
  ``<<placeholder>>`` tokens for the same reason.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone

from ...event_logic import is_schedule_window_active
from ._helpers import _scrub

#: Bump the minor when a key is added, the major when one changes
#: meaning or disappears. A consumer can then refuse a document it does
#: not understand instead of silently reading a renamed field as null.
SCHEMA = "squirreling.sightings.simu-debug/1"

#: Markdown section title → key in this document. The anti-drift table:
#: the two renderings are built from the same inputs but by different
#: code, so this is what makes "someone added a section to only one of
#: them" a test failure rather than a discovery six months later.
SECTION_KEYS = {
    "Befund": "findings",
    "Live-Status": "tick",
    "Alarm-Weg (Gates)": "gates",
    "Schwellen-Leiter (pro Klasse)": "ladder",
    "Motion-Gate": "motion",
    "Tracker-Schwellen (effektive Werte)": "tracker",
    "Zonen / Masken": "geometry",
    "Aktive Tracks": "tracks_active",
    "Detections (letzter Tick)": "detections",
    "Tracker-Ereignisse (letzte 60s)": "tracker_events_60s",
    "Decision-Trace (letzter Tick)": "trace",
    "Performance": "performance",
    "Server-Log (gefiltert)": "log",
    "Frontend State": "frontend",
}


def _num(val, default=None):
    """A float, or ``default`` — never a string and never a stray bool."""
    if val is None or isinstance(val, bool):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _int(val, default=None):
    num = _num(val)
    return default if num is None else int(round(num))


def _schedule(sched: dict) -> dict:
    """One schedule, as three facts rather than one German sentence.

    ``gates`` is False for a schedule that is absent or disabled — the
    distinction the Markdown spells out as "24/7 (deaktiviert → gilt
    immer)". ``active_now`` is None only when the window itself is
    unparsable, which is a bug worth seeing rather than smoothing over.
    """
    sched = sched or {}
    enabled = bool(sched.get("enabled"))
    if not enabled:
        return {"gates": False, "from": None, "to": None, "active_now": True}
    try:
        active = bool(is_schedule_window_active(sched))
    except Exception:  # pragma: no cover - defensive
        active = None
    return {
        "gates": True,
        "from": sched.get("from"),
        "to": sched.get("to"),
        "active_now": active,
    }


def _fps(runtime, attr: str) -> tuple:
    """``(value, state)`` — the honest form of a counter that may not exist.

    ``0.0`` alone reads as "the stream is dead"; the state says which of
    the four situations produced the number.
    """
    if runtime is None:
        return None, "no_runtime"
    if not hasattr(runtime, attr):
        return None, "not_measured"
    num = _num(getattr(runtime, attr, None))
    if num is None:
        return None, "unparsable"
    if num <= 0.0:
        return 0.0, "no_full_window"
    return round(num, 1), "ok"


def _tick_block(last: dict, diag: dict, cluster_ev: dict) -> dict:
    fs = last.get("frame_size") or {}
    c4 = cluster_ev.get("cluster4") or {}
    src = diag.get("frame_src")
    return {
        "seen": bool(last),
        "frame_src": src,
        "frame_mode": (
            "sub-fast" if src == "sub" else "main-slow" if src == "main_fallback" else src
        ),
        "frame_w": _int(fs.get("w"), 0),
        "frame_h": _int(fs.get("h"), 0),
        "frame_age_ms": _int(last.get("frame_age_ms"), 0),
        "frame_interval_avg_ms": _int(diag.get("frame_interval_avg_ms"), 0),
        "inference_ms": _int(diag.get("inference_ms"), 0),
        "cycle_ema_ms": _int(c4.get("tick_cycle_ema_ms"), 0),
        "validator_profile": diag.get("validator_profile"),
        # Browser-owned — see the module docstring.
        "next_ms": None,
        "hold_ms": None,
    }


def _gates_block(cam: dict) -> dict:
    return {
        "armed": cam.get("armed", True) is not False,
        "telegram_enabled": cam.get("telegram_enabled", True) is not False,
        "recording_enabled": cam.get("recording_enabled", True) is not False,
        "schedule_notify": _schedule(cam.get("schedule_notify") or {}),
        "schedule_record": _schedule(cam.get("schedule_record") or {}),
        "class_severity": dict(cam.get("class_severity") or {}),
    }


def _ladder_block(rows) -> list:
    """The resolved detect→spawn→confirm→push ladder, one row per class.

    ``dead_zone`` is a property on :class:`EffectiveThresholds`, so
    ``asdict`` drops it — and it is the single most diagnostic bit in the
    whole document ("erkannt ab 0.45, gemeldet erst ab 0.85"). Put back
    explicitly rather than recomputed: one owner of the comparison.
    """
    out = []
    for eff in rows or []:
        row = asdict(eff) if is_dataclass(eff) else dict(eff)
        row["dead_zone"] = bool(getattr(eff, "dead_zone", False))
        out.append(row)
    return out


def _motion_block(cam: dict, eff_cfg: dict) -> dict:
    """The motion gate, with the fallbacks resolved rather than hinted.

    ``0.0`` is the schema's "unset" marker on two of these fields, so the
    raw value AND what it resolves to both travel — a consumer comparing
    two snapshots needs the raw one, a consumer asking "what floor is in
    force" needs the effective one.
    """
    wl_global = _num(((eff_cfg.get("processing") or {}).get("wildlife") or {}).get("min_score"))
    wl_cam = _num(cam.get("wildlife_min_score"), 0.0) or 0.0
    return {
        "detection_trigger": cam.get("detection_trigger", "motion_and_objects"),
        "motion_enabled": cam.get("motion_enabled", True) is not False,
        "motion_sensitivity": _num(cam.get("motion_sensitivity"), 0.5),
        "wildlife_motion_sensitivity": _num(cam.get("wildlife_motion_sensitivity"), 0.0),
        "wildlife_motion_sensitivity_derived": _num(cam.get("wildlife_motion_sensitivity"), 0.0)
        <= 0.0,
        "post_motion_tail_s": _num(cam.get("post_motion_tail_s"), 0.0),
        "roi_mode": cam.get("roi_mode", "off"),
        "wildlife_min_score": wl_cam,
        "wildlife_min_score_effective": wl_global if wl_cam <= 0.0 else wl_cam,
        "wildlife_min_score_source": "global" if wl_cam <= 0.0 else "camera",
    }


def _tracker_block(cam: dict) -> dict:
    """Per-camera tracker overrides. ``None`` = falls back to the
    tracker_core default; the schema writes that state as 0.0, which a
    bare number would report as "accepts anything"."""

    def override(key):
        val = _num(cam.get(key), 0.0) or 0.0
        return val if val > 0.0 else None

    return {
        "track_spawn_min_score": override("track_spawn_min_score"),
        "track_continue_min_score": override("track_continue_min_score"),
        "track_miss_grace_seconds": override("track_miss_grace_seconds"),
        "track_iou_match_threshold": override("track_iou_match_threshold"),
        "object_filter": sorted(cam.get("object_filter") or []),
        "excluded_classes": sorted(cam.get("excluded_classes") or []),
    }


def _tracks_block(runtime) -> list:
    if runtime is None or not hasattr(runtime, "_tracker"):
        return []
    out = []
    for tr in getattr(runtime._tracker.state, "active", []) or []:
        out.append(
            {
                "track_id": getattr(tr, "track_id", None),
                "label": getattr(tr, "label", None),
                "samples": len(getattr(tr, "samples", []) or []),
                "missed_windows": _int(getattr(tr, "missed_windows", 0), 0),
                "best_score": _num(getattr(tr, "best_score", 0.0), 0.0),
            }
        )
    return out


def _detections_block(last: dict, cluster_ev: dict) -> dict:
    dets = last.get("detections") or []

    def rows(verdict):
        return [
            {
                "track_num": d.get("track_num"),
                "label": d.get("label"),
                "score": _num(d.get("score"), 0.0),
            }
            for d in dets
            if d.get("verdict") == verdict
        ]

    off = (cluster_ev.get("cluster3") or {}).get("off_filter_60s_counts") or {}
    return {
        "pass": rows("pass"),
        "tentative": rows("tentative"),
        "off_filter_60s": {str(k): _int(v, 0) for k, v in off.items()},
    }


def _events_block(cluster_ev: dict) -> list:
    events = (cluster_ev.get("cluster5") or {}).get("events_60s") or []
    return [
        {
            "t_ago_s": _int(ev.get("t_ago_seconds"), 0),
            "kind": ev.get("kind"),
            "track_num": ev.get("track_num"),
            "label": ev.get("label"),
            "extra": ev.get("extra") or None,
        }
        for ev in events
    ]


def _performance_block(cluster_ev: dict, diag: dict, runtime) -> dict:
    c4 = cluster_ev.get("cluster4") or {}
    main_fps, main_state = _fps(runtime, "_main_fps")
    sub_fps, sub_state = _fps(runtime, "_sub_fps")
    return {
        "tick_cycle_ema_ms": _int(c4.get("tick_cycle_ema_ms"), 0),
        "sim_frame_src": diag.get("frame_src"),
        "alarm_pipeline_src": "main",
        "main_stream_fps": main_fps,
        "main_stream_fps_state": main_state,
        "sub_stream_fps": sub_fps,
        "sub_stream_fps_state": sub_state,
    }


def _log_block(records) -> list:
    """Ring-buffer lines, already narrowed to this camera by
    ``collect_log_lines``. Scrubbed here for the same reason the Markdown
    scrubs them: the document leaves the box."""
    return [
        {
            "ts": rec.get("ts"),
            "level": rec.get("level"),
            "msg": _scrub(rec.get("msg") or ""),
        }
        for rec in records or []
    ]


def build_document(**ctx) -> dict:
    """The machine-readable snapshot. Keys mirror :data:`SECTION_KEYS`."""
    cam = ctx["cam"]
    cluster_ev = ctx["cluster_ev"]
    last = ctx["last"]
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "camera": {"id": ctx["cam_id"], "name": cam.get("name") or ctx["cam_id"]},
        "findings": list(ctx["findings"]),
        "tick": _tick_block(last, ctx["diag"], cluster_ev),
        "gates": _gates_block(cam),
        "ladder": _ladder_block(ctx["ladder"]),
        "motion": _motion_block(cam, ctx["eff_cfg"] or {}),
        "tracker": _tracker_block(cam),
        "geometry": {
            "zones": len(cam.get("zones") or []),
            "masks": len(cam.get("masks") or []),
        },
        "tracks_active": _tracks_block(ctx["runtime"]),
        "detections": _detections_block(last, cluster_ev),
        "tracker_events_60s": _events_block(cluster_ev),
        "trace": list(last.get("trace") or []),
        "performance": _performance_block(cluster_ev, ctx["diag"], ctx["runtime"]),
        "log": _log_block(ctx["log_records"]),
        # Browser-owned; the frontend merges its own block in before the
        # clipboard write and before POSTing the run to the SIMU log.
        "frontend": {},
    }
