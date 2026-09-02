"""Per-stage helpers behind ``/api/coral/test``.

Split out of the 242-line route body so each classifier stage is one
readable unit. Pure move: the gates, the mutation of the detection
objects (the bird stage writes ``species`` / ``species_latin`` /
``species_score`` back onto them, which the annotated preview and the
``detections`` field of the response then see) and the exact result-row
shapes are unchanged.

The two crop-driven stages used to carry a byte-identical
"pad the bbox, clamp to the frame, skip an empty crop" block; it lives
once in ``padded_crop`` now.
"""

from __future__ import annotations

import base64 as _b64
import os as _os
import subprocess as _sp
import time as _time

import cv2

from ... import app_state

_CROP_PAD = 6


def source_frame(cam_id: str | None) -> tuple:
    """Return ``(frame, source, camera_name)`` for the test run.

    Prefers the camera's clean H.264 sub-stream frame; falls back to a
    synthetic test pattern when no runtime can supply one.
    """
    settings = app_state.settings
    runtimes = app_state.runtimes
    frame = None
    source = "test_pattern"
    camera_name = None
    if cam_id:
        rt = runtimes.get(cam_id)
        if rt is not None:
            with rt.lock:
                # Prefer the clean H.264 sub-stream frame. The main-stream
                # rt.frame is OpenCV's software H.265 decode output, which is
                # riddled with pink/magenta artifacts and unusable for a
                # visual sanity check of Coral detection results.
                if getattr(rt, '_preview_frame', None) is not None:
                    frame = rt._preview_frame.copy()
                elif rt.preview is not None:
                    frame = rt.preview.copy()
                elif rt.frame is not None:
                    frame = rt.frame.copy()
            if frame is not None:
                source = "camera"
                cam_cfg = settings.get_camera(cam_id) or {}
                camera_name = cam_cfg.get("name", cam_id)
    if frame is None:
        import numpy as _np

        frame = _np.zeros((300, 300, 3), dtype=_np.uint8)
        frame[50:150, 50:150] = (255, 120, 0)
        frame[150:250, 100:200] = (80, 200, 0)
        frame[80:120, 200:280] = (50, 100, 180)
    return frame, source, camera_name


def padded_crop(frame, bbox):
    """Bbox crop with a fixed pad, clamped to the frame. ``None`` when empty."""
    h_full, w_full = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    cx1 = max(0, x1 - _CROP_PAD)
    cy1 = max(0, y1 - _CROP_PAD)
    cx2 = min(w_full, x2 + _CROP_PAD)
    cy2 = min(h_full, y2 + _CROP_PAD)
    crop = frame[cy1:cy2, cx1:cx2]
    if crop is None or crop.size == 0:
        return None
    return crop


def run_detection_stage(det_cfg: dict, frame) -> tuple:
    """Stage 1 · COCO detection. Returns ``(detector, detections, ms, err, row)``."""
    from ...detectors import CoralObjectDetector

    detector = CoralObjectDetector(det_cfg)
    detections: list = []
    infer_ms = 0.0
    err_msg = None
    if detector.available:
        try:
            t0 = _time.perf_counter()
            detections = detector.detect_frame(frame)
            infer_ms = round((_time.perf_counter() - t0) * 1000, 1)
        except Exception as e:
            err_msg = str(e)
    row = {
        "category": "detection",
        "model": _os.path.basename(det_cfg.get("model_path") or "") or None,
        "mode": detector.mode,
        "available": bool(detector.available),
        "reason": detector.reason,
        "inference_ms": infer_ms,
        "error": err_msg,
        "results": [d.to_dict() for d in detections],
    }
    return detector, detections, infer_ms, err_msg, row


def run_bird_stage(bird_cfg: dict, frame, detections: list) -> tuple:
    """Stage 2 · bird species. Returns ``(classifier, row)``.

    Test-mode override: ignores ``.enabled`` so the user can see what the
    model would say even when the runtime has it switched off. Writes the
    species back onto each matching detection object.
    """
    from ...detectors import BirdSpeciesClassifier

    bird_test_cfg = dict(bird_cfg)
    bird_test_cfg["enabled"] = True
    bird_clf = BirdSpeciesClassifier(bird_test_cfg)
    bird_results: list[dict] = []
    bird_ms = 0.0
    if bird_clf.available and detections:
        t0 = _time.perf_counter()
        for d in detections:
            if d.label != "bird":
                continue
            crop = padded_crop(frame, d.bbox)
            if crop is None:
                continue
            try:
                sp, sp_latin, sp_score = bird_clf.classify_crop(crop)
            except Exception:
                sp, sp_latin, sp_score = None, None, None
            if sp:
                d.species = sp
                d.species_latin = sp_latin
                d.species_score = float(sp_score) if sp_score is not None else None
                bird_results.append(
                    {
                        "species": sp,
                        "latin": sp_latin,
                        "score": round(float(sp_score), 4) if sp_score is not None else None,
                        "from_label": "bird",
                    }
                )
        bird_ms = round((_time.perf_counter() - t0) * 1000, 1)
    row = {
        "category": "bird_species",
        "model": _os.path.basename(bird_cfg.get("model_path") or "") or None,
        "mode": bird_clf.mode,
        "available": bool(bird_clf.available),
        "reason": bird_clf.reason,
        "inference_ms": bird_ms,
        "error": None,
        "results": bird_results,
    }
    return bird_clf, row


def run_wildlife_stage(wild_cfg: dict, frame, detections: list) -> tuple:
    """Stage 3 · wildlife (mammals not covered by COCO). Returns ``(clf, row)``.

    Same test-mode override as the bird stage, so a CPU-only setup can
    validate that the wildlife pipeline would work. Runs on every
    detection that is NOT a bird and NOT a person — those are covered
    upstream.
    """
    from ...detectors import WildlifeClassifier

    wild_test_cfg = dict(wild_cfg)
    wild_test_cfg["enabled"] = True
    wild_clf = WildlifeClassifier(wild_test_cfg)
    wild_results: list[dict] = []
    wild_ms = 0.0
    if wild_clf.available and detections:
        t0 = _time.perf_counter()
        for d in detections:
            if d.label in ("bird", "person"):
                continue
            crop = padded_crop(frame, d.bbox)
            if crop is None:
                continue
            try:
                category, imagenet_label, score = wild_clf.classify_crop(crop)
            except Exception:
                category, imagenet_label, score = None, None, None
            wild_results.append(
                {
                    "from_label": d.label,
                    "imagenet": imagenet_label,
                    "mapped": category,  # "squirrel" / "fox" / "hedgehog" / null
                    "score": round(float(score), 4) if score is not None else None,
                }
            )
        wild_ms = round((_time.perf_counter() - t0) * 1000, 1)
    row = {
        "category": "wildlife",
        "model": _os.path.basename(wild_cfg.get("model_path") or "") or None,
        "mode": wild_clf.mode,
        "available": bool(wild_clf.available),
        "reason": wild_clf.reason,
        "inference_ms": wild_ms,
        "error": None,
        "results": wild_results,
    }
    return wild_clf, row


def annotated_b64(frame, detections: list) -> str | None:
    """Draw the stage-1 boxes, downscale to 640 px wide, return a data URI."""
    from ...detectors import draw_detections

    annotated = draw_detections(frame, detections)
    h, w = annotated.shape[:2]
    if w > 640:
        scale = 640 / w
        annotated = cv2.resize(annotated, (640, int(h * scale)))
    ok, buf = cv2.imencode('.jpg', annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        return None
    return "data:image/jpeg;base64," + _b64.b64encode(buf.tobytes()).decode('ascii')


def usb_info() -> str | None:
    """The ``lsusb`` line for the Coral stick, when one is plugged in."""
    try:
        lsusb = _sp.check_output(['lsusb'], text=True, timeout=3, stderr=_sp.DEVNULL)
    except Exception:
        return None
    for line in lsusb.splitlines():
        low = line.lower()
        if 'google' in low or 'coral' in low or '18d1' in low or '1a6e' in low:
            return line.strip()
    return None
