"""Shared JPEG-frame-sequence → MP4 encoder, and the clip audio contract.

Two callers need the exact same primitive: "pipe N independently-captured
JPEG stills through ffmpeg's mjpeg demuxer into one browser-friendly H.264
mp4."

  * ``weather_service/_clip.py`` — weather sighting clips, splicing a
    ``WeatherPrebuffer`` pre-roll onto a live post-roll capture.
  * ``camera_runtime/_recording/_preroll.py`` — motion-clip pre-roll,
    splicing a ``MotionPreroll`` ring onto the ffmpeg stream-copy clip.

Both used to carry their own copy of the same ffmpeg command line. Factored
out here so there is one command to get right, not two that can drift.

The same argument brought the motion clip's OWN re-encode command here
(``build_reencode_cmd``, run by
``camera_runtime/_recording/_ffmpeg_clip.py``). A motion clip recorded with
audio is two independently encoded segments joined by a concat demuxer, and
that join is a stream copy — so the pre-roll encoder above and the main
clip's encoder must agree on the audio codec, sample rate and channel
layout down to the last argument. Keeping both command lines and the
constants they read in one file is what makes that agreement structural
instead of a coincidence two files have to keep re-discovering.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("app.media_encode")

# ── Audio parameters, pinned once for every producer of a clip segment ──
#
# A motion clip with the per-camera `record_audio` opt-in on is assembled
# from TWO independently encoded segments — the JPEG-derived pre-roll from
# this module, and the re-encoded main clip from
# camera_runtime/_recording/_ffmpeg_clip.py — which the concat demuxer then
# joins with a STREAM COPY first. A stream copy cannot resample: two
# segments that disagree on codec, sample rate or channel layout produce a
# file ffmpeg writes happily and no player decodes correctly. Both encoders
# pin the same three values from here, so the copy path is safe by
# construction instead of by luck. AAC because it is the only audio codec
# every browser will play out of an mp4.
AUDIO_SAMPLE_RATE = "48000"
AUDIO_CHANNELS = "2"
AUDIO_BITRATE = "128k"
#: lavfi input that fabricates silence with exactly those parameters.
SILENT_AUDIO_INPUT = f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_SAMPLE_RATE}"
#: Output-side ffmpeg args producing that same AAC layout. Tuple, not
#: list — a module-level list would be one `+=` away from being mutated
#: by a caller for every other caller.
AAC_OUTPUT_ARGS: tuple[str, ...] = (
    "-c:a",
    "aac",
    "-ar",
    AUDIO_SAMPLE_RATE,
    "-ac",
    AUDIO_CHANNELS,
    "-b:a",
    AUDIO_BITRATE,
)


def build_reencode_cmd(raw_path: Path, vid_path: Path, *, record_audio: bool) -> list[str]:
    """The raw-stream-copy → H.264 argv the motion path's re-encode runs.

    A pure function so the audio decision can be asserted on without a
    working ffmpeg binary (the sandbox and CI have none).

    ``record_audio`` is the per-camera opt-in (CAMERA_SCHEMA["record_audio"],
    default False — a microphone in a garden records the neighbours too, so
    it is never on for a camera nobody switched it on for). False emits the
    historical ``-an``: byte-for-byte the command this path has always run.
    True re-encodes whatever audio the RTSP stream-copy captured into the
    pinned AAC layout above — re-encoded rather than copied on purpose,
    because the camera may deliver G.711/PCM, which mp4 cannot carry at
    all, and because the pre-roll splice can only stream-copy two segments
    whose audio parameters match exactly.

    A camera with no microphone needs no special case: ffmpeg produces no
    audio stream and the audio codec options are simply ignored.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(raw_path),
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
    ]
    cmd += [*AAC_OUTPUT_ARGS] if record_audio else ["-an"]
    cmd.append(str(vid_path))
    return cmd


def build_jpeg_frames_cmd(
    out_path: Path,
    fps: int,
    *,
    crf: int = 23,
    preset: str = "fast",
    silent_audio: bool = False,
) -> list[str]:
    """The ffmpeg argv ``encode_jpeg_frames_to_mp4`` runs.

    Split out so the command line can be asserted on without a working
    ffmpeg binary — the sandbox and CI have none (see
    tests/test_motion_preroll.py's module docstring).

    ``silent_audio`` appends an ``anullsrc`` input and encodes it to the
    pinned AAC layout above, so the resulting segment has the SAME stream
    layout as an audio-bearing main clip. Without it the concat demuxer
    would be joining a 1-stream file to a 2-stream one.
    """
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
    ]
    if silent_audio:
        cmd += ["-f", "lavfi", "-i", SILENT_AUDIO_INPUT]
    cmd += [
        "-vcodec",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(int(crf)),
        "-pix_fmt",
        "yuv420p",
    ]
    if silent_audio:
        # -shortest: anullsrc never ends on its own, the JPEG pipe does.
        cmd += [*AAC_OUTPUT_ARGS, "-shortest"]
    cmd += ["-movflags", "+faststart", str(out_path)]
    return cmd


def encode_jpeg_frames_to_mp4(
    frames: list[tuple[float, bytes]],
    out_path: Path,
    fps: int,
    *,
    crf: int = 23,
    preset: str = "fast",
    log_tag: str = "[storage]",
    silent_audio: bool = False,
) -> bool:
    """Encode a ``[(timestamp, jpeg_bytes), ...]`` sequence to an H.264 mp4.

    The timestamp is the caller's bookkeeping only — frames are written to
    ffmpeg in list order at a constant ``fps``, real gaps between captures
    are not reproduced. Returns False on any failure (missing ffmpeg, spawn
    error, non-zero exit, or a missing/undersized result) so the caller can
    fall back to whatever it had before calling this.

    ``silent_audio=True`` gives the result a silent AAC track — see
    ``build_jpeg_frames_cmd``. Default False keeps every existing caller's
    command line byte-for-byte what it was.
    """
    if not frames:
        return False
    if not shutil.which("ffmpeg"):
        log.warning("%s ffmpeg unavailable — cannot encode jpeg-frame clip", log_tag)
        return False
    cmd = build_jpeg_frames_cmd(out_path, fps, crf=crf, preset=preset, silent_audio=silent_audio)
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
