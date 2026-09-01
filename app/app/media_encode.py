"""Shared JPEG-frame-sequence → MP4 encoder.

Two callers need the exact same primitive: "pipe N independently-captured
JPEG stills through ffmpeg's mjpeg demuxer into one browser-friendly H.264
mp4."

  * ``weather_service/_clip.py`` — weather sighting clips, splicing a
    ``WeatherPrebuffer`` pre-roll onto a live post-roll capture.
  * ``camera_runtime/_recording/_preroll.py`` — motion-clip pre-roll,
    splicing a ``MotionPreroll`` ring onto the ffmpeg stream-copy clip.

Both used to carry their own copy of the same ffmpeg command line. Factored
out here so there is one command to get right, not two that can drift.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("app.media_encode")


def encode_jpeg_frames_to_mp4(
    frames: list[tuple[float, bytes]],
    out_path: Path,
    fps: int,
    *,
    crf: int = 23,
    preset: str = "fast",
    log_tag: str = "[storage]",
) -> bool:
    """Encode a ``[(timestamp, jpeg_bytes), ...]`` sequence to an H.264 mp4.

    The timestamp is the caller's bookkeeping only — frames are written to
    ffmpeg in list order at a constant ``fps``, real gaps between captures
    are not reproduced. Returns False on any failure (missing ffmpeg, spawn
    error, non-zero exit, or a missing/undersized result) so the caller can
    fall back to whatever it had before calling this.
    """
    if not frames:
        return False
    if not shutil.which("ffmpeg"):
        log.warning("%s ffmpeg unavailable — cannot encode jpeg-frame clip", log_tag)
        return False
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-framerate",
        str(max(1, int(fps))),
        "-i",
        "pipe:0",
        "-vcodec",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(int(crf)),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        write_failed = False
        for _ts, jpg in frames:
            try:
                proc.stdin.write(jpg)
            except Exception:
                write_failed = True
                break
        # Don't proc.stdin.close() here — communicate() does it for us, and
        # a manual close before communicate raises "flush of closed file"
        # on the next communicate() call.
        try:
            _out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            log.warning("%s ffmpeg timeout — killed", log_tag)
            return False
        if proc.returncode != 0:
            log.warning(
                "%s ffmpeg rc=%s stderr=%s",
                log_tag,
                proc.returncode,
                (err or b"").decode("utf-8", "replace")[-300:],
            )
            return False
        if write_failed:
            log.debug("%s partial frame write — clip may be short", log_tag)
        return out_path.exists() and out_path.stat().st_size > 1024
    except Exception as e:
        log.warning("%s ffmpeg pipe error: %s", log_tag, e)
        return False
