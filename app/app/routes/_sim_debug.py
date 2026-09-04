"""The structured payloads the Simulieren panel reads.

Two of them, and the split is the point:

* ``build_diag`` — the Diagnose panel every tick gets. Moved here out of
  ``coral_test_detection.py``, which is the orchestrator and was at its
  file ceiling; nothing about it changed in the move.
* ``build_debug`` — the ``?debug=1`` block. Every box the detector
  returned including the ones under the tracker floor, and every track
  the panel's tracker is holding, with the state that decided its fate.

The debug block is REPORTING only. It costs no extra inference (the
lower score cut rides on the full-frame pass the tick already pays for,
see ``_sim_pipeline.detect``) and nothing in it feeds a gate, so a tick
with the flag decides exactly what the same tick without it would have
decided. That is the property the tests pin.

``modes`` ships on every tick, flag or no flag: which device actually
ran the inference, what the camera's role and alarm profile are, and
which ROI mode is configured versus which one this tick ran. It is
three lines of JSON that answer the first three questions anyone asks
about a surprising result.
"""

from __future__ import annotations

import time as _time

from ..detectors._describe import describe_backend, describe_models
from ..thresholds._apply import camera_role
from ._sim_frame import capture_lag_s
from ._sim_pipeline import (
    VERDICT_FILTERED,
    VERDICT_MASKED,
    VERDICT_NO_TRACK,
    VERDICT_OUTSIDE_ZONE,
    VERDICT_TENTATIVE,
    bbox_xywh,
)

#: Score cut for the debug pass. Low enough to show what the tracker
#: floor is throwing away, high enough that a busy frame does not come
#: back with a hundred boxes nobody can read.
DEBUG_RAW_FLOOR = 0.05

#: Closed tracks kept in the debug block. The interesting one is almost
#: always the track that just died, not the fiftieth before it.
CLOSED_TRACKS = 8


def build_diag(
    *, setup, sim, pick, rt, det_mode, mode_override, stream_pref, stream_override, snap
):
    """Structured payload for the in-modal Diagnose panel.

    ``parity`` is new and is the point of this change: the panel now
    declares, in machine-readable form, which of its controls are NOT
    the camera's configuration, so the UI can mark them rather than
    letting the operator read an experiment as production.
    """
    snap_w, snap_h, snap_scale = snap
    lag_s = capture_lag_s(rt)
    return {
        "frame_src": pick.src or "main",
        "stream_pref": stream_pref,
        "det_mode": det_mode,
        "sahi": sim.sahi_diag,
        "parity": {
            "config_mode": setup.det_mode,
            "mode_override": bool(mode_override),
            "stream_override": bool(stream_override),
            "sim_tick_fps": round(sim.tick_fps, 2),
            # Gates production runs that this endpoint does not — the UI
            # renders them as "nicht geprüft" instead of implying a pass.
            "not_simulated": [
                "motion_gate",
                "confirmation_window",
                "wildlife_cascade",
                "bird_species",
                "identity",
                "event_cooldown",
                "recording_schedule",
                "frame_validator",
            ],
        },
        "sub_stream_available": bool(getattr(rt, "_preview_frame", None) is not None),
        "frame_size": {"w": int(sim.frame_w), "h": int(sim.frame_h)},
        "frame_age_ms": int(pick.age_ms),
        "capture_lag_ms": (None if lag_s is None else int(lag_s * 1000)),
        # Asked of the detector, not asserted. This was hard-coded True,
        # and it lied on the one path where the answer matters: when
        # another process holds the Coral stick the detector walks down
        # to its CPU tier and the tick returns a perfectly ordinary 200 —
        # so the operator saw "coral_available: true" next to inference
        # that was running on the CPU. The failure mode with no failure
        # response is exactly the one a diagnostic has to name.
        "coral_available": describe_backend(getattr(rt, "detector", None))["device"] == "tpu",
        "inference_ms": int(sim.inference_ms),
        # What this tick ACTUALLY cost. The full-frame pass is now reused
        # by the tiling stage exactly as production's rescue reuses it,
        # so this is the number production would pay too.
        "mode_invokes": int(sim.invokes),
        "gates": {
            "raw": int(sim.raw_count),
            "pass": len(sim.pass_rows),
            "tentative": sim.count(VERDICT_TENTATIVE),
            # Back-compat key for the existing frontend counters.
            "belowthresh": sim.count(VERDICT_TENTATIVE),
            "no_track": sim.count(VERDICT_NO_TRACK),
            "filtered": sim.count(VERDICT_FILTERED),
            "masked": sim.count(VERDICT_MASKED),
            "outside_zone": sim.count(VERDICT_OUTSIDE_ZONE),
        },
        "top_raw": [{"label": r["label"], "score": r["score"]} for r in sim.rows[:3]],
        "thresholds": {
            "floor": round(setup.floor, 3),
            "spawn": round(setup.spawn_default, 3),
            # Reported, never applied — see DetectionSetup.min_score.
            "global": round(setup.min_score, 3),
            "per_class": dict(setup.label_thresholds),
        },
        "object_filter": sorted(setup.object_filter),
        "excluded_classes": sorted(setup.excluded_classes),
        "validator_profile": (pick.profile.name if pick.profile else None),
        "validator_reason": pick.validator_reason or None,
        "source_frame_size": {"w": int(sim.frame_w), "h": int(sim.frame_h)},
        "snapshot_frame_size": {"w": int(snap_w), "h": int(snap_h)},
        "bbox_space": "source" if snap_scale == 1.0 else "snapshot",
    }


def modes_block(*, rt, cam_cfg: dict, setup, det_mode: str) -> dict:
    """Which machine, which job, which framing — every tick.

    ``roi_mode`` is what the camera is CONFIGURED for and
    ``roi_mode_active`` is what this tick actually ran; they differ
    whenever the operator drives the mode switch, and a reader who sees
    only one of the two cannot tell an experiment from production.
    """
    return {
        "inference": describe_backend(getattr(rt, "detector", None)),
        "role": camera_role(cam_cfg),
        "alarm_profile": cam_cfg.get("alarm_profile"),
        "detection_trigger": cam_cfg.get("detection_trigger"),
        "roi_mode": setup.det_mode,
        "roi_mode_active": det_mode,
    }


def models_block(rt) -> dict:
    """The stage → model file/sha table this tick's boxes join against.

    The same table ``event["provenance"]["models"]`` carries, from the
    same builder, so the live surface and a recorded clip name one model
    identically. Without it a live row could only ever say which STAGE
    labelled a box, never which model file did — the file names live on
    the runtime's interpreters, not on the boxes.
    """
    return describe_models(
        getattr(rt, "detector", None),
        getattr(rt, "bird_classifier", None),
        getattr(rt, "wildlife_classifier", None),
    )


def _det_row(d, floor: float) -> dict:
    """One detector box, before any gate saw it."""
    score = round(float(d.score), 4)
    return {
        "label": d.label,
        "score": score,
        "bbox": bbox_xywh(d),
        # Which cascade stage produced it. Always the object detector
        # here — the panel deliberately runs no classifier — and saying
        # so is the point: it is why a bird arrives as ``bird`` and not
        # as a species.
        "model": getattr(d, "model", None),
        "above_floor": score >= float(floor),
    }


def _track_row(tr, *, display_nums: dict, now_s: float, state: str) -> dict:
    samples = getattr(tr, "samples", None) or []
    first_t = samples[0].get("t") if samples else None
    last_t = samples[-1].get("t") if samples else None
    last_score = samples[-1].get("score") if samples else None
    last_iou = getattr(tr, "last_iou", None)
    return {
        # The badge the overlay draws AND the id the tracker keys on:
        # the operator reads one, the log line carries the other.
        "id": display_nums.get(tr.track_id),
        "track_id": tr.track_id,
        "state": state,
        "label": tr.label,
        "model": getattr(tr, "model", None),
        "age_s": None if first_t is None else round(max(0.0, now_s - float(first_t)), 2),
        # Time since the last sample of any kind — how close a coasting
        # track is to its grace window running out.
        "idle_s": None if last_t is None else round(max(0.0, now_s - float(last_t)), 2),
        "misses": int(getattr(tr, "missed_windows", 0) or 0),
        # None = the newborn distance gate matched it, not an overlap.
        "last_iou": None if last_iou is None else round(float(last_iou), 4),
        "score": None if last_score is None else round(float(last_score), 4),
        "best_score": round(float(getattr(tr, "best_score", 0.0) or 0.0), 4),
        "samples": len(samples),
        "end_reason": getattr(tr, "end_reason", None),
    }


def _active_state(tr) -> str:
    """``coasting`` is a distinct state, not a shade of active: the
    track is alive on the miss-grace window, holding an id for a subject
    nothing detected this tick. Reporting it as ``active`` hides the
    most common reason a track outlives what the operator can see."""
    return "coasting" if int(getattr(tr, "missed_windows", 0) or 0) > 0 else "active"


def track_rows(entry: dict, now_s: float) -> list:
    """Every track the panel's tracker holds — the live ones first, then
    the handful it has already closed."""
    state = getattr(entry.get("tracker"), "state", None)
    if state is None:
        return []
    display_nums = entry.get("display_nums") or {}
    rows = [
        _track_row(tr, display_nums=display_nums, now_s=now_s, state=_active_state(tr))
        for tr in list(getattr(state, "active", []) or [])
    ]
    rows += [
        _track_row(tr, display_nums=display_nums, now_s=now_s, state="closed")
        for tr in list(getattr(state, "closed", []) or [])[-CLOSED_TRACKS:]
    ]
    return rows


def build_debug(*, entry: dict, sim, setup, now_s: float | None = None) -> dict:
    """The ``?debug=1`` block: the detector's unfiltered output plus the
    tracker's full state.

    ``raw_detections`` does not repeat the verdicts in ``detections`` —
    it is the layer underneath them, the boxes as the model returned
    them, reaching under the tracker floor so the near-misses are
    visible at all. Tile hits are not in it: tiles run at the floor, and
    a sub-floor tile pass would cost real inference.
    """
    now = _time.monotonic() if now_s is None else float(now_s)
    floor = float(setup.floor)
    raw = [_det_row(d, floor) for d in (getattr(sim, "full_scan", None) or [])]
    raw.sort(key=lambda r: r["score"], reverse=True)
    return {
        "raw_floor": round(DEBUG_RAW_FLOOR, 4),
        "track_floor": round(floor, 4),
        "spawn_floor": round(float(setup.spawn_default), 4),
        "raw_detections": raw,
        "raw_below_floor": sum(1 for r in raw if not r["above_floor"]),
        "tracks": track_rows(entry, now),
    }
