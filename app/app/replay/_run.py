"""Run one stored clip back through the post-clip detection pipeline.

Not a second pipeline. Every step below is the same function the queued
sidecar job calls in ``tracking_worker._run_one``; the only difference is
the ``cam_cfg_getter`` handed to them. Each of ``precision_for``,
``resolve_object_filter`` and ``resolve_track_thresholds`` already takes
that getter as an argument, so replaying "with different settings" is
handing them a getter that returns the settings under test instead of
the camera's live ones. Nothing in the worker needed a branch.

One thing IS added rather than borrowed: the second-stage bird
classifier. The queued sidecar job does not run it, so a replay that
only ran the four steps above could count birds but never name them —
see `_species.py` for why that was the missing half of the answer, and
why the naming still goes through the live loop's own stamping
function rather than a copy of it.

Three properties keep this safe to call from a request thread:

  * It borrows ``worker.detector()`` — the CPU-pinned instance — so a
    replay never competes for the single Edge TPU the live camera
    runtimes own. This is the same protection the queued jobs have, and
    it comes from the detector, not from which thread runs it.
  * The classifier is borrowed on the same terms, from
    ``worker.bird_classifier()``, and is pinned to CPU independently of
    what `processing.bird_species.prefer_cpu` says for live detection.
  * It is bounded on BOTH costs. ``max_samples`` caps the decode
    attempts and ``max_crops`` caps the classifier invocations, which
    are not the same number: one sampled frame holding a flock is one
    decode and many crops. The result reports each separately, so the
    caller can say "180 von 420 Frames, davon 96 mit Artbestimmung".
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
from ._consts import REPLAY_MAX_CROPS, REPLAY_MAX_SAMPLES
from ._diff import track_to_detection
from ._species import SpeciesTally, make_sample_hook

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


def classifier_for(worker, classify: bool):
    """The classifier this replay should use, or None.

    ``worker.bird_classifier`` is looked up rather than called outright
    because ``replay_clip`` accepts anything exposing the worker's
    accessors — the batch path and the test suite both hand in
    stand-ins, and a stand-in built before the second stage existed
    carries only ``detector``. Such a worker gets a detector-only run
    that still reports its box counts, instead of an exception that
    would lose the whole comparison over the half of it that is
    optional.
    """
    if not classify:
        return None
    accessor = getattr(worker, "bird_classifier", None)
    return accessor() if callable(accessor) else None


def describe_classifier(classifier, *, requested: bool) -> dict:
    """What named the species, and on which device.

    Reported for the same reason `describe_detector` is: a species list
    is only readable next to what produced it. ``mode`` is the honest
    field — "cpu" is the expected answer for a replay (the worker pins
    it there, see tracking_worker/_classifier.py), and anything else in
    that slot means the pinning stopped working and live capture is
    sharing its accelerator with an archive sweep.

    ``requested`` separates the two ways a run ends up with no
    classifier: the caller asked for a detector-only pass, or it asked
    for species and could not get them. An empty species list means
    something different in each case.
    """
    if classifier is None:
        return {
            "available": False,
            "mode": None,
            "model": None,
            "reason": "unavailable" if requested else "not_requested",
        }
    model = getattr(classifier, "active_model_path", None)
    return {
        "available": bool(getattr(classifier, "available", False)),
        "mode": getattr(classifier, "mode", None),
        "model": Path(model).name if model else None,
        "reason": getattr(classifier, "reason", None),
    }


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
    sample_hook=None,
) -> dict:
    """Sample → associate → clean → serialise, on an open capture.

    The four calls below are, in order, the same four the queued
    sidecar job makes in ``tracking_worker._run_one``. Only ``getter``
    and ``sample_hook`` differ, and both are arguments those functions
    already take.
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
        sample_hook=sample_hook,
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
    max_crops: int = REPLAY_MAX_CROPS,
    classify: bool = True,
) -> dict:
    """Walk ``video_path`` with ``cfg`` as the camera's settings.

    Returns the replay side of a comparison: the tracks it produced,
    those tracks collapsed to one detection each, the gates that were
    applied, how much of the clip it got through, and — unless
    ``classify`` is off — the bird species it named along the way.

    ``classify`` defaults to ON because naming species is what a replay
    over archived bird clips is FOR. The original event already froze a
    detection list from one frame; a re-run that only recounted boxes
    would repeat the cheap half of the question. Passing False gives a
    detector-only run for the cases that genuinely only need box counts
    — a threshold sweep comparing many tunings over the same clip,
    where the species would be identical every time and the classifier
    would be pure cost.
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
    # Borrowed, never built here — the same rule the detector follows,
    # and for the same reason: a classifier of our own could take the
    # Edge TPU the live camera runtimes own. See
    # tracking_worker/_classifier.py.
    classifier = classifier_for(worker, classify)
    tally = SpeciesTally(max_crops=max_crops)
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
            sample_hook=make_sample_hook(classifier, tally),
        )
    finally:
        cap.release()

    tracks = payload.get("tracks") or []
    total = available_samples(meta)
    analysed = min(total, max_samples) if total else 0
    species = tally.result()
    elapsed_ms = int((time.time() - started) * 1000)
    log.info(
        "[tracking] cam=%s replay tracks=%d frames=%d/%d classified=%d/%d "
        "crops=%d species=%d in %d ms",
        camera_id,
        len(tracks),
        analysed,
        total,
        tally.frames_classified,
        analysed,
        tally.crops_classified,
        len(species),
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
        # Whole-clip species, best-scoring first — the half of the
        # answer a detector-only replay could never give.
        "species": species,
        "classified": bool(classify and classifier is not None),
        "classifier": describe_classifier(classifier, requested=classify),
        **tally.stats(),
    }
