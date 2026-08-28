"""SIMU-05h · 60-second cluster evidence for the panel's Debug tab.

Aggregates the per-camera ring buffers the detection pass fills
(``events`` and ``class_log`` on the tracker entry) into the five
clusters the frontend renders. Pruning happens here, on every call, so
the buffers stay bounded without a sweeper thread.
"""

from __future__ import annotations

import time as _time

from .. import app_state
from ._sim_pipeline import EVIDENCE_WINDOW_S


def build_cluster_evidence(entry: dict, cam: dict, obj_filter, ema_ms: float) -> dict:
    """The ``cluster_evidence`` payload for one tick."""
    now = _time.time()
    cutoff = now - EVIDENCE_WINDOW_S
    events = entry.get("events")
    if events is not None:
        while events and events[0][0] < cutoff:
            events.popleft()
    class_log = entry.get("class_log")
    if class_log is not None:
        while class_log and class_log[0][0] < cutoff:
            class_log.popleft()
    return {
        "cluster1": _continuity(events),
        "cluster2": _per_class(class_log, obj_filter),
        "cluster3": _off_filter(class_log),
        "cluster4": _performance(entry, cam, ema_ms),
        "cluster5": {"events_60s": _event_rows(events, now)},
    }


def _continuity(events) -> dict:
    """Cluster 1 · spawns / deaths / re-ids in the window."""
    deaths = spawns = reids = 0
    for ev in events or []:
        kind = ev[1]
        if kind == "spawn":
            spawns += 1
        elif kind == "death":
            deaths += 1
        elif kind == "reid":
            reids += 1
    return {
        "deaths_60s": deaths,
        "spawns_60s": spawns,
        "reid_attempts_60s": [],
        "reid_successes_60s": reids,
    }


def _per_class(class_log, obj_filter) -> dict:
    """Cluster 2 · per-class raw / pass / below counts.

    ``below`` now counts the TENTATIVE verdict — a detection the tracker
    keeps but that sits under its label's spawn threshold. The old
    ``belowthresh`` verdict meant "under detection_min_score", a bar the
    live pipeline stopped applying when the two-tier tracker landed.
    """
    per_class: dict = {}
    for _ts, lbl, verdict in class_log or []:
        bucket = per_class.setdefault(lbl, {"raw": 0, "pass": 0, "below": 0})
        bucket["raw"] += 1
        if verdict == "pass":
            bucket["pass"] += 1
        elif verdict == "tentative":
            bucket["below"] += 1
    missing = sorted(lbl for lbl in (obj_filter or ()) if lbl not in per_class)
    return {"per_class_60s_counts": per_class, "missing_classes_60s": missing}


def _off_filter(class_log) -> dict:
    """Cluster 3 · what the class filter dropped, per label."""
    off_filter: dict = {}
    for _ts, lbl, verdict in class_log or []:
        if verdict == "filtered":
            off_filter[lbl] = off_filter.get(lbl, 0) + 1
    return {"off_filter_60s_counts": off_filter}


def _performance(entry: dict, cam: dict, ema_ms: float) -> dict:
    """Cluster 4 · cadence + the runtime's own stream FPS."""
    runtime = app_state.runtimes.get(cam.get("id", ""))
    sub_fps = float(getattr(runtime, "_sub_fps", 0.0) or 0.0) if runtime else 0.0
    main_fps = float(getattr(runtime, "_main_fps", 0.0) or 0.0) if runtime else 0.0
    return {
        "tick_cycle_ema_ms": int(round(ema_ms)) if ema_ms > 0 else 0,
        "sub_fps": round(sub_fps, 1),
        "main_fps": round(main_fps, 1),
        # The cadence the tracker's miss-grace is actually computed
        # against — surfaced so the two clocks can never silently drift
        # apart again.
        "sim_tick_fps": round(float(entry.get("tick_fps") or 0.0), 2),
    }


def _event_rows(events, now: float) -> list:
    """Cluster 5 · raw event log, newest first."""
    rows = []
    for ts, kind, tn, lbl, sc, iou, extra in events or []:
        rows.append(
            {
                "kind": kind,
                "track_num": tn,
                "label": lbl,
                "score": sc,
                "iou": iou,
                "t_ago_seconds": round(now - ts, 1),
                "extra": extra,
            }
        )
    rows.reverse()
    return rows
