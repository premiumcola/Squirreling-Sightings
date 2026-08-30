"""Per-camera test-detection endpoint — the "Erkennung jetzt simulieren"
backend.

This module is the ORCHESTRATOR only. The work lives next door:

  * ``_sim_frame``    — frame acquisition contract + snapshot encoding
  * ``_sim_pipeline`` — the detection pass, on production's setup
  * ``_sim_trace``    — the German decision trace (capture → tracker)
  * ``_sim_routing``  — the downstream notification trace
  * ``_sim_evidence`` — the 60-s cluster aggregates for the Debug tab

The operator's requirement is that this panel show the pipeline that
actually runs. It therefore builds its configuration from the same
``detect_setup.build_detection_setup`` the alarm loop uses, applies the
same gates in the same order, and steps a tracker with the same
parameters. Three things stay deliberately different, and every one of
them is STATED in the trace rather than left for the operator to
discover:

  1. the tracker OBJECT (own instance — stepping the live one would
     shift real track ids and real events);
  2. the frame INSTANCE (the panel reads the newest frame in the reader
     slot; the loop reads the frame it is processing);
  3. the tick CADENCE (~1 Hz over HTTP vs ~6.7 Hz in the loop) — with
     every cadence-derived number computed against the measured tick
     clock, which is what the old hand-rolled tracker call got wrong.

The frame validator is the fourth: the alarm pipeline must refuse frames
it judges broken, a diagnostic view must show the current frame whatever
it looks like. See ``_sim_frame.acquire_frame``.
"""

from __future__ import annotations

import logging
import time as _time

from flask import Blueprint, jsonify, request

from .. import app_state
from ..detect_setup import apply_bottom_crop, build_detection_setup
from . import _sim_evidence, _sim_frame, _sim_pipeline, _sim_routing, _sim_trace
from ._sim_guard import affordability, busy_payload, record_cost, refusal_payload, sim_slot
from ._sim_tiling import VALID_MODES

bp = Blueprint("coral_test_detection", __name__)
log = logging.getLogger(__name__)


def _requested_det_mode(setup_mode: str) -> tuple[str, bool]:
    """``(mode, is_override)``.

    Defaults to the camera's configured ``roi_mode`` — the panel used to
    default to ``off`` and take whatever the ``?mode=`` switch said, so
    it could be tiling 3×3 while the camera ran none of it, with nothing
    on screen saying the mode was not the camera's. The switch survives
    as a deliberate experiment control ("was würde 3×3 finden?"); a
    non-default selection is flagged into the trace and the diag.
    """
    raw = (request.args.get("mode") or "").strip().lower()
    if not raw or raw not in VALID_MODES:
        return setup_mode, False
    return raw, raw != setup_mode


def _requested_stream() -> tuple[str, bool]:
    """``(stream, is_override)`` — main unless the operator asked for sub."""
    pref = (request.args.get("stream") or "main").strip().lower()
    if pref not in ("main", "sub"):
        pref = "main"
    return pref, pref != "main"


@bp.post('/api/cameras/<cam_id>/test-detection')
def api_test_detection(cam_id: str):
    """Admission control in front of the real handler.

    Both gates exist because a tiled mode used to fail DISHONESTLY: the
    tick never completed, the client watchdog aborted and re-issued it
    (adding another ten-inference job to a handler Flask cannot cancel),
    and the operator was shown "Verbindung zur Kamera unterbrochen" for
    what was really a request nobody could afford. See routes/_sim_guard.
    """
    cam = app_state.settings.get_camera(cam_id)
    if not cam:
        return jsonify({"error": "camera not found"}), 404
    setup_mode = build_detection_setup(cam_id, cam).det_mode
    det_mode, _ = _requested_det_mode(setup_mode)
    with sim_slot(cam_id) as slot:
        if not slot.acquired:
            return jsonify(busy_payload(cam_id)), 429
        verdict = affordability(cam_id, det_mode)
        if not verdict["ok"]:
            return jsonify(refusal_payload(cam_id, det_mode, verdict)), 429
        return _run_test_detection(cam_id, cam, det_mode)


def _run_test_detection(cam_id: str, cam: dict, det_mode_hint: str):
    """One simulated tick: acquire → detect → gate → track → explain."""
    rt = app_state.runtimes.get(cam_id)
    if rt is None:
        return jsonify({"error": "Kamera-Runtime nicht aktiv (deaktiviert?)"}), 503
    # Q2-5 · note this poll so a connectivity drop gets one INFO line.
    _sim_frame.note_client_request(cam_id)
    stream_pref, _ = _requested_stream()
    pick = _sim_frame.acquire_frame(rt, cam_id, stream_pref)
    if pick.frame is None:
        return _frame_failure_response(cam_id, pick)
    # The divergence is what was SERVED, not what was asked for: a
    # requested sub-stream that turned out to be unavailable falls back
    # to main, and flagging that tick as "läuft auf dem Sub-Stream"
    # would be the same class of lie this whole change removes.
    stream_override = pick.src != "main"
    detector = getattr(rt, "detector", None)
    if not detector or not getattr(detector, "available", False):
        log.warning(
            "[test-detection] cam=%s outcome=coral_unavailable waited=%.2fs "
            "retries=%d frame_age_ms=%d frame_src=%s",
            cam_id,
            pick.waited_s,
            pick.retries,
            pick.age_ms,
            pick.src,
        )
        return jsonify({"error": "Coral nicht verfügbar (motion-only?)"}), 503

    # The config PRODUCTION runs, not a second reading of it. rt.cfg is
    # the runtime's live view of the camera; the store's copy is the
    # fallback for a stub runtime. Resolved once here and handed down, so
    # the thresholds and the mask/zone polygons can never come from two
    # different readings of the camera.
    cam_cfg = getattr(rt, "cfg", None) or cam
    setup = build_detection_setup(
        cam_id,
        cam_cfg,
        global_cfg=app_state.get_effective_config(),
    )
    # The mode the admission gate PRICED is the mode this tick may run —
    # resolving it a second time here would let the handler spend an
    # unbudgeted 3×3 if the two readings ever disagreed.
    det_mode = det_mode_hint
    mode_override = det_mode != setup.det_mode
    entry = _sim_pipeline.get_test_tracker(cam_id, setup)
    entry["last_call_ts"] = _time.monotonic()
    try:
        sim = _run_pass(rt, cam_cfg, cam_id, setup, pick.frame, det_mode, entry)
    except Exception as e:  # noqa: BLE001 — a diagnostic must not 500
        log.warning("[test-detection] %s inference failed: %s", cam_id, e)
        return jsonify({"error": f"Inference fehlgeschlagen: {e}"}), 500
    record_cost(cam_id, det_mode, sim.inference_ms, sim.invokes)
    return _respond(
        rt=rt,
        cam=cam,
        cam_id=cam_id,
        setup=setup,
        sim=sim,
        pick=pick,
        entry=entry,
        det_mode=det_mode,
        mode_override=mode_override,
        stream_pref=stream_pref,
        stream_override=stream_override,
    )


def _run_pass(rt, cam_cfg, cam_id, setup, frame, det_mode, entry) -> _sim_pipeline.SimPass:
    """Production's sequence, with every dropped box kept and labelled."""
    proc_frame = apply_bottom_crop(frame, setup.bottom_crop_px)
    h_px, w_px = proc_frame.shape[:2]
    motion_box = _sim_pipeline.sim_motion_box(cam_id, proc_frame) if det_mode == "roi" else None
    t0 = _time.monotonic()
    raw, sahi_diag, invokes = _sim_pipeline.detect(
        rt.detector, proc_frame, setup, det_mode, motion_box
    )
    inference_ms = int(round((_time.monotonic() - t0) * 1000))
    # The camera CONFIG goes into the gates, not the runtime object: the
    # mask and zone POLYGONS are read from it, but the compiled rasters
    # are the panel's own — a diagnostic must not be able to rebuild the
    # alarm loop's cache. See _sim_pipeline._SIM_MASK_ZONES.
    survivors, drops = _sim_pipeline.run_gates(cam_cfg, proc_frame, raw, setup)
    tick_fps = _sim_pipeline.measure_tick_fps(entry)
    num_by_det, no_track = _sim_pipeline.run_tracker(entry, survivors, setup, w_px, h_px, tick_fps)
    rows = _sim_pipeline.build_rows(survivors, drops, num_by_det, no_track, setup)
    wall_now = _time.time()
    for r in rows:
        entry["class_log"].append((wall_now, r["label"], r["verdict"]))
    return _sim_pipeline.SimPass(
        rows=rows,
        raw_count=len(raw),
        invokes=invokes,
        inference_ms=inference_ms,
        sahi_diag=sahi_diag,
        tick_fps=tick_fps,
        frame_w=w_px,
        frame_h=h_px,
    )


def _respond(
    *,
    rt,
    cam,
    cam_id,
    setup,
    sim,
    pick,
    entry,
    det_mode,
    mode_override,
    stream_pref,
    stream_override,
):
    """Trace, snapshot, diag, log line, JSON body."""
    eff_cfg = app_state.get_effective_config()
    trace = _build_trace(
        cam=cam,
        cam_id=cam_id,
        setup=setup,
        sim=sim,
        pick=pick,
        entry=entry,
        eff_cfg=eff_cfg,
        mode_override=mode_override,
        stream_override=stream_override,
    )
    skip_snapshot = (request.args.get("no_snapshot") or "").strip() in ("1", "true", "yes")
    snapshot, snap_w, snap_h, snap_scale = _sim_frame.encode_snapshot(
        apply_bottom_crop(pick.frame, setup.bottom_crop_px), sim.rows, skip_snapshot
    )
    ema_ms = float(getattr(rt, "_frame_interval_ema_ms", 0.0) or 0.0)
    diag = _build_diag(
        setup=setup,
        sim=sim,
        pick=pick,
        rt=rt,
        det_mode=det_mode,
        mode_override=mode_override,
        stream_pref=stream_pref,
        stream_override=stream_override,
        snap=(snap_w, snap_h, snap_scale),
    )
    _log_tick(cam_id=cam_id, sim=sim, pick=pick, setup=setup)
    evidence = _sim_evidence.build_cluster_evidence(entry, cam, setup.object_filter, ema_ms)
    interval_ms = int(cam.get("frame_interval_ms", 350) or 350)
    entry["last_tick"] = {
        "ts": _time.time(),
        "detections": sim.rows,
        "trace": trace,
        "frame_size": {"w": int(snap_w), "h": int(snap_h)},
        "frame_age_ms": pick.age_ms,
        "diag": diag,
        "cluster_evidence": evidence,
    }
    return jsonify(
        {
            "ok": True,
            "snapshot": snapshot,
            "frame_size": {"w": int(snap_w), "h": int(snap_h)},
            "frame_age_ms": pick.age_ms,
            "detections": sim.rows,
            "decision_trace": trace,
            "diag": diag,
            "frame_interval_avg_ms": int(round(ema_ms)) if ema_ms > 0 else 0,
            # A decoder draining a buffered burst reports an EMA well
            # below the camera's configured interval; 0.4× keeps a
            # slightly-fast normal stream from false-positiving.
            "decoder_backlog_suspected": bool(
                ema_ms > 0 and interval_ms > 0 and ema_ms < 0.4 * interval_ms
            ),
            "cluster_evidence": evidence,
        }
    )


def _build_trace(
    *, cam, cam_id, setup, sim, pick, entry, eff_cfg, mode_override, stream_override
) -> list:
    """The full decision trace, capture → final push verdict.

    Assembled in pipeline order so the operator reads it the way the
    frame travelled. The stated-gate block sits between the gates that
    RAN and the routing gates precisely because that is where production
    runs the motion window and the confirmation window — the two the
    panel refuses to fake.
    """
    trace = _sim_trace.capture_lines(
        cam=cam,
        setup=setup,
        sim=sim,
        frame_age_ms=pick.age_ms,
        stream_used=pick.src,
        stream_override=stream_override,
    )
    trace += _sim_trace.config_lines(setup=setup, sim=sim, mode_override=mode_override)
    trace += _sim_trace.gate_lines(
        cam=cam, setup=setup, sim=sim, active_tracks=entry["tracker"].active_count()
    )
    trace += _sim_trace.detection_lines(sim)
    trace += _sim_trace.stated_gate_lines(cam=cam, setup=setup, eff_cfg=eff_cfg)
    routing, _push_blocked = _sim_routing.routing_lines(
        cam=cam,
        cam_id=cam_id,
        sim=sim,
        eff_cfg=eff_cfg,
        notifier=getattr(app_state, "telegram_service", None),
    )
    return trace + routing


def _build_diag(
    *, setup, sim, pick, rt, det_mode, mode_override, stream_pref, stream_override, snap
):
    """Structured payload for the in-modal Diagnose panel.

    ``parity`` is new and is the point of this change: the panel now
    declares, in machine-readable form, which of its controls are NOT
    the camera's configuration, so the UI can mark them rather than
    letting the operator read an experiment as production.
    """
    snap_w, snap_h, snap_scale = snap
    lag_s = _sim_frame.capture_lag_s(rt)
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
        "coral_available": True,
        "inference_ms": int(sim.inference_ms),
        # What this tick ACTUALLY cost. The full-frame pass is now reused
        # by the tiling stage exactly as production's rescue reuses it,
        # so this is the number production would pay too.
        "mode_invokes": int(sim.invokes),
        "gates": {
            "raw": int(sim.raw_count),
            "pass": len(sim.pass_rows),
            "tentative": sim.count(_sim_pipeline.VERDICT_TENTATIVE),
            # Back-compat key for the existing frontend counters.
            "belowthresh": sim.count(_sim_pipeline.VERDICT_TENTATIVE),
            "no_track": sim.count(_sim_pipeline.VERDICT_NO_TRACK),
            "filtered": sim.count(_sim_pipeline.VERDICT_FILTERED),
            "masked": sim.count(_sim_pipeline.VERDICT_MASKED),
            "outside_zone": sim.count(_sim_pipeline.VERDICT_OUTSIDE_ZONE),
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


def _log_tick(*, cam_id, sim, pick, setup) -> None:
    """One greppable line per tick. WARNING when nothing was detected or
    the frame outcome was not clean, so a regression surfaces without
    --tail digging."""
    top_raw = (
        "["
        + ", ".join(f"({r['label']},{int(round(r['score'] * 100))}%)" for r in sim.rows[:3])
        + "]"
    )
    log_fn = log.info if (pick.outcome == "ok" and sim.raw_count > 0) else log.warning
    log_fn(
        "[test-detection] cam=%s outcome=%s waited=%.2fs retries=%d "
        "frame_age_ms=%d frame_src=%s raw=%d pass=%d tentative=%d no_track=%d "
        "filtered=%d masked=%d outside_zone=%d inference_ms=%d "
        "invokes=%d tick_fps=%.2f top_raw=%s obj_filter=%s floor=%.2f",
        cam_id,
        pick.outcome,
        pick.waited_s,
        pick.retries,
        pick.age_ms,
        pick.src,
        sim.raw_count,
        len(sim.pass_rows),
        sim.count(_sim_pipeline.VERDICT_TENTATIVE),
        sim.count(_sim_pipeline.VERDICT_NO_TRACK),
        sim.count(_sim_pipeline.VERDICT_FILTERED),
        sim.count(_sim_pipeline.VERDICT_MASKED),
        sim.count(_sim_pipeline.VERDICT_OUTSIDE_ZONE),
        sim.inference_ms,
        sim.invokes,
        sim.tick_fps,
        top_raw,
        "[" + ",".join(sorted(setup.object_filter)) + "]",
        setup.floor,
    )


def _frame_failure_response(cam_id: str, pick):
    """503 body when no frame cleared the freshness contract."""
    code, msg = pick.failure()
    age_ms = (
        int((_time.time() - pick.last_candidate_ts) * 1000) if pick.last_candidate_ts > 0 else 0
    )
    log.warning(
        "[test-detection] cam=%s outcome=%s waited=%.2fs retries=%d "
        "frame_age_ms=%d frame_src=- raw=0 validator_reason=%r profile=%s",
        cam_id,
        code,
        pick.waited_s,
        pick.retries,
        age_ms,
        pick.validator_reason or "-",
        (pick.profile.name if pick.profile else "-"),
    )
    return jsonify(
        {
            "ok": False,
            "error": msg,
            "code": code,
            "frame_age_ms": age_ms,
            "validator_reason": pick.validator_reason or None,
            "validator_profile": (pick.profile.name if pick.profile else None),
        }
    ), 503


# SIMU-07 · debug-snapshot endpoint. Returns a self-contained document of
# the camera's current live state — everything a debugging session needs
# in one paste-able blob, so the operator never has to open a root shell
# on the phone. Reads the per-cam test-tracker state (no fresh inference)
# so it is cheap and reflects the LAST tick the user saw.
@bp.get('/api/cameras/<cam_id>/debug-snapshot')
def api_debug_snapshot(cam_id: str):
    from flask import Response

    from ._debug_snapshot import build_snapshot

    cam = app_state.settings.get_camera(cam_id)
    want_json = (request.args.get("format") or "").lower() == "json"
    if not cam:
        if want_json:
            return jsonify({"ok": False, "error": "camera not found"}), 404
        return Response("# Camera not found\n", mimetype="text/markdown", status=404)
    snap = build_snapshot(
        cam=cam,
        cam_id=cam_id,
        tt=_sim_pipeline.trackers().get(cam_id) or {},
        runtime=app_state.runtimes.get(cam_id),
        eff_cfg=app_state.get_effective_config(),
    )
    if want_json:
        return jsonify({"ok": True, "markdown": snap["markdown"], "findings": snap["findings"]})
    return Response(snap["markdown"], mimetype="text/markdown; charset=utf-8")
