"""Clip-production stages — the vocabulary shared by the recorder and the
media API.

A motion clip is not "done" the moment ffmpeg stops. It walks a short
chain, and until this module existed the frontend only ever saw the two
coarsest points of it:

    recording ──▶ queued ──▶ encoding ──▶ ready
                                    └───▶ failed

* ``recording`` — the stream-copy subprocess is writing ``<id>.raw.mp4``.
  Bounded by ``processing.clip_max_duration_s`` (default 120 s).
* ``queued``    — stream-copy finished, the re-encode thread is spawned
  but has not entered ffmpeg yet. Real, but normally milliseconds long:
  each clip gets its OWN thread, so this is *not* a FIFO position. Never
  render it as "3rd in line" — there is no line.
* ``encoding``  — ``ffmpeg -vcodec libx264`` is running. Hard-capped by
  the 300 s ``subprocess.run`` timeout in ``_reencode_motion_clip``.
* ``ready`` / ``failed`` — terminal.

Two stages are deliberately NOT in this vocabulary:

* thumbnail extraction — one cv2 seek + imwrite, sub-second. Announcing
  it would cost a full event-JSON rewrite to describe a state nobody can
  ever observe.
* the tracking sidecar — enqueued *after* ``status=ready``. The clip is
  playable at that point, and the Lightbox already owns that message.
  Repeating it in the library would show the same fact twice.

There is intentionally no percentage anywhere in this file. ffmpeg can
emit one via ``-progress``, but only by trading ``subprocess.run`` for a
reader thread that rewrites the per-camera event JSON at ~1 Hz per clip
— an atomic rewrite of the whole file, several times a second, for a
job that usually finishes in seconds. Elapsed-time-in-stage is truthful,
free, and doubles as the stall signal.

Staleness is derived at *read* time, never stored: a container restart
mid-encode leaves an event frozen in ``encoding`` with no process behind
it, and nothing would ever come along to write a "stalled" flag. Age
past the stage's own ceiling is the honest tell.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

# Same channel the rest of the camera_runtime package logs on, so the
# stage lines land in the ring buffer with everything else about the cam.
log = logging.getLogger("app.camera_runtime")

STAGE_RECORDING = "recording"
STAGE_QUEUED = "queued"
STAGE_ENCODING = "encoding"
# Coarse bucket for events written before the fine-grained stages
# existed (and for the OpenCV fallback path, which finalises in one
# blocking call and has no observable intermediate point). "Somewhere in
# post-processing, phase not recorded" — which is the truth about them.
STAGE_PROCESSING = "processing"
STAGE_READY = "ready"
STAGE_FAILED = "failed"

#: Fine stage → the coarse ``status`` value kept for backwards
#: compatibility. Every consumer that predates ``stage`` still reads
#: ``status`` and must keep seeing exactly what it saw before.
STAGE_STATUS = {
    STAGE_RECORDING: "recording",
    STAGE_QUEUED: "processing",
    STAGE_ENCODING: "processing",
    STAGE_PROCESSING: "processing",
    STAGE_READY: "ready",
    STAGE_FAILED: "error",
}

#: Legacy ``status`` → stage, for events written before ``stage`` existed.
_STATUS_STAGE = {
    "recording": STAGE_RECORDING,
    "processing": STAGE_PROCESSING,
    "ready": STAGE_READY,
    "error": STAGE_FAILED,
}

#: Stages that mean "work is still in flight".
PENDING_STAGES = (STAGE_RECORDING, STAGE_QUEUED, STAGE_ENCODING, STAGE_PROCESSING)

#: Seconds a stage may sit before it is considered stalled rather than
#: busy. ``recording`` is resolved against the configured clip ceiling;
#: the encode stages against the 300 s ffmpeg timeout plus slack for a
#: loaded box.
_STALL_SLACK_S = 120
_ENCODE_TIMEOUT_S = 300
_ENCODE_STALL_S = _ENCODE_TIMEOUT_S + 90

DEFAULT_CLIP_MAX_S = 120


def stall_ceiling_s(stage: str, clip_max_s: int = DEFAULT_CLIP_MAX_S) -> int:
    """How long ``stage`` may legitimately last, in seconds."""
    if stage == STAGE_RECORDING:
        return max(1, int(clip_max_s)) + _STALL_SLACK_S
    if stage == STAGE_QUEUED:
        return _STALL_SLACK_S
    if stage in (STAGE_ENCODING, STAGE_PROCESSING):
        return _ENCODE_STALL_S
    return 0


def set_clip_stage(store, camera_id: str, event_id: str, stage: str) -> None:
    """Move an in-flight clip to ``stage`` and stamp when it got there.

    One event-JSON write per transition — three per clip in total, which
    is what buys the library an honest "where is it right now" without a
    progress poller hammering the store. ``status`` keeps its old coarse
    values so every consumer that predates ``stage`` sees exactly what
    it saw before.

    Best-effort by design: a clip that fails to advertise its stage must
    still finish encoding.
    """
    try:
        ev = store.get_event(camera_id, event_id) or {}
        ev["stage"] = stage
        ev["status"] = STAGE_STATUS.get(stage, ev.get("status") or "processing")
        ev["stage_since"] = datetime.now().isoformat(timespec="seconds")
        store.update_event(camera_id, event_id, ev)
    except Exception as e:
        log.debug("[%s] stage update (%s) failed: %s", camera_id, stage, e)


def stage_of(event: dict) -> str:
    """The fine stage of ``event``, falling back to the coarse ``status``
    for events written before stages were recorded."""
    stage = (event or {}).get("stage")
    if stage in STAGE_STATUS:
        return stage
    return _STATUS_STAGE.get((event or {}).get("status") or "", STAGE_READY)


def is_pending(event: dict) -> bool:
    """True while the clip is still being produced."""
    return stage_of(event) in PENDING_STAGES


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace(" ", "T"))
    except (TypeError, ValueError):
        return None


def stage_age_s(event: dict, now: datetime) -> Optional[int]:
    """Seconds since the event entered its current stage.

    Falls back to the event's start time when ``stage_since`` is absent
    (every event written before this module shipped). That fallback
    over-reports for post-recording stages — it includes the recording
    itself — which is why :func:`annotate_stage` widens the ceiling by
    one clip length in exactly that case.
    """
    ref = _parse_iso((event or {}).get("stage_since") or "") or _parse_iso(
        (event or {}).get("time") or ""
    )
    if ref is None:
        return None
    if ref.tzinfo is not None and now.tzinfo is None:
        ref = ref.replace(tzinfo=None)
    try:
        return max(0, int((now - ref).total_seconds()))
    except TypeError:
        return None


def annotate_stage(event: dict, now: datetime, clip_max_s: int = DEFAULT_CLIP_MAX_S) -> dict:
    """Attach the derived, never-persisted stage fields to ``event``.

    Adds ``stage``, ``stage_age_s`` and ``stage_stalled`` for in-flight
    events and leaves finished ones untouched — a ready clip carries no
    stage chatter, so the library shows each fact exactly once.
    """
    if not is_pending(event):
        return event
    stage = stage_of(event)
    age = stage_age_s(event, now)
    ceiling = stall_ceiling_s(stage, clip_max_s)
    if not (event or {}).get("stage_since") and stage != STAGE_RECORDING:
        # No per-stage timestamp: the age we have starts at the clip's
        # beginning, so allow one whole recording on top before calling
        # it stuck.
        ceiling += max(1, int(clip_max_s))
    event["stage"] = stage
    event["stage_age_s"] = age
    event["stage_stalled"] = bool(age is not None and ceiling and age > ceiling)
    return event
