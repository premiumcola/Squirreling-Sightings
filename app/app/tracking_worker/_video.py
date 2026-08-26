"""Clip probing + the per-clip sampling loop.

The only two places in the package that touch OpenCV. ``open_video``
reads the container's cadence; ``sample_clip`` walks the clip at that
cadence and feeds each sampled frame through the detector into the
tracker. Neither knows anything about jobs, queues or sidecars.
"""

from __future__ import annotations

from pathlib import Path

from ..tracker_core import TrackerState, associate_detections
from ._detect import detect_and_filter


def open_video(video_path: Path, *, precision: str = "standard"):
    """Open the file and read its sampling cadence. Returns
    ``(capture, meta)``; capture is None on failure (and is released
    before returning so the caller doesn't have to). meta carries
    ``fps``, ``frame_count``, ``duration_s``, ``sample_interval``,
    ``frame_w``, ``frame_h``. The frame dimensions feed the per-track
    end-state diagnostics (last_bbox_frac_h / last_bbox_frac_area).

    ``precision`` controls the sampling cadence:
      * ``"standard"`` (default) — ~1 Hz, the historic post-clip
        behaviour. One inference per second of clip.
      * ``"precise"`` — ~2 Hz. Doubles the per-clip inference cost
        but halves the gap between samples so tracks reflect motion
        more faithfully. Same algorithm; just sees more samples."""
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if frame_count <= 0 or fps <= 0:
        cap.release()
        return None, {
            "fps": fps,
            "frame_count": frame_count,
            "duration_s": 0.0,
            "sample_interval": 0,
            "frame_w": frame_w,
            "frame_h": frame_h,
        }
    duration_s = frame_count / fps
    if precision == "precise":
        sample_interval = max(1, int(round(fps / 2)))  # ~2 Hz
    else:
        sample_interval = max(1, int(round(fps)))  # ~1 Hz
    return cap, {
        "fps": fps,
        "frame_count": frame_count,
        "duration_s": duration_s,
        "sample_interval": sample_interval,
        "frame_w": frame_w,
        "frame_h": frame_h,
    }


def precision_for(cam_cfg_getter, camera_id: str) -> str:
    """Per-camera sampling cadence. ``"standard"`` = 1 Hz (historic
    default); ``"precise"`` = 2 Hz for richer track samples at double
    the inference cost. The knob lives in settings.json only (no UI in
    this version), so anything unreadable falls back to standard."""
    try:
        cfg = cam_cfg_getter(camera_id) if cam_cfg_getter else {}
        if isinstance(cfg, dict):
            raw = str(cfg.get("track_postclip_precision") or "").strip().lower()
            if raw == "precise":
                return "precise"
    except Exception:
        return "standard"
    return "standard"


def sample_clip(cap, meta: dict, detector, allowed, *, floor_score, spawn_score, iou_threshold):
    """Walk the clip at ``meta["sample_interval"]`` and return the
    populated :class:`TrackerState`.

    Unreadable frames are skipped without advancing the tracker — a
    dropped sample must not look like a miss to the grace window.
    Tracks still active at end-of-clip are closed and moved into
    ``state.closed`` so the whole post-pass (stitch → static-FP →
    ghost prune → serialise) sees one list.
    """
    import cv2

    state = TrackerState()
    sample_interval = meta["sample_interval"]
    frame_count = meta["frame_count"]
    fps = meta["fps"]
    frame_w = meta.get("frame_w", 0)
    frame_h = meta.get("frame_h", 0)

    frame_idx = 0
    while frame_idx < frame_count:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            frame_idx += sample_interval
            continue
        t_s = frame_idx / fps
        dets = detect_and_filter(detector, frame, allowed, floor_score=floor_score)
        associate_detections(
            state,
            dets,
            frame_idx,
            t_s,
            frame_w=frame_w,
            frame_h=frame_h,
            spawn_score=spawn_score,
            iou_threshold=iou_threshold,
        )
        frame_idx += sample_interval

    # Flush any tracks still active at end-of-clip into closed so the
    # payload's serialisation comprehension picks them up. close()
    # populates the per-track end_reason + last_* fields so the
    # lightbox × tooltip has something to render.
    for tr in state.active:
        tr.close("ended_at_clip", frame_w, frame_h)
    state.closed.extend(state.active)
    state.active = []
    return state
