"""Run one stored clip back through the post-clip detection pipeline.

Not a second pipeline. Every step below is the same function the queued
sidecar job calls in ``tracking_worker._run_one``; the only difference is
the ``cam_cfg_getter`` handed to them. Each of ``precision_for``,
``resolve_object_filter`` and ``resolve_track_thresholds`` already takes
that getter as an argument, so replaying "with different settings" is
handing them a getter that returns the settings under test instead of
the camera's live ones. Nothing in the worker needed a branch.

Two properties keep this safe to call from a request thread:

  * It borrows ``worker.detector()`` — the CPU-pinned instance — so a
    replay never competes for the single Edge TPU the live camera
    runtimes own. This is the same protection the queued jobs have, and
    it comes from the detector, not from which thread runs it.
  * It is bounded. ``max_samples`` caps the decode attempts, and the
    result reports how many of the clip's available samples were
    actually walked so the caller can say "180 von 420 Frames".
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ..tracker_core import resolve_track_thresholds
from ..tracking_worker._clean import clean_tracks
from ..tracking_worker._detect import resolve_object_filter
from ..tracking_worker._payload import build_payload
from ..tracking_worker._video import open_video, precision_for, sample_clip
from ._consts import REPLAY_MAX_SAMPLES
from ._diff import track_to_detection

log = logging.getLogger(__name__)

# Track fields worth keeping in the event JSON. The full track carries
# its whole sample series, which is what makes a tracks.json sidecar
# large — five of those under an event would bloat a document the
# Mediathek reads on every card render.
_COMPACT_TRACK_KEYS = (
    "track_id",
    "label",
    "best_score",
    "first_frame",
    "last_frame",
    "end_reason",
)


def available_samples(meta: dict) -> int:
    """How many samples a full walk of this clip would take, at the
    cadence ``open_video`` chose. The denominator in "n of m frames"."""
    interval = int(meta.get("sample_interval") or 0)
    frames = int(meta.get("frame_count") or 0)
    if interval <= 0 or frames <= 0:
        return 0
    return -(-frames // interval)  # ceil division


def compact_track(track: dict) -> dict:
    """One track without its sample series."""
    return {k: track[k] for k in _COMPACT_TRACK_KEYS if k in track}


def describe_detector(detector) -> dict:
    """What the replay actually ran on, so a report can admit that the
    model differs from the one recorded in the event's provenance. A
    replay can vary the tuning; it cannot retro-install the model the
    clip was captured with."""
    model = getattr(detector, "active_model_path", None)
    return {
        "available": bool(getattr(detector, "available", False)),
        "mode": getattr(detector, "mode", None),
        "model": Path(model).name if model else None,
        "reason": getattr(detector, "reason", None),
    }


def _walk_clip(
    cap,
    meta: dict,
    *,
    detector,
    getter,
    camera_id: str,
    cfg: dict,
    video_path: Path,
    storage_root: Path,
    max_samples: int,
) -> dict:
    """Sample → associate → clean → serialise, on an open capture.

    The four calls below are, in order, the same four the queued
    sidecar job makes in ``tracking_worker._run_one``. Only ``getter``
    differs, and every one of them takes it as an argument.
    """
    allowed = resolve_object_filter(getter, camera_id)
    thr = resolve_track_thresholds(getter, camera_id)
    # spawn == floor, exactly as the queued sidecar job does it: a
    # post-clip pass is a visualisation, and a replay that hid
    # everything below the live spawn threshold would answer "did
    # lowering the threshold help?" with an empty list every time.
    state = sample_clip(
        cap,
        meta,
        detector,
        allowed,
        floor_score=thr.floor,
        spawn_score=thr.floor,
        iou_threshold=thr.iou,
        block_contain=thr.block_contain,
        max_samples=max_samples,
    )
    clean_tracks(state, camera_id=camera_id, cam_cfg=cfg, spawn_score=thr.spawn)
    return build_payload(
        state,
        meta["fps"],
        meta["frame_count"],
        meta["duration_s"],
        allowed,
        video_path,
        storage_root,
        spawn_score=thr.spawn,
        floor_score=thr.floor,
        grace_s=thr.grace_seconds,
    )


def replay_clip(
    *,
    worker,
    camera_id: str,
    video_path: Path,
    storage_root: Path,
    cfg: dict,
    max_samples: int = REPLAY_MAX_SAMPLES,
) -> dict:
    """Walk ``video_path`` with ``cfg`` as the camera's settings.

    Returns the replay side of a comparison: the tracks it produced,
    those tracks collapsed to one detection each, the gates that were
    applied, and how much of the clip it got through.
    """
    started = time.time()

    def getter(_cam_id: str) -> dict:
        """The seam this whole module turns on: the pipeline asks for
        the camera's config and gets the settings under test."""
        return cfg

    cap, meta = open_video(video_path, precision=precision_for(getter, camera_id))
    if cap is None:
        raise ValueError(
            f"Clip nicht lesbar (fps={meta.get('fps', 0.0):.1f} "
            f"frames={meta.get('frame_count', 0)})"
        )

    detector = worker.detector()
    try:
        payload = _walk_clip(
            cap,
            meta,
            detector=detector,
            getter=getter,
            camera_id=camera_id,
            cfg=cfg,
            video_path=video_path,
            storage_root=storage_root,
            max_samples=max_samples,
        )
    finally:
        cap.release()

    tracks = payload.get("tracks") or []
    total = available_samples(meta)
    analysed = min(total, max_samples) if total else 0
    elapsed_ms = int((time.time() - started) * 1000)
    log.info(
        "[tracking] cam=%s replay tracks=%d frames=%d/%d in %d ms",
        camera_id,
        len(tracks),
        analysed,
        total,
        elapsed_ms,
    )
    return {
        "tracks": [compact_track(t) for t in tracks],
        "detections": [track_to_detection(t) for t in tracks],
        "gates": payload.get("gates") or {},
        "filter_applied": payload.get("filter_applied"),
        "frames_analysed": analysed,
        "frames_available": total,
        "truncated": bool(total and analysed < total),
        "duration_ms": elapsed_ms,
        "detector": describe_detector(detector),
    }
