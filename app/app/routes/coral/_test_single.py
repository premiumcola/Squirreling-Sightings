"""``/api/coral/test`` — run every classifier stage against one frame."""

from __future__ import annotations

from flask import jsonify, request

from ... import app_state
from ._blueprint import bp
from ._stages import (
    annotated_b64,
    run_bird_stage,
    run_detection_stage,
    run_wildlife_stage,
    source_frame,
    usb_info,
)


@bp.post('/api/coral/test')
def api_coral_test():
    """Run every classifier stage against a single frame and return a
    per-model breakdown. The user wants to see "what each model would
    say" in the Settings → Modelle test panel — including stages that
    are currently disabled in the runtime, so the test bypasses the
    .enabled flag for the second-stage classifiers.

    Response shape:
      {
        ok, source, camera_id, camera_name, image_b64, usb_info,
        models_run: [
          {category, model, mode, available, reason, inference_ms, results: [...]},
          ...
        ],
        # Legacy flat fields kept for the older test-panel UI:
        detector_mode, detector_available, detector_reason, inference_ms,
        detections, bird_species_mode, bird_species_reason,
      }
    """
    payload = request.get_json(silent=True) or {}
    cam_id = (payload.get("camera_id") or "").strip() or None

    eff = app_state.get_effective_config()
    det_cfg = (eff.get("processing", {}) or {}).get("detection", {}) or {}
    bird_cfg = (eff.get("processing", {}) or {}).get("bird_species", {}) or {}
    wild_cfg = (eff.get("processing", {}) or {}).get("wildlife", {}) or {}

    frame, source, camera_name = source_frame(cam_id)

    models_run: list[dict] = []
    detector, detections, infer_ms, err_msg, det_row = run_detection_stage(det_cfg, frame)
    models_run.append(det_row)
    bird_clf, bird_row = run_bird_stage(bird_cfg, frame, detections)
    models_run.append(bird_row)
    _wild_clf, wild_row = run_wildlife_stage(wild_cfg, frame, detections)
    models_run.append(wild_row)

    return jsonify(
        {
            "ok": True,
            # Legacy flat fields — older test-panel renderers still read these.
            "detector_mode": detector.mode,
            "detector_available": detector.available,
            "detector_reason": detector.reason,
            "model_path": det_cfg.get("model_path"),
            "bird_species_mode": bird_clf.mode,
            "bird_species_reason": bird_clf.reason,
            "source": source,
            "camera_id": cam_id,
            "camera_name": camera_name,
            "inference_ms": infer_ms,
            "inference_error": err_msg,
            "detections": [d.to_dict() for d in detections],
            "image_b64": annotated_b64(frame, detections),
            "usb_info": usb_info(),
            # New per-model breakdown.
            "models_run": models_run,
        }
    )
