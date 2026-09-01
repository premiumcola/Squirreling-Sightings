"""Main-stream JPEG pre-roll ring for the ffmpeg stream-copy motion path.

Why this is a NEW ring and not a reuse of an existing one
───────────────────────────────────────────────────────────
Two rings already exist in this codebase and both were evaluated:

* ``camera_runtime.WeatherPrebuffer`` buffers SUB-STREAM frames (the
  preview loop's resolution/cadence, e.g. 1280×720 @ 15 fps) for a
  different consumer: the weather clip encoder stitches EVERY frame of
  the finished clip — pre-roll AND post-roll — from that one JPEG
  source (see weather_service/_clip.py::_trigger_clip). Splicing THAT
  buffer onto an ffmpeg stream-copied MAIN-stream clip (2560×1440 in
  this deployment — see camera_runtime/_capture.py's own resolution
  comment) would prepend a visibly lower-resolution segment onto a
  native-resolution one. weather_service/_event_tl_ring.py already
  documents rejecting WeatherPrebuffer for the same reason (wrong
  frame source) for its own, unrelated pre-roll need.
* ``weather_service.EventTLRing`` buffers to DISK for a minutes-long,
  forecast-armed window. Motion pre-roll needs the opposite shape: a
  tiny (single-digit-second), always-on, zero-disk-I/O-in-steady-state
  buffer that a motion trigger can fire at any moment, not one that
  arms ahead of a predicted event.

So this ring buffers MAIN-stream frames, fed straight from
``_main_loop``'s every-tick ``proc_frame`` (see
``_recording_step.RecordingStepMixin._rtsp_recording_step``) — the SAME
frame already decoded for motion/object detection, so pushing a frame
here costs one JPEG encode, no extra RTSP decode or connection.

JPEG, not raw BGR
──────────────────
A raw BGR frame at 2560×1440 is ≈ 10.6 MB. At the shipped
``frame_interval_ms`` default (350 ms → ~2.9 fps) a 3 s window is only
~9 frames, but an aggressively low per-camera interval could hold far
more — an unbounded raw-frame ring is exactly the OOM risk
``WeatherPrebuffer``'s own docstring reasons about, at roughly 4× the
per-frame cost (2560×1440 vs 1280×720). JPEG cuts that ~10-20×, the
same trade weather already made. ``DEFAULT_MAX_BYTES`` is a second,
independent bound so a run of unusually detailed frames or a
misconfigured (very low) frame_interval_ms cannot outgrow the budget —
mirrors ``EventTLRing``'s two-bound eviction.

Playback trade-off (log this so nobody re-discovers it as a bug)
──────────────────────────────────────────────────────────────
The spliced pre-roll segment plays back at the loop's detection cadence
(≈3 fps by default), not the camera's native stream fps (typically
15-25 fps) that the ffmpeg stream-copy segment carries. The splice is a
visible frame-rate step at the boundary. This is an inherent limit of
building pre-roll from detection-sample stills instead of a second
continuous high-fps decode of the main stream (which would cost as
much CPU as the primary detection loop, per camera, permanently) — a
choppier few seconds of real lead-in is judged strictly better than
the 0 s the ffmpeg path shipped with.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import cv2

from .._consts import log

# camera_runtime/_recording/ is two levels under app/app/, so
# ``...media_encode`` resolves to app.app.media_encode.
from ...media_encode import encode_jpeg_frames_to_mp4

DEFAULT_CAPACITY_S = 3.0
DEFAULT_JPEG_QUALITY = 82
# ~9 frames/camera at the shipped cadence should run well under 8 MB;
# this is a generous safety valve for a misconfigured low interval or an
# unusually detailed scene, not the expected steady-state size.
DEFAULT_MAX_BYTES = 48 * 1024 * 1024


def resolve_pre_motion_seconds(cam_cfg: dict, global_cfg: dict) -> float:
    """0 (or unset) on the camera means "inherit the global default" —
    mirrors ``post_motion_tail_s``'s existing convention (see
    ``_recording_step.py``'s identical ``_post_tail`` resolution). Pure
    function so the resolution rule is testable without constructing a
    full ``CameraRuntime``."""
    proc = (global_cfg or {}).get("processing") or {}
    return float((cam_cfg or {}).get("pre_motion_seconds") or proc.get("pre_motion_seconds", 3.0))


class MotionPreroll:
    """Rolling, time-bounded ring of ``(timestamp, jpeg_bytes)`` main-stream
    frames for ONE camera. Not thread-safe across cameras — one instance
    per ``CameraRuntime``, matching ``WeatherPrebuffer``'s shape.
    """

    def __init__(
        self,
        camera_id: str,
        capacity_s: float = DEFAULT_CAPACITY_S,
        jpeg_quality: int = DEFAULT_JPEG_QUALITY,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ):
        self.camera_id = camera_id
        # 0 (or negative) disables the ring entirely — push() becomes a
        # no-op so an operator who sets pre_motion_seconds: 0 pays no
        # per-frame JPEG-encode cost for a feature they turned off.
        self.capacity_s = max(0.0, float(capacity_s))
        self._quality = int(jpeg_quality)
        self._max_bytes = max(1, int(max_bytes))
        self._lock = threading.Lock()
        self._frames: deque = deque()  # (ts, jpeg_bytes), oldest first
        self._bytes = 0
        # Diagnostic only — how many frames the byte cap has ever had to
        # evict early (i.e. before their time-based cutoff). A nonzero,
        # growing count means the configured pre-roll window is costing
        # more than DEFAULT_MAX_BYTES and deserves operator attention.
        self.byte_cap_drops = 0

    @property
    def bytes_held(self) -> int:
        with self._lock:
            return self._bytes

    def push(self, bgr_frame) -> None:
        if self.capacity_s <= 0 or bgr_frame is None:
            return
        try:
            ok, buf = cv2.imencode(
                '.jpg', bgr_frame, [int(cv2.IMWRITE_JPEG_QUALITY), self._quality]
            )
            if not ok:
                return
            jpg = buf.tobytes()
        except Exception:
            return
        now = time.time()
        with self._lock:
            self._frames.append((now, jpg))
            self._bytes += len(jpg)
            self._evict_locked(now)

    def _evict_locked(self, now: float) -> None:
        cutoff = now - self.capacity_s
        while self._frames and self._frames[0][0] < cutoff:
            _, old = self._frames.popleft()
            self._bytes -= len(old)
        dropped = 0
        while self._frames and self._bytes > self._max_bytes:
            _, old = self._frames.popleft()
            self._bytes -= len(old)
            dropped += 1
        if dropped:
            self.byte_cap_drops += dropped
            log.warning(
                "[%s] motion pre-roll ring over byte cap (%d bytes) — dropped %d frame(s) early",
                self.camera_id,
                self._max_bytes,
                dropped,
            )

    def snapshot(self) -> list[tuple[float, bytes]]:
        """Frozen copy of the currently buffered frames, oldest first."""
        with self._lock:
            return list(self._frames)


class MotionPrerollMixin:
    """Splice a ``MotionPreroll`` snapshot onto an already-transcoded
    ffmpeg stream-copy clip. Mixin for ``RecordingMixin`` — see
    ``_ffmpeg_clip.FfmpegClipMixin._reencode_motion_clip``, the only
    caller.
    """

    def _splice_preroll_onto_clip(
        self,
        vid_path: Path,
        preroll_frames: list[tuple[float, bytes]],
        event_id: str,
        day_dir: Path,
    ) -> float:
        """Encode the buffered pre-trigger stills into their own short mp4
        and concat them onto the front of ``vid_path`` IN PLACE.

        Returns the pre-roll duration actually spliced in, in seconds —
        0.0 on ANY failure or when there is nothing worth splicing, in
        which case ``vid_path`` is left byte-for-byte untouched. The
        caller reports this number verbatim in the event's
        recording_settings, so it must never overstate what actually
        landed on disk.
        """
        # A single frame carries no time span to derive an fps from, and
        # is not worth a splice on its own merits either.
        if not preroll_frames or len(preroll_frames) < 2:
            return 0.0
        span = preroll_frames[-1][0] - preroll_frames[0][0]
        if span <= 0:
            return 0.0
        pre_fps = max(1.0, min(30.0, len(preroll_frames) / span))
        preroll_path = day_dir / f"{event_id}.preroll.mp4"
        spliced_path = day_dir / f"{event_id}.spliced.mp4"
        try:
            if not encode_jpeg_frames_to_mp4(
                preroll_frames,
                preroll_path,
                int(round(pre_fps)),
                crf=22,
                log_tag=f"[{self.camera_id}]",
            ):
                log.warning(
                    "[%s] pre-roll encode failed for %s — clip keeps 0 s lead-in",
                    self.camera_id,
                    event_id,
                )
                return 0.0
            if not self._concat_preroll_and_clip(preroll_path, vid_path, spliced_path):
                log.warning(
                    "[%s] pre-roll concat failed for %s — clip keeps 0 s lead-in",
                    self.camera_id,
                    event_id,
                )
                return 0.0
            # Verify the spliced result is a healthy, readable video BEFORE
            # trusting it over the clip we already know works — never swap
            # in something worse than what we had.
            check = cv2.VideoCapture(str(spliced_path))
            fc = int(check.get(cv2.CAP_PROP_FRAME_COUNT))
            cfps = check.get(cv2.CAP_PROP_FPS) or 0.0
            check.release()
            if fc < 3 or cfps <= 0:
                log.warning(
                    "[%s] spliced clip %s unreadable (frames=%d fps=%.1f) — "
                    "keeping trigger-only clip",
                    self.camera_id,
                    event_id,
                    fc,
                    cfps,
                )
                return 0.0
            # Atomic on the same filesystem (both paths share day_dir).
            spliced_path.replace(vid_path)
            return round(span, 2)
        except Exception as e:
            log.warning("[%s] pre-roll splice error for %s: %s", self.camera_id, event_id, e)
            return 0.0
        finally:
            with contextlib.suppress(Exception):
                preroll_path.unlink(missing_ok=True)
            with contextlib.suppress(Exception):
                if spliced_path.exists():
                    spliced_path.unlink()

    @staticmethod
    def _concat_preroll_and_clip(preroll_path: Path, main_path: Path, out_path: Path) -> bool:
        """ffmpeg concat-demuxer join: preroll_path THEN main_path, re-
        encoded to one continuous mp4. Mirrors
        weather_service._recaps._concat_clips's concat-demuxer technique;
        re-encodes (rather than ``-c copy``) so small parameter drift
        between the two independent encode passes can never produce an
        unplayable splice — these clips are a few seconds long, the extra
        pass is cheap."""
        if not preroll_path.exists() or not main_path.exists():
            return False
        if preroll_path.stat().st_size < 1024 or main_path.stat().st_size < 1024:
            return False
        if not shutil.which("ffmpeg"):
            return False
        list_file = out_path.with_suffix(".txt")
        try:
            list_file.write_text(
                "\n".join(
                    f"file '{str(p).replace(chr(39), chr(92) + chr(39))}'"
                    for p in (preroll_path, main_path)
                ),
                encoding="utf-8",
            )
            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-vcodec",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "22",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-an",
                str(out_path),
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=120)
            if r.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 1024:
                return False
            return True
        except Exception:
            return False
        finally:
            with contextlib.suppress(Exception):
                list_file.unlink(missing_ok=True)
