"""``/api/coral/test-images`` and ``/api/coral/test-batch``.

Batch-runs the detector over the folders under ``storage/test_images/``
so detection quality can be sanity-checked without a live camera feed.
"""

from __future__ import annotations

from pathlib import Path

import cv2
from flask import jsonify, request

from ... import app_state
from .._coral_helpers import _TEST_FOLDER_LABELS, _TEST_VALID_EXT
from .._coral_pipeline import (
    ALLOWED_MODES,
    COCO_MODES,
    WILDLIFE_FOLDERS,
    build_classifiers_for_mode,
    build_models_active,
    resolve_candidate_dirs,
    run_mode_all_independent,
    run_mode_bird_only,
    run_mode_cascade,
    run_mode_coco_only,
    run_mode_wildlife_only,
    serialise_image_b64,
    serialise_result_row,
)
from ._blueprint import bp


@bp.get('/api/coral/test-images')
def api_coral_test_images():
    """List subfolders under storage/test_images/ with image counts so the
    Coral test-panel dropdown can populate a 'Testbilder' optgroup."""
    eff = app_state.get_effective_config()
    storage_root = Path(eff.get("storage", {}).get("root", "storage"))
    base = storage_root / "test_images"
    if not base.exists():
        return jsonify({"folders": [], "expected_at": str(base)})
    folders = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        count = sum(1 for p in d.iterdir() if p.is_file() and p.suffix.lower() in _TEST_VALID_EXT)
        if count == 0:
            continue
        meta = _TEST_FOLDER_LABELS.get(d.name, {})
        folders.append(
            {
                "name": d.name,
                "count": count,
                "label": meta.get("label", d.name.capitalize()),
                "icon": meta.get("icon", "📁"),
            }
        )
    return jsonify({"folders": folders})


def _dispatch_mode(mode, frame, detector, bird_clf, wl_clf, folder_name, counters):
    """Route one frame to the pipeline helper for ``mode``.

    Returns the helpers' ``(tagged, wildlife_info, stages_run, ms)``.
    """
    if mode == "cascade":
        return run_mode_cascade(frame, detector, bird_clf, wl_clf, folder_name, counters)
    if mode == "coco_only":
        return run_mode_coco_only(frame, detector)
    if mode == "bird_species_only":
        return run_mode_bird_only(frame, bird_clf, counters)
    if mode == "wildlife_only":
        return run_mode_wildlife_only(frame, wl_clf, counters)
    return run_mode_all_independent(frame, detector, bird_clf, wl_clf, counters)


def _scan_folders(candidate_dirs, mode, detector, bird_clf, wl_clf):
    """Run every image under ``candidate_dirs``. Returns (results, tally)."""
    results: list = []
    counters: dict = {"by_label": {}, "species": {}, "wildlife": {}}
    total_images = 0
    with_detections = 0
    with_wildlife = 0
    inference_times: list = []

    for d in candidate_dirs:
        if not d.is_dir():
            continue
        for img_path in sorted(d.iterdir()):
            if img_path.suffix.lower() not in _TEST_VALID_EXT:
                continue
            frame = cv2.imread(str(img_path))
            if frame is None:
                results.append(
                    {
                        "folder": d.name,
                        "filename": img_path.name,
                        "error": "could not read image",
                    }
                )
                continue
            try:
                tagged, wildlife_info, stages_run, ms = _dispatch_mode(
                    mode, frame, detector, bird_clf, wl_clf, d.name, counters
                )
            except Exception as e:
                # Match the legacy error-row shape: stages_run is empty
                # because the failure is the COCO detect_frame call inside
                # the helper, which happens before any stage append.
                results.append(
                    {
                        "folder": d.name,
                        "filename": img_path.name,
                        "error": str(e),
                        "stages_run": [],
                    }
                )
                continue

            image_b64, orig_w, orig_h = serialise_image_b64(frame)
            results.append(
                serialise_result_row(
                    d.name,
                    img_path.name,
                    ms,
                    image_b64,
                    orig_w,
                    orig_h,
                    stages_run,
                    tagged,
                    wildlife_info,
                )
            )
            total_images += 1
            inference_times.append(ms)
            if tagged:
                with_detections += 1
                for dd, _src in tagged:
                    counters["by_label"][dd.label] = counters["by_label"].get(dd.label, 0) + 1
            # For wildlife folders, "hit" means either COCO found something
            # or wildlife classifier found fox/squirrel/hedgehog
            if wildlife_info and wildlife_info.get("label"):
                with_wildlife += 1

    summary = {
        "total_images": total_images,
        "with_detections": with_detections,
        "with_wildlife": with_wildlife,
        "by_label": counters["by_label"],
        "by_species": counters["species"],
        "by_wildlife": counters["wildlife"],
        "avg_ms": round(sum(inference_times) / len(inference_times), 1) if inference_times else 0.0,
    }
    return results, summary


@bp.post('/api/coral/test-batch')
def api_coral_test_batch():
    """Run detect_frame on every image under storage/test_images/<folder>/.

    Body: {"folder": "bird"} runs only that folder. Empty body runs all.
    Returns a per-image breakdown (incl. annotated image_b64 with bounding
    boxes drawn on it) plus a summary of label counts so the user can
    sanity-check object-detection quality without live camera feeds."""
    payload = request.get_json(silent=True) or {}
    folder_filter = (payload.get("folder") or "").strip()
    mode = (payload.get("mode") or "cascade").strip()
    if mode not in ALLOWED_MODES:
        return jsonify(
            {
                "ok": False,
                "error": f"unknown mode: {mode!r}",
                "allowed": list(ALLOWED_MODES),
            }
        ), 400

    eff = app_state.get_effective_config()
    det_cfg = (eff.get("processing", {}) or {}).get("detection", {}) or {}
    bird_cfg = (eff.get("processing", {}) or {}).get("bird_species", {}) or {}
    wl_cfg = (eff.get("processing", {}) or {}).get("wildlife", {}) or {}
    storage_root = Path(eff.get("storage", {}).get("root", "storage"))

    candidate_dirs, err = resolve_candidate_dirs(storage_root, folder_filter)
    if err is not None:
        return jsonify(err), 404

    target_folders = {d.name for d in candidate_dirs if d.is_dir()}
    needs_wildlife = bool(target_folders & WILDLIFE_FOLDERS)
    wildlife_settings_enabled = bool(wl_cfg.get("enabled"))

    detector, bird_clf, wl_clf, wildlife_disabled_warning = build_classifiers_for_mode(
        mode,
        det_cfg,
        bird_cfg,
        wl_cfg,
        needs_wildlife,
    )
    # COCO-less modes (bird_species_only, wildlife_only) tolerate the
    # detector being absent — they don't call detect_frame at all. Only
    # the modes that genuinely need COCO short-circuit on unavailability.
    if mode in COCO_MODES and not detector.available:
        return jsonify(
            {
                "ok": False,
                "error": "detector unavailable",
                "detector_mode": detector.mode,
                "detector_reason": detector.reason,
                "results": [],
            }
        )

    results, summary = _scan_folders(candidate_dirs, mode, detector, bird_clf, wl_clf)

    response = {
        "ok": True,
        "mode": mode,
        "models_active": build_models_active(
            detector,
            bird_clf,
            wl_clf,
            det_cfg,
            bird_cfg,
            wl_cfg,
        ),
        "detector_mode": detector.mode,
        "detector_reason": detector.reason,
        "bird_species_mode": bird_clf.mode if bird_clf else "none",
        "bird_species_reason": bird_clf.reason if bird_clf else "disabled",
        "wildlife_mode": wl_clf.mode if wl_clf else "none",
        "wildlife_reason": wl_clf.reason if wl_clf else "disabled",
        "wildlife_settings_enabled": wildlife_settings_enabled,
        "model_path": det_cfg.get("model_path"),
        "summary": summary,
        "results": results,
    }
    if wildlife_disabled_warning:
        response["wildlife_disabled_warning"] = wildlife_disabled_warning
    return jsonify(response)
