"""Clip probing + the per-clip sampling loop.

The only two places in the package that touch OpenCV. ``open_video``
reads the container's cadence; ``sample_clip`` walks the clip at that
cadence and feeds each sampled frame through the detector into the
tracker. Neither knows anything about jobs, queues or sidecars.
"""

from __future__ import annotations

from pathlib import Path

from ..tracker_core import SPAWN_BLOCK_CONTAIN, TrackerState, associate_detections
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


def _read_at(cap, frame_idx: int):
    """Seek to ``frame_idx`` and read that frame. ``(ok, frame)``.

    Also the only place in the sampling loop that needs cv2, which is
    why the import sits here rather than at the top of the walk.
    """
    import cv2

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    return cap.read()


def _close_open_tracks(state, frame_w: int, frame_h: int) -> None:
    """End-of-clip flush: move tracks still active into ``closed``.

    The whole post-pass — stitch → static-FP → ghost prune → serialise
    — reads one list, so a track that was still alive when the footage
    ran out has to be moved rather than dropped. ``close()`` also
    populates the per-track end_reason + last_* fields the lightbox's
    × tooltip renders.
    """
    for tr in state.active:
        tr.close("ended_at_clip", frame_w, frame_h)
    state.closed.extend(state.active)
    state.active = []


def sample_clip(
    cap,
    meta: dict,
    detector,
    allowed,
    *,
    floor_score,
    spawn_score,
    iou_threshold,
    block_contain=SPAWN_BLOCK_CONTAIN,
    max_samples: int | None = None,
    sample_hook=None,
):
    """Walk the clip at ``meta["sample_interval"]`` and return the
    populated :class:`TrackerState`.

    Unreadable frames are skipped without advancing the tracker — a
    dropped sample must not look like a miss to the grace window.
    Tracks still active at end-of-clip are closed and moved into
    ``state.closed`` so the whole post-pass (stitch → static-FP →
    ghost prune → serialise) sees one list.

    ``max_samples`` stops the walk after that many DECODE ATTEMPTS
    (not successful reads — a clip whose tail is unreadable must not
    be able to spin past the cap). None, the default the queued
    sidecar jobs use, means walk the whole clip: they run on a
    background thread where a long clip only costs time. The replay
    endpoint runs synchronously on a request thread and passes a cap,
    then reports how many of the available samples it got through.

    ``sample_hook(frame, dets)``, when given, is called once per
    successfully decoded sample with the frame's pixels and the
    detections just filtered out of it, BEFORE they are associated into
    tracks. It exists for the second stage a bare detector pass cannot
    do: the replay hands in a hook that classifies bird crops
    (replay/_species.py), which needs the pixels while they are still
    in hand. The hook may mutate the detections — that is how a species
    lands on one — but must not add or remove entries, since the list
    it is handed is the one association is about to consume. None, the
    default, leaves the queued sidecar jobs walking exactly as before.
    """
    state = TrackerState()
    sample_interval = meta["sample_interval"]
    frame_count = meta["frame_count"]
    fps = meta["fps"]
    frame_w = meta.get("frame_w", 0)
    frame_h = meta.get("frame_h", 0)

    frame_idx = 0
    attempts = 0
    while frame_idx < frame_count:
        if max_samples is not None and attempts >= max_samples:
            break
        attempts += 1
        ok, frame = _read_at(cap, frame_idx)
        if not ok or frame is None:
            frame_idx += sample_interval
            continue
        t_s = frame_idx / fps
        dets = detect_and_filter(detector, frame, allowed, floor_score=floor_score)
        if sample_hook is not None:
            sample_hook(frame, dets)
        associate_detections(
            state,
            dets,
            frame_idx,
            t_s,
            frame_w=frame_w,
            frame_h=frame_h,
            spawn_score=spawn_score,
            iou_threshold=iou_threshold,
            block_contain=block_contain,
        )
        frame_idx += sample_interval

    _close_open_tracks(state, frame_w, frame_h)
    return state
