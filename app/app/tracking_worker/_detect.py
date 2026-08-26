"""Detector plumbing: which classes are allowed, and one sample's pass.

The detector INSTANCE is owned by the worker (built lazily, pinned to
CPU); everything about how it is called for a post-clip sample lives
here.
"""

from __future__ import annotations


def resolve_object_filter(cam_cfg_getter, camera_id):
    """Pull the camera's object_filter and translate to the worker's
    allowed-set semantics. Mirrors camera_runtime/_main_loop:
    ``None`` == no filter (all classes pass), set == filter active.
    Filtered classes can't spawn or extend tracks because the filter is
    applied BEFORE association."""
    try:
        cam_cfg = cam_cfg_getter(camera_id) or {}
    except Exception:
        cam_cfg = {}
    of_raw = cam_cfg.get("object_filter")
    if isinstance(of_raw, list) and of_raw:
        return {str(x) for x in of_raw}
    return None


def detect_and_filter(detector, frame, allowed, *, floor_score: float):
    """One sample's detector pass at the worker's low confidence floor.
    Uses ``detect_frame_raw`` so we receive every candidate ≥
    ``floor_score`` BEFORE the live pipeline's per-label thresholds /
    size floors trim the list — those gates would otherwise prevent
    the tentative-continuation tier in v3 from seeing anything below
    the spawn threshold. The allowed-label filter (the camera's
    object_filter) IS still applied here so tentative detections of
    forbidden classes don't leak through to track association.
    Empty list when the detector is unavailable (worker stays alive
    but writes a tracks.json with no tracks)."""
    if not detector.available:
        return []
    dets = detector.detect_frame_raw(frame, threshold=float(floor_score))
    if allowed is not None:
        dets = [d for d in dets if d.label in allowed]
    return dets
