"""Pick the strongest frame of a clip and burn its boxes onto a JPEG.

Split out of `_outbound/__init__.py` (far past the 500-line file budget)
and, inside this module, cut along the pipeline it always was: wait for
the sidecar → read the cache → seek the frame with ffmpeg → draw and
re-encode. Each stage answers None for "not available" and the mixin
method below is only the chain of those four.

Nothing here is Telegram-specific except the reason it exists: receivers
cannot render the Canvas overlay the lightbox draws client-side, so the
push needs the boxes baked in. The on-disk MP4 is never touched.

The heavy imports (cv2, numpy, the detectors package, subprocess) stay
inside the functions that need them — this module is imported at boot on
every install, including ones where no push ever carries a photo.
"""

from __future__ import annotations

import time
from pathlib import Path

from .._consts import log

# Sidecar wait budget — a GRACE PERIOD, not a wait for the job.
#
# This was 2.0 s, on the belief that "most clips finish tracking in well
# under this". They do not, and cannot: the tracking job is enqueued
# about five lines before the alert path runs (_ffmpeg_clip.py), the
# worker is a single serialised thread shared by every camera, and the
# pass costs roughly one model invoke per second of clip — the worker's
# own budget is a THIRD of the clip's duration, which for a 15 s clip is
# ~5 s. A 2 s wait was therefore two seconds of sleeping before the same
# fallback, on essentially every alert.
#
# What the short budget below is actually for: a sidecar that already
# exists — a re-send, a /resend, an older clip — or one being written at
# this instant. Both return on the first or second tick. Anything longer
# is the module's own stated rule applied one stage earlier: the push is
# more valuable prompt than best-framed.
_TRACKS_WAIT_S = 0.4
_TRACKS_POLL_S = 0.1
# ffmpeg gets one second to produce a single frame — past that the push
# is more valuable late-free than best-framed, so we fall back.
_FFMPEG_TIMEOUT_S = 1.0
_JPEG_QUALITY = 85


def _wait_for_tracks(tracks_path: Path, event_id: str) -> dict | None:
    """Block briefly for the Phase-1 worker's tracks.json, then parse it.

    None means "no usable sidecar" for any reason — never written, still
    being written, or corrupt on disk."""
    deadline = time.time() + _TRACKS_WAIT_S
    while not tracks_path.exists() and time.time() < deadline:
        time.sleep(_TRACKS_POLL_S)
    if not tracks_path.exists():
        log.info("[tg] best-frame: tracks.json not ready for %s, fallback", event_id)
        return None
    import json as _json

    try:
        return _json.loads(tracks_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("[tg] best-frame: tracks.json parse fail %s: %s", tracks_path.name, e)
        return None


def _cached_render(cache_path: Path, tracks_path: Path) -> bytes | None:
    """Return the previously rendered JPEG when it is newer than the
    tracks.json that drove it. Re-sends (resilience retry, /resend) skip
    the ffmpeg + draw work entirely."""
    if not cache_path.exists():
        return None
    try:
        if cache_path.stat().st_mtime >= tracks_path.stat().st_mtime:
            return cache_path.read_bytes()
    except Exception:
        pass  # corrupt cache → caller re-renders
    return None


def _extract_frame(video_path: Path, t_seek: float, event_id: str) -> bytes | None:
    """Seek one frame out of the clip as JPEG bytes.

    -ss before -i seeks via keyframes (fast, may snap to the nearest one
    up to ~2 s away); acceptable because best_frame normally sits well
    inside a continuous run. -frames:v 1 + mjpeg gives a single-image
    stream on stdout."""
    import shutil as _shutil

    ffmpeg_bin = _shutil.which("ffmpeg")
    if not ffmpeg_bin:
        log.info("[tg] best-frame: ffmpeg missing, fallback")
        return None
    import subprocess as _sp

    try:
        proc = _sp.run(
            [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{t_seek:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-f",
                "mjpeg",
                "-",
            ],
            capture_output=True,
            timeout=_FFMPEG_TIMEOUT_S,
        )
    except _sp.TimeoutExpired:
        log.warning("[tg] best-frame: ffmpeg timeout for %s, fallback", event_id)
        return None
    if proc.returncode != 0 or not proc.stdout:
        log.warning(
            "[tg] best-frame: ffmpeg rc=%s len=%d for %s, fallback",
            proc.returncode,
            len(proc.stdout or b""),
            event_id,
        )
        return None
    return proc.stdout


def _synth_detections(tracks: dict, best_f: int) -> list:
    """Rebuild a Detection list from the track samples that land on the
    chosen frame — one sample per track, malformed boxes skipped."""
    from ...detectors import Detection

    dets = []
    for tr in tracks.get("tracks", []) or []:
        label = tr.get("label", "?")
        for s in tr.get("samples", []) or []:
            if s.get("f") != best_f:
                continue
            bb = s.get("bbox") or {}
            try:
                box = (int(bb["x1"]), int(bb["y1"]), int(bb["x2"]), int(bb["y2"]))
            except Exception:
                continue
            score = s.get("score")
            if score is None:
                score = tr.get("best_score") or 0.0
            dets.append(Detection(label=label, score=float(score), bbox=box))
            break  # one sample per track at this frame
    return dets


def _render(jpeg_bytes: bytes, tracks: dict, best: dict, event_id: str, cache_path: Path):
    """Decode → draw the boxes → re-encode, and cache the result next to
    the mp4. Returns None if the frame cannot be decoded or encoded."""
    try:
        import cv2 as _cv2
        import numpy as _np

        arr = _np.frombuffer(jpeg_bytes, dtype=_np.uint8)
        frame = _cv2.imdecode(arr, _cv2.IMREAD_COLOR)
        if frame is None:
            log.warning("[tg] best-frame: imdecode failed for %s", event_id)
            return None
        from ...detectors import draw_detections

        best_f = int(best.get("f") or 0)
        synth_dets = _synth_detections(tracks, best_f)
        if synth_dets:
            frame = draw_detections(frame, synth_dets)
        ok, buf = _cv2.imencode(".jpg", frame, [int(_cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY])
        if not ok:
            return None
        out_bytes = buf.tobytes()
        try:
            cache_path.write_bytes(out_bytes)
        except Exception:
            pass  # non-fatal — return the rendered bytes anyway
        log.info(
            "[tg] best-frame: event=%s f=%d t=%.2f score=%.2f boxes=%d size=%dKB",
            event_id,
            best_f,
            float(best.get("t") or 0.0),
            float(best.get("score") or 0.0),
            len(synth_dets),
            len(out_bytes) // 1024,
        )
        return out_bytes
    except Exception as e:
        log.warning("[tg] best-frame: render failed for %s: %s", event_id, e)
        return None


class BestFrameMixin:
    """Best-frame resolution for TelegramService. Mixin — reads shared
    state via `self.*` (store, config accessors)."""

    def _best_frame_jpeg(self, meta: dict, camera_id: str) -> bytes | None:
        """Resolve the "best frame" for an event from the tracking
        sidecar and return JPEG bytes with the bbox burnt on. The
        recording-side tracks.json (Phase 1 worker) carries the highest-
        scoring detection across the whole clip; pushing that frame
        gives the receiver the strongest single image instead of
        whichever frame happened to trigger.

        Returns None on any failure (worker not ready, ffmpeg missing,
        tracks.json absent or corrupt, video missing). Caller is
        expected to fall back to the trigger snapshot in that case.

        Side effect: caches the rendered JPEG as <event_id>.best.jpg
        next to the mp4."""
        try:
            event_id = meta.get("event_id")
            if not event_id or not self.store:
                return None
            ev = self.store.get_event(camera_id, event_id)
            if not ev:
                return None
            video_rel = ev.get("video_relpath")
            if not video_rel:
                return None
            video_path = self._storage_root() / video_rel
            if not video_path.exists():
                return None
            from ...tracking_worker import tracks_path_for

            tracks_path = tracks_path_for(video_path)
            tracks = _wait_for_tracks(tracks_path, event_id)
            if tracks is None:
                return None
            best = tracks.get("best_frame")
            if not best or not isinstance(best, dict):
                log.info("[tg] best-frame: no best_frame in tracks.json for %s, fallback", event_id)
                return None
            cache_path = video_path.with_name(video_path.stem + ".best.jpg")
            cached = _cached_render(cache_path, tracks_path)
            if cached is not None:
                return cached
            raw = _extract_frame(video_path, float(best.get("t") or 0.0), event_id)
            if raw is None:
                return None
            return _render(raw, tracks, best, event_id, cache_path)
        except Exception as e:
            log.debug("[tg] best-frame: %s", e)
            return None
