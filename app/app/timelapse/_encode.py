"""The two encoders: ffmpeg (primary) and OpenCV (fallback).

Both are mixin methods rather than free functions because the build
tests monkeypatch them on ``TimelapseBuilder`` to run without an ffmpeg
binary in CI.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
from pathlib import Path

import cv2

from ._consts import log
from ._geometry import fit_into_box, scale_dims


# 50 KB floor — empirically the smallest VALID H.264 mp4 we see from a
# 2-frame, 16x16 source is ~12 KB; the bad zero-duration writes we want
# to reject land at <= 2 KB (just the moov atom + sps/pps headers). 50 KB
# is the safest threshold that catches the failure mode without rejecting
# any legitimate output.
_MIN_OUTPUT_BYTES = 50_000


def _ffmpeg_cmd(concat_path: str, out_w: int, out_h: int, out_path: Path) -> list[str]:
    """The encode command line for one window."""
    return [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_path,
        "-vf",
        # force_original_aspect_ratio + pad: a frame that is NOT the
        # majority size is letterboxed into the output box instead of
        # being stretched to fill it. `scale` alone distorts, which is
        # how one odd frame used to squash a whole timelapse.
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
        f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
        "-c:v",
        "libx264",
        "-crf",
        "28",  # good quality/size balance
        "-preset",
        "fast",
        "-movflags",
        "+faststart",  # progressive download / iOS
        "-pix_fmt",
        "yuv420p",  # required for broad iOS/Android compat
        str(out_path),
    ]


def _encode_succeeded(result, out_path: Path) -> bool:
    """True only for a clean exit that left a plausibly sized file.

    Both failure shapes are reported rather than swallowed: a non-zero
    exit carries ffmpeg's own stderr tail, and a zero exit that produced
    a runt file is the silent case worth a WARNING of its own.
    """
    if result.returncode != 0:
        log.warning(
            "[timelapse] ffmpeg failed for %s: %s",
            out_path.name,
            result.stderr.decode(errors="replace")[-300:],
        )
        return False
    if not out_path.exists():
        return False
    size = out_path.stat().st_size
    if size >= _MIN_OUTPUT_BYTES:
        return True
    log.warning(
        "[timelapse] ffmpeg wrote %s but file is %d B < 50 KB · treating as failure",
        out_path.name,
        size,
    )
    return False


class EncodeMixin:
    """Frame list in, MP4 (and thumbnail) out."""

    def _write_video_ffmpeg(
        self, valid_paths: list, out_path: Path, fps: float, ref_size: tuple[int, int]
    ) -> str | None:
        """Encode valid JPEG frames to H.264 MP4 via ffmpeg concat demuxer.
        No frame data is loaded into Python memory — ffmpeg reads files directly.
        Returns path string on success, None on failure."""
        # Defence-in-depth — _write_video already rejects len<2 before
        # we get here, but a direct caller could still hand us 0 or 1
        # paths. ffmpeg-concat with a single entry silently produces a
        # 1-frame mp4 that fails ffprobe duration validation downstream
        # but leaves an inscrutable file on disk; refusing up front is
        # cheaper and produces a clearer log line.
        if len(valid_paths) < 2:
            log.warning(
                "[timelapse] _write_video_ffmpeg refused — only %d input frame(s) for %s",
                len(valid_paths),
                out_path.name,
            )
            return None
        w, h = ref_size
        out_w, out_h = scale_dims(w, h)
        frame_dur = 1.0 / fps

        concat_fd, concat_path = tempfile.mkstemp(suffix=".txt")
        try:
            with os.fdopen(concat_fd, "w") as f:
                for p in valid_paths:
                    # ffmpeg concat requires forward slashes even on Windows
                    f.write(f"file '{str(p).replace(chr(92), '/')}'\n")
                    f.write(f"duration {frame_dur:.6f}\n")
                # Repeat last frame entry without duration (ffmpeg concat requirement)
                if valid_paths:
                    f.write(f"file '{str(valid_paths[-1]).replace(chr(92), '/')}'\n")

            result = subprocess.run(
                _ffmpeg_cmd(concat_path, out_w, out_h, out_path),
                capture_output=True,
                timeout=180,
            )
            if _encode_succeeded(result, out_path):
                log.debug(
                    "[timelapse] ffmpeg encoded %s (%d frames → H.264 %dx%d, %d bytes)",
                    out_path.name,
                    len(valid_paths),
                    out_w,
                    out_h,
                    out_path.stat().st_size,
                )
                return str(out_path)
        except Exception as e:
            log.warning("[timelapse] ffmpeg exception for %s: %s", out_path.name, e)
        finally:
            with contextlib.suppress(Exception):
                os.unlink(concat_path)
        return None

    def _write_video_opencv(
        self, valid_paths: list, out_path: Path, fps: float, ref_size: tuple[int, int]
    ) -> str | None:
        """Fallback encoder using OpenCV VideoWriter (mp4v/MPEG-4 Part 2).
        Reads and writes one frame at a time to keep peak memory low."""
        w, h = ref_size
        out_w, out_h = scale_dims(w, h)
        writer = cv2.VideoWriter(
            str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (out_w, out_h)
        )
        if not writer.isOpened():
            writer.release()
            writer = cv2.VideoWriter(
                str(out_path), cv2.VideoWriter_fourcc(*"DIVX"), fps, (out_w, out_h)
            )
        for img_path in valid_paths:
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            if (img.shape[1], img.shape[0]) != (out_w, out_h):
                img = fit_into_box(img, out_w, out_h)
            writer.write(img)
            del img
        writer.release()
        # Mirror the 50 KB floor from the ffmpeg path — OpenCV mp4v
        # encoder lands ~30 % larger than libx264 for the same input,
        # so 50 KB is well below any legitimate output and still
        # catches the zero-content writer failure mode.
        if out_path.exists() and out_path.stat().st_size >= _MIN_OUTPUT_BYTES:
            return str(out_path)
        if out_path.exists():
            log.warning(
                "[timelapse] opencv wrote %s but file is %d B < 50 KB · treating as failure",
                out_path.name,
                out_path.stat().st_size,
            )
        return None

    def _write_thumbnail(self, img_path: Path, out_path: Path) -> None:
        """Write a thumbnail .jpg alongside the video. Max 640px wide."""
        try:
            img = cv2.imread(str(img_path))
            if img is None:
                return
            tw, th = img.shape[1], img.shape[0]
            if tw > 640:
                scale = 640 / tw
                img = cv2.resize(img, (640, int(th * scale)))
            thumb_path = out_path.with_suffix(".jpg")
            cv2.imwrite(str(thumb_path), img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            log.debug("[timelapse] thumbnail written: %s", thumb_path.name)
        except Exception as e:
            log.debug("[timelapse] thumbnail write failed: %s", e)
